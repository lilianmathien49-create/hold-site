#!/usr/bin/env python3
"""Transforme des fichiers de montre en blocs analysables.

    python3 tools/import_watch.py ~/Downloads/export_strava/activities \
        --out tools/mes-blocs.csv

Lit les .gpx et .tcx d'un dossier et en sort le même format que le simulateur,
pour que toute la chaîne d'analyse tourne ensuite sans rien changer :

    session, date, type, t_s, slope, mode, kmh, hr, temp

Trois choix qui méritent d'être explicités :

  LA PENTE. L'altitude GPS est bruitée de plusieurs mètres d'un point à l'autre.
  Dérivée brute, elle produit des pentes de 40 % sur du plat. On la lisse donc
  sur une fenêtre glissante avant de calculer quoi que ce soit, et on écarte
  les pentes absurdes.

  MARCHE OU COURSE. Les montres ne l'enregistrent pas. On la déduit de la
  cadence quand elle est disponible — une cadence sous 140 pas par minute en
  mouvement n'est pas de la course — et de la vitesse sinon.

  LA TEMPÉRATURE. Rarement présente dans les fichiers. Sans elle, on met une
  valeur neutre et on signale combien de séances sont concernées : l'effet de
  la chaleur ne sera estimable que sur celles qui l'ont.
"""
from __future__ import annotations

import argparse, csv, math, re, statistics as st, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fitread import read_fit
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

BLOCK_S = 15
MAX_SLOPE = 45.0          # au-delà, c'est du bruit d'altitude, pas du terrain
SMOOTH_M = 80.0           # fenêtre de lissage de l'altitude, en mètres


def haversine(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def parse_time(t: str):
    t = (t or "").strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.fromisoformat(t) if fmt is None else datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


def cadence_fit(p: dict):
    """Pas par minute, d'où qu'ils viennent.

    Le champ cadence compte une jambe : on le double. Beaucoup de montres ne
    l'écrivent pas mais écrivent la longueur de foulée ; la cadence s'en
    déduit, vitesse divisée par foulée. Sans cette déduction, ces séances
    passaient pour dépourvues de cadence, et la marche se devinait à la vitesse
    seule — ce qui échoue justement en montée.
    """
    if p.get("cad"):
        return p["cad"] * 2 if p["cad"] < 120 else p["cad"]
    if p.get("foulee") and p["foulee"] > 0.2 and p.get("speed"):
        return p["speed"] / p["foulee"] * 60
    return None


# Un dossier exporté contient tous les sports. Le nom de la séance le dit
# souvent ; quand il ne dit rien, l'allure tranche.
AUTRES_SPORTS = ("natation", "piscine", "swim", "cyclisme", "velo", "vélo", "gravel", "bike",
                 "ride", "vtt", "musculation", "renforcement", "padel", "tennis", "yoga", "ski",
                 "rameur", "elliptique", "marche_nordique", "randonnee", "kayak", "aviron")
V_PIED = (4.0, 22.0)            # km/h médians plausibles pour de la course ou du trail


def autre_sport(path: Path) -> bool:
    nom = path.name.lower()
    return any(m in nom for m in AUTRES_SPORTS)


def vitesse_mediane(pts) -> float:
    vs = []
    for a, b in zip(pts, pts[1:]):
        dt = (b[0] - a[0]).total_seconds()
        if dt <= 0:
            continue
        la1, lo1, la2, lo2 = map(math.radians, (a[1], a[2], b[1], b[2]))
        d = 2 * 6371000 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2
                                              + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))
        if d > 0.5:                     # à l'arrêt, la vitesse ne dit rien du sport
            vs.append(d / dt * 3.6)
    return st.median(vs) if vs else 0.0


