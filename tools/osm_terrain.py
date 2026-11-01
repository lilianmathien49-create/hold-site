#!/usr/bin/env python3
"""Le terrain d'une course d'après OpenStreetMap, point par point.

    python3 tools/osm_terrain.py data/utmb.gpx --out tools/utmb-terrain.json

Pour chaque point du tracé, on cherche le chemin OpenStreetMap le plus proche
(30 m au plus) et on en relève ce que les contributeurs ont noté :

  · le type de voie : route, piste carrossable, sentier, escalier ;
  · la difficulté de randonnée (sac_scale) : T1 sentier facile … T6 alpin ;
  · le revêtement : goudron, gravier, terre ou herbe, rocher ou cailloux ;
  · l'état (smoothness) et la difficulté VTT (mtb:scale), quand ils existent.

On y ajoute la sinuosité, mesurée sur le tracé lui-même : les degrés de virage
par kilomètre. Un single qui serpente en lacets coûte, même sans pente.

Une seule requête à l'API Overpass, mise en cache sur disque : relancer ne
retélécharge rien. Les données OpenStreetMap sont sous licence ODbL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
from pathlib import Path

from build_plan import read_gpx, haversine

CACHE = Path(__file__).resolve().parent / ".cache-osm"
OVERPASS = "https://overpass-api.de/api/interpreter"
UA = "Hold/1.0 (analyse de terrain pour coaching; holdrunning.fr)"
RAYON = 30  # mètres

ROUTE = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
         "service", "living_street", "road", "pedestrian"}
DUR = {"asphalt", "paved", "concrete", "paving_stones", "sett", "concrete:plates", "metal", "wood"}
GRAVIER = {"gravel", "fine_gravel", "compacted", "pebblestone", "unpaved"}
TERRE = {"ground", "dirt", "earth", "grass", "mud", "sand", "grass_paver", "soil"}
ROCHE = {"rock", "stone", "rocks", "scree", "bare_rock"}
SAC = {"hiking": 1, "mountain_hiking": 2, "demanding_mountain_hiking": 3, "alpine_hiking": 4,
       "demanding_alpine_hiking": 5, "difficult_alpine_hiking": 6}


def requete(pts) -> dict:
    """Tous les chemins à moins de RAYON mètres du tracé, géométrie comprise.

    Le tracé est demandé par morceaux d'une quinzaine de kilomètres : une seule
    requête pour 170 km dépasse ce que le serveur accepte de calculer."""
    # Un point tous les 150 m environ suffit à décrire le couloir.
    pas, poly, d = 150.0, [pts[0]], 0.0
    for a, b in zip(pts, pts[1:]):
        d += haversine(a[:2], b[:2])
        if d >= pas:
            poly.append(b)
            d = 0.0
    CACHE.mkdir(exist_ok=True)
    vus, elements = set(), []
    # Une réponse vide sur un morceau de sentier n'est pas un désert : c'est le
    # serveur qui a abandonné sans le dire. On redemande alors en deux moitiés.
    file_ = [poly[i:i + 101] for i in range(0, len(poly), 100)]
    n = 0
    while file_:
        m = file_.pop(0)
        n += 1
        coords = ",".join(f"{p[0]:.5f},{p[1]:.5f}" for p in m)
        q = f"[out:json][timeout:120];way(around:{RAYON},{coords})[highway];out tags geom;"
        f = CACHE / (hashlib.sha1(q.encode()).hexdigest()[:16] + ".json")
        if not f.is_file():
            for essai in range(3):
                r = subprocess.run(["curl", "-sS", "--fail", "-A", UA, "--max-time", "180",
                                    "--data-urlencode", f"data={q}", OVERPASS], capture_output=True)
                if r.returncode == 0 and json.loads(r.stdout or b"{}").get("elements"):
                    f.write_bytes(r.stdout)
                    break
                time.sleep(10)
            else:
                if len(m) > 12:
                    moitie = len(m) // 2
                    file_[:0] = [m[:moitie + 1], m[moitie:]]
                    print(f"    morceau de {len(m)} points vide : redemandé en deux moitiés")
                else:
                    print(f"    morceau de {len(m)} points sans chemin connu : laissé vide")
                continue
            time.sleep(2)  # on ménage le serveur
        for w in json.loads(f.read_text()).get("elements", []):
            if w.get("id") not in vus:
                vus.add(w.get("id"))
                elements.append(w)
        print(f"    {n} requêtes · {len(elements)} chemins", end="\r", flush=True)
    print()
    return {"elements": elements}

def classe(tags: dict) -> dict:
    hw = tags.get("highway", "")
    surf = tags.get("surface", "")
    voie = ("escalier" if hw == "steps" else "route" if hw in ROUTE
            else "piste" if hw == "track" else "sentier" if hw in {"path", "footway", "bridleway", "cycleway"}
            else "autre")
    rev = ("dur" if surf in DUR else "gravier" if surf in GRAVIER else "terre" if surf in TERRE
           else "roche" if surf in ROCHE else None)
    mtb = tags.get("mtb:scale", "")
    return {"voie": voie, "rev": rev, "sac": SAC.get(tags.get("sac_scale", "")),
            "mtb": int(mtb[0]) if mtb[:1].isdigit() else None,
            "lisse": tags.get("smoothness"), "visibilite": tags.get("trail_visibility")}


def plus_proche(lat, lon, index, cos_lat):
    """Le chemin dont un tronçon passe le plus près du point, et sa distance (m)."""
    meilleur, dmin = None, RAYON
    cle = (round(lat / 0.002), round(lon / 0.002))
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            for (a, b, w) in index.get((cle[0] + di, cle[1] + dj), ()):
                # Distance point–segment en mètres, sur un plan local.
                ax, ay = (a[1] - lon) * 111320 * cos_lat, (a[0] - lat) * 110540
                bx, by = (b[1] - lon) * 111320 * cos_lat, (b[0] - lat) * 110540
                dx, dy = bx - ax, by - ay
                t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy or 1)))
                d = math.hypot(ax + t * dx, ay + t * dy)
                if d < dmin:
                    meilleur, dmin = w, d
    return meilleur, dmin


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gpx")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pts, _ = read_gpx(Path(args.gpx))
    osm = requete(pts)
    chemins = [w for w in osm.get("elements", []) if w.get("type") == "way" and w.get("geometry")]
    print(f"  {len(chemins)} chemins OpenStreetMap le long du tracé")

    index = {}
    for k, w in enumerate(chemins):
        g = [(n["lat"], n["lon"]) for n in w["geometry"]]
        for a, b in zip(g, g[1:]):
            for c in {(round(a[0] / 0.002), round(a[1] / 0.002)), (round(b[0] / 0.002), round(b[1] / 0.002))}:
                index.setdefault(c, []).append((a, b, k))
    infos = [classe(w.get("tags", {})) for w in chemins]

    # Chaque point du tracé : sa distance cumulée, son chemin, son cap.
    cos_lat = math.cos(math.radians(pts[0][0]))
    out, km = [], 0.0
    for i, p in enumerate(pts):
        if i:
            km += haversine(pts[i - 1][:2], p[:2]) / 1000
        w, d = plus_proche(p[0], p[1], index, cos_lat)
        out.append({"km": round(km, 4), **(infos[w] if w is not None else {"voie": None})})

    # La sinuosité : on lisse d'abord le tracé sur ~40 m pour ne pas compter le
    # bruit du GPS, puis on additionne les changements de cap, en degrés par km.
    pas = 3
    caps = []
    for i in range(0, len(pts) - pas, pas):
        a, b = pts[i], pts[i + pas]
        caps.append((out[i]["km"], math.degrees(math.atan2((b[1] - a[1]) * cos_lat, b[0] - a[0]))))
    virages = []
    for (k0, c0), (k1, c1) in zip(caps, caps[1:]):
        dc = abs((c1 - c0 + 180) % 360 - 180)
        virages.append((k1, dc))

    trouves = sum(1 for o in out if o["voie"])
    print(f"  {trouves / len(out):.0%} du tracé rattaché à un chemin · "
          f"difficulté renseignée sur {sum(1 for o in out if o.get('sac')) / len(out):.0%} · "
          f"revêtement sur {sum(1 for o in out if o.get('rev')) / len(out):.0%}")
    Path(args.out).write_text(json.dumps({
        "source": "OpenStreetMap (ODbL), via Overpass", "rayon": RAYON,
        "points": out, "virages": virages}, ensure_ascii=False))
    print(f"  écrit : {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