def read_points(path: Path):
    """Renvoie [(instant, lat, lon, altitude, fc, cadence, température)]."""
    if path.name.lower().endswith((".fit", ".fit.gz")):
        return [(p["t"], p["lat"], p["lon"], p.get("alt", 0.0), p.get("hr"), cadence_fit(p),
                 p.get("temp"))
                for p in read_fit(path) if "t" in p and "lat" in p and "lon" in p]
    try:
        if path.name.lower().endswith(".gz"):
            import gzip
            root = ET.fromstring(gzip.decompress(path.read_bytes()))
        else:
            root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return []
    ns = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""
    out = []

    if "TrainingCenterDatabase" in root.tag:          # TCX
        n = {"t": ns, "x": "http://www.garmin.com/xmlschemas/ActivityExtension/v2"}
        for tp in root.findall(".//t:Trackpoint", n):
            g = lambda p, d=None: (tp.findtext(p, namespaces=n) or d)
            t = parse_time(g("t:Time"))
            lat, lon = g("t:Position/t:LatitudeDegrees"), g("t:Position/t:LongitudeDegrees")
            if not t or lat is None or lon is None:
                continue
            hr = g("t:HeartRateBpm/t:Value")
            cad = g("t:Cadence") or g(".//x:RunCadence")
            out.append((t, float(lat), float(lon),
                        float(g("t:AltitudeMeters") or 0),
                        float(hr) if hr else None,
                        float(cad) * (2 if cad and float(cad) < 120 else 1) if cad else None,
                        None))
        return out

    n = {"g": ns}                                      # GPX
    for p in root.findall(".//g:trkpt", n):
        t = parse_time(p.findtext("g:time", namespaces=n))
        if t is None:
            continue
        ext = " ".join(e.tag.split("}")[-1] + "=" + (e.text or "")
                       for e in p.iter() if e.text and e.tag.split("}")[-1] in
                       ("hr", "cad", "atemp", "TrackPointExtension"))
        grab = lambda k: (lambda m: float(m.group(1)) if m else None)(re.search(k + r"=([\d.]+)", ext))
        cad = grab("cad")
        out.append((t, float(p.get("lat")), float(p.get("lon")),
                    float(p.findtext("g:ele", default="0", namespaces=n) or 0),
                    grab("hr"), cad * 2 if cad and cad < 120 else cad, grab("atemp")))
    return out


def smooth_altitude(pts):
    """Moyenne glissante sur une fenêtre en mètres. L'altitude GPS varie de
    plusieurs mètres d'un point à l'autre : sa dérivée brute est inexploitable."""
    n = len(pts)
    cum = [0.0]
    for i in range(1, n):
        cum.append(cum[-1] + haversine(pts[i-1][1:3], pts[i][1:3]))
    out, j0, j1 = [], 0, 0
    for i in range(n):
        while cum[i] - cum[j0] > SMOOTH_M / 2:
            j0 += 1
        while j1 < n - 1 and cum[j1] - cum[i] < SMOOTH_M / 2:
            j1 += 1
        out.append(st.mean(p[3] for p in pts[j0:j1 + 1]))
    return out, cum


def to_blocks(pts, sid, kind, writer):
    if len(pts) < 40:
        return 0, 0
    pts.sort(key=lambda p: p[0])
    alt, cum = smooth_altitude(pts)
    t0 = pts[0][0]
    temps = [p[6] for p in pts if p[6] is not None]
    temp = round(st.median(temps), 1) if temps else None

    written = 0
    i = 0
    while i < len(pts) - 1:
        t_start = (pts[i][0] - t0).total_seconds()
        j = i
        while j < len(pts) - 1 and (pts[j][0] - pts[i][0]).total_seconds() < BLOCK_S:
            j += 1
        dt = (pts[j][0] - pts[i][0]).total_seconds()
        dist = cum[j] - cum[i]
        if dt <= 0 or dist < 1:
            i = j if j > i else i + 1
            continue
        kmh = dist / 1000 / (dt / 3600)
        if kmh > 30:                       # saut GPS
            i = j
            continue
        slope = (alt[j] - alt[i]) / dist * 100
        if abs(slope) > MAX_SLOPE:
            i = j
            continue
        hrs = [p[4] for p in pts[i:j+1] if p[4]]
        cads = [p[5] for p in pts[i:j+1] if p[5]]
        # La montre ne dit pas si on marche. La cadence le trahit : sous 140 pas
        # par minute en mouvement, ce n'est plus de la course.
        if cads:
            walking = st.mean(cads) < 140
        else:
            # Repli sans cadence. Il est nettement moins sûr : sur du terrain
            # raide, une course lente et une marche rapide se recouvrent autour
            # de 5 à 6 km/h, et aucune vitesse ne les sépare. Si tes fichiers
            # n'ont pas la cadence, le seuil de marche sera mal estimé.
            walking = kmh < 6.5
        writer.writerow([sid, t0.date().isoformat(), kind, int(t_start), round(slope, 2),
                         "marche" if walking else "course", round(kmh, 2),
                         round(st.mean(hrs)) if hrs else "", temp if temp is not None else ""])
        written += 1
        i = j
    return written, 1 if temp is not None else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="dossier contenant les .gpx et .tcx")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-minutes", type=float, default=20, help="ignorer les sorties plus courtes")
    a = ap.parse_args()

    folder = Path(a.folder).expanduser()
    if not folder.is_dir():
        print(f"Dossier introuvable : {folder}", file=sys.stderr)
        return 1
    EXT = (".gpx", ".tcx", ".fit")
    files = sorted([p for p in folder.rglob("*")
                    if p.name.lower().endswith(EXT) or p.name.lower().endswith(tuple(e + ".gz" for e in EXT))])
    if not files:
        print(f"Aucun .gpx ni .tcx dans {folder}.", file=sys.stderr)
        print("Formats lus : .gpx, .tcx, .fit, et leurs versions .gz telles que "
              "Strava les livre.", file=sys.stderr)
        return 1

    print(f"  {len(files)} fichiers trouvés")
    sid = total = with_temp = skipped = with_hr = with_cad = sports = 0
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["session", "date", "type", "t_s", "slope", "mode", "kmh", "hr", "temp"])
        no_time = []
        for path in files:
            if autre_sport(path):
                sports += 1
                continue
            pts = read_points(path)
            if not pts:
                # Un fichier de parcours n'a pas d'horodatage : il décrit un
                # itinéraire, pas une sortie. Le dire plutôt que de le compter
                # comme « trop court ».
                no_time.append(path.name)
                skipped += 1
                continue
            if len(pts) < 40:
                skipped += 1
                continue
            mins = (pts[-1][0] - pts[0][0]).total_seconds() / 60
            if mins < a.min_minutes:
                skipped += 1
                continue
            if not V_PIED[0] <= vitesse_mediane(pts) <= V_PIED[1]:
                sports += 1
                continue
            sid += 1
            n, t = to_blocks(pts, sid, "sortie", w)
            total += n
            with_temp += t
            if any(p[4] for p in pts):
                with_hr += 1
            if any(p[5] for p in pts):
                with_cad += 1

    print(f"  {sid} séances retenues · {skipped} écartées")
    if sports:
        print(f"  dont {sports} d'un autre sport que la course à pied (vélo, natation…), mises de côté")
    if no_time:
        print(f"  dont {len(no_time)} sans horodatage : ce sont des tracés de parcours, "
              f"pas des enregistrements de sortie")
        for nm in no_time[:3]:
            print(f"      {nm}")
    print(f"  {total:,} blocs de {BLOCK_S} s, soit {total*BLOCK_S/3600:.0f} heures".replace(",", " "))
    print(f"  {with_hr} séances avec fréquence cardiaque")
    print(f"  {with_cad} séances avec cadence")
    print(f"  {with_temp} séances avec température")
    if with_cad < sid * 0.5:
        print("\n  Attention : moins de la moitié des séances portent la cadence. Sans elle, "
              "marche et course se distinguent par la vitesse seule, ce qui échoue sur terrain "
              "raide où les deux se recouvrent. Le seuil de marche en pâtira.")
    if with_hr < sid * 0.5:
        print("\n  Attention : moins de la moitié des séances portent la FC. "
              "La dérive cardiaque et le coût de la chaleur seront mal estimés.")
    if with_temp < 10:
        print("\n  Attention : presque aucune température dans les fichiers. L'effet de la chaleur "
              "ne sera pas estimable. On peut la retrouver a posteriori par la date et le lieu, "
              "avec les archives météo — dis-le-moi si tu veux que je l'ajoute.")
    print(f"\n  Écrit : {a.out}")
    print("  Ensuite :")
    print(f"    python3 tools/fit_gam.py {a.out} --out tools/mon-profil.json\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
