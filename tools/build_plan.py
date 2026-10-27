#!/usr/bin/env python3
"""Calcule un plan de course au pas de 500 m à partir d'un GPX.

    python3 tools/build_plan.py --gpx data/utmb.gpx --race UTMB \
        --runner "Thomas Riva" --target 28:00 --start "2027-08-27 18:00" \
        --tmin 4 --tmax 24 --out tools/plan-thomas.json

Ce que le script décide tout seul, segment par segment :
  · la pente, donc marche ou course via le seuil mesuré du coureur ;
  · la vitesse, via le coût énergétique de Minetti, calibrée pour tenir l'objectif ;
  · l'heure de passage, donc le jour ou la nuit, par la position réelle du soleil ;
  · la température, par l'heure et l'altitude du point.

Ce qu'il ne devine pas : la météo réelle (donne --tmin/--tmax de la prévision) et
les temps de passage historiques des finishers (option --reference).
"""
from __future__ import annotations

import argparse, json, math, sys, unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

STEP_M = 500.0          # pas d'analyse demandé
LAPSE = 0.0065          # refroidissement de l'air, °C par mètre d'altitude
CIVIL_TWILIGHT = -6.0   # au-dessous, il faut la frontale

# --- Coût énergétique de la locomotion en pente (Minetti & al. 2002, J Appl Physiol).
# i est la pente en fraction (0,10 = 10 %). Le coût sert de diviseur : à puissance
# constante, la vitesse est inversement proportionnelle au coût par mètre.
def cost_run(i: float) -> float:
    i = max(-0.45, min(0.45, i))
    return max(1.5, 155.4*i**5 - 30.4*i**4 - 43.3*i**3 + 46.3*i**2 + 19.5*i + 3.6)

def cost_walk(i: float) -> float:
    i = max(-0.45, min(0.45, i))
    return max(1.2, 280.5*i**5 - 58.7*i**4 - 76.8*i**3 + 51.9*i**2 + 19.6*i + 2.5)

# Minetti mesure un coût énergétique sur tapis : en descente il s'effondre, et le
# modèle voudrait faire dévaler à 20 km/h. Sur un sentier de montagne, ce n'est plus
# l'énergie qui limite mais le pied, la pente technique et les quadriceps. On plafonne
# donc le gain de la descente au lieu de suivre la courbe jusqu'au bout.
GAIN_RUN, GAIN_WALK = 1.18, 1.10
# Plafond absolu : sur sentier alpin, même en descente et même frais, on ne
# dépasse pas ces vitesses en ultra. Sans ça le modèle fait dévaler à 20 km/h.
V_MAX_RUN, V_MAX_WALK, V_MIN = 13.5, 7.0, 1.0

def speed_ratio(grade: float, walking: bool) -> float:
    cost = cost_walk(grade) if walking else cost_run(grade)
    flat = cost_walk(0.0) if walking else cost_run(0.0)
    return min(flat / cost, GAIN_WALK if walking else GAIN_RUN)


# --- Position du soleil (algorithme NOAA simplifié) : suffisant au degré près.
def solar_elevation(when: datetime, lat: float, lon: float) -> float:
    n = when.astimezone(timezone.utc).timestamp() / 86400.0 + 2440587.5 - 2451545.0
    mean_long = math.radians((280.460 + 0.9856474 * n) % 360)
    anomaly = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.degrees(mean_long) + 1.915 * math.sin(anomaly) + 0.020 * math.sin(2 * anomaly)
    lam = math.radians(lam % 360)
    eps = math.radians(23.439 - 0.0000004 * n)
    dec = math.asin(math.sin(eps) * math.sin(lam))
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    hour_angle = math.radians((gmst * 15 + lon) % 360) - ra
    la = math.radians(lat)
    s = math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def light_at(when: datetime, lat: float, lon: float) -> str:
    e = solar_elevation(when, lat, lon)
    if e < CIVIL_TWILIGHT:
        return "nuit"
    return "jour" if e > 0 else "entre chien et loup"


def temp_at(when: datetime, altitude: float, tmin: float, tmax: float, ref_alt: float) -> float:
    """Cycle journalier au niveau de la vallée, corrigé du gradient d'altitude.
    Le minimum tombe vers 5 h, le maximum vers 15 h."""
    h = when.hour + when.minute / 60
    mean, amp = (tmax + tmin) / 2, (tmax - tmin) / 2
    valley = mean - amp * math.cos(math.pi * (h - 5) / 10) if 5 <= h <= 15 else \
             mean + amp * math.cos(math.pi * ((h - 15) % 24) / 14)
    return valley - LAPSE * (altitude - ref_alt)


def gear_for(temp: float, light: str) -> list[str]:
    g = []
    if light == "nuit":
        g.append("frontale")
    if temp <= 8:
        g.append("gants")
    if temp <= 4:
        g.append("veste chaude")
    if temp <= 0:
        g.append("bonnet")
    if temp >= 24:
        g.append("casquette")
    return g


# --- GPX
def haversine(a, b) -> float:
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp/2)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl/2)**2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def read_gpx(path: Path):
    root = ET.parse(path).getroot()
    ns = {"g": root.tag.split("}")[0].strip("{")}
    pts = []
    for p in root.findall(".//g:trkpt", ns):
        ele = p.find("g:ele", ns)
        pts.append((float(p.get("lat")), float(p.get("lon")), float(ele.text) if ele is not None else 0.0))
    wpts = []
    for w in root.findall("g:wpt", ns):
        name = w.find("g:name", ns)
        wpts.append((float(w.get("lat")), float(w.get("lon")), name.text.strip() if name is not None else "?"))
    if len(pts) < 2:
        raise SystemExit(f"{path} ne contient pas de trace exploitable.")
    return pts, wpts


def to_segments(pts, step=STEP_M):
    """Découpe la trace en tronçons d'environ `step` mètres, lissés en altitude."""
    cum, out = 0.0, []
    seg_d = seg_up = seg_dn = 0.0
    start_alt, start_km = pts[0][2], 0.0
    for i in range(1, len(pts)):
        d = haversine(pts[i-1][:2], pts[i][:2])
        dz = pts[i][2] - pts[i-1][2]
        cum += d
        seg_d += d
        if dz > 0: seg_up += dz
        else: seg_dn -= dz
        if seg_d >= step:
            out.append({"km0": start_km, "km1": cum/1000, "dist": seg_d, "up": seg_up, "down": seg_dn,
                        "alt0": start_alt, "alt1": pts[i][2],
                        "lat": pts[i][0], "lon": pts[i][1]})
            start_km, start_alt = cum/1000, pts[i][2]
            seg_d = seg_up = seg_dn = 0.0
    if seg_d > 50:
        out.append({"km0": start_km, "km1": cum/1000, "dist": seg_d, "up": seg_up, "down": seg_dn,
                    "alt0": start_alt, "alt1": pts[-1][2], "lat": pts[-1][0], "lon": pts[-1][1]})
    for s in out:
        s["slope"] = (s["alt1"] - s["alt0"]) / s["dist"] * 100 if s["dist"] else 0.0
    return out


def locate_waypoints(wpts, pts):
    """Place chaque ravitaillement au kilomètre de la trace dont il est le plus proche."""
    cum, marks = [0.0], 0.0
    for i in range(1, len(pts)):
        marks += haversine(pts[i-1][:2], pts[i][:2])
        cum.append(marks)
    out = []
    for lat, lon, name in wpts:
        j = min(range(len(pts)), key=lambda i: haversine((lat, lon), pts[i][:2]))
        out.append({"km": cum[j]/1000, "name": name, "alt": pts[j][2],
                    "lat": pts[j][0], "lon": pts[j][1]})
    out.sort(key=lambda w: w["km"])
    return out


def terrain_class(slope: float) -> str:
    """Cinq familles de terrain. C'est ce qui décide où couper : un découpage
    tous les 500 m hache une montée de six kilomètres en douze lignes identiques."""
    if slope >= 12: return "raide"
    if slope >= 4: return "montee"
    if slope > -4: return "plat"
    if slope > -12: return "descente"
    return "plongeon"


def to_sections(out_segs, aid, min_km=2.0):
    """Regroupe les tronçons de 500 m en portions de terrain homogène, coupées
    aux ravitaillements. On obtient les bosses et les descentes réelles au lieu
    d'une liste plate."""
    marks = sorted({round(a["km"], 2) for a in aid if a["km"] > 0.2})
    def boundary(km):
        return any(abs(km - m) < 0.26 for m in marks)

    runs = [{"segs": [s]} for s in out_segs]

    def grade(r):
        d = r["segs"][-1]["km1"] - r["segs"][0]["km0"]
        return (r["segs"][-1]["alt"] - r["segs"][0]["alt"]) / (d * 10) if d else 0.0
    def length(r):
        return r["segs"][-1]["km1"] - r["segs"][0]["km0"]

    # Fusion progressive : à chaque tour on réunit le couple de voisins dont les
    # pentes sont les plus proches, tant que l'écart reste faible. Une montée de
    # six kilomètres qui ondule entre 8 et 13 % reste ainsi une seule montée.
    while len(runs) > 1:
        best, best_gap = None, None
        for i in range(len(runs) - 1):
            a_, b_ = runs[i], runs[i + 1]
            if boundary(b_["segs"][0]["km0"]):
                continue
            gap = abs(grade(a_) - grade(b_))
            # Une portion encore courte se fond plus facilement que deux longues.
            tol = 10.0 if min(length(a_), length(b_)) < min_km else 5.5
            if gap > tol or length(a_) + length(b_) > 13.0:
                continue
            if best_gap is None or gap < best_gap:
                best, best_gap = i, gap
        if best is None:
            break
        runs[best]["segs"].extend(runs[best + 1]["segs"])
        runs.pop(best + 1)

    for r in runs:
        r["cls"] = terrain_class(grade(r))

    out = []
    for r in runs:
        ss = r["segs"]
        dist = ss[-1]["km1"] - ss[0]["km0"]
        up = sum(x["up"] for x in ss)
        down = sum(x["down"] for x in ss)
        dt = sum(x["split"] for x in ss)
        walk_km = sum((x["km1"] - x["km0"]) for x in ss if x["mode"] == "marche")
        nxt = next((a["name"] for a in aid if abs(a["km"] - ss[-1]["km1"]) < 0.3), None)
        out.append({
            "km0": round(ss[0]["km0"], 2), "km1": round(ss[-1]["km1"], 2),
            "lat": ss[0].get("lat"), "lon": ss[0].get("lon"),
            "dist": round(dist, 2), "up": round(up), "down": round(down),
            "alt0": ss[0]["alt"], "alt1": ss[-1]["alt"],
            "slope": round((ss[-1]["alt"] - ss[0]["alt"]) / (dist * 10), 1) if dist else 0.0,
            "cls": r["cls"], "split": dt, "cumul": ss[-1]["cumul"], "clock": ss[-1]["clock"],
            "kmh": round(dist / (dt / 3600), 2) if dt else 0,
            "pace": pace_str(dt / dist) if dist else "—",
            "vam": round(up / (dt / 3600)) if dt and up > 30 else None,
            "walkShare": round(walk_km / dist * 100) if dist else 0,
            "poles": any(x["poles"] for x in ss),
            "light": max({x["light"] for x in ss}, key=lambda L: sum(1 for x in ss if x["light"] == L)),
            "tmin": min(x["temp"] for x in ss), "tmax": max(x["temp"] for x in ss),
            "aid": nxt,
        })
    return out


def hms(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds//3600}:{seconds%3600//60:02d}:{seconds%60:02d}"

def hm(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds//3600}h{seconds%3600//60:02d}"

def pace_str(sec_per_km: float) -> str:
    if sec_per_km > 3600:
        return "—"
    return f"{int(sec_per_km)//60}:{int(sec_per_km)%60:02d}"


def simulate(segs, scale, a):
    """Déroule la course une fois. `scale` fixe l'allure de base ; on le cherche
    ensuite par dichotomie pour tomber sur l'objectif."""
    t = 0.0
    rows = []
    for s in segs:
        hours = t / 3600
        # Le seuil de marche du coureur baisse avec le temps écoulé (ses propres données).
        thr = max(a.walk_floor, a.walk_thr - a.walk_decay * hours)
        walking = s["slope"] >= thr
        grade = s["slope"] / 100
        base = a.walk_flat if walking else a.run_flat
        # Perte de rendement au fil des heures : la durabilité mesurée du coureur.
        fade = max(0.60, 1 - a.fatigue / 100 * max(0, hours - 1))
        v = base * speed_ratio(grade, walking) * fade * scale          # km/h
        v = max(V_MIN, min(V_MAX_WALK if walking else V_MAX_RUN, v))
        dt = s["dist"] / 1000 / v * 3600
        t += dt
        rows.append((walking, v, dt, t, thr))
    return rows, t


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--gpx", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--runner", default="")
    p.add_argument("--race", default="")
    p.add_argument("--target", required=True, help="objectif, en h:mm (ex. 28:00)")
    p.add_argument("--start", required=True, help="départ, 'AAAA-MM-JJ HH:MM' en heure locale")
    p.add_argument("--tz", type=float, default=2.0, help="décalage horaire du lieu (défaut +2, été en France)")
    p.add_argument("--lat", type=float, default=45.9237, help="latitude, pour le calcul jour/nuit")
    p.add_argument("--lon", type=float, default=6.8694)
    p.add_argument("--tmin", type=float, default=6.0, help="température minimale prévue en vallée")
    p.add_argument("--tmax", type=float, default=22.0, help="température maximale prévue en vallée")
    p.add_argument("--ref-alt", type=float, default=1035.0, help="altitude du point de prévision")
    p.add_argument("--walk-thr", type=float, default=8.8, help="pente de bascule à la marche, frais (%%)")
    p.add_argument("--walk-decay", type=float, default=0.775, help="baisse du seuil par heure (%%)")
    p.add_argument("--walk-floor", type=float, default=4.0, help="plancher du seuil (%%)")
    p.add_argument("--fatigue", type=float, default=1.2, help="perte de vitesse par heure au-delà de la 1re (%%)")
    p.add_argument("--run-flat", type=float, default=11.0, help="vitesse de course sur le plat, frais (km/h)")
    p.add_argument("--walk-flat", type=float, default=5.6, help="vitesse de marche sur le plat (km/h)")
    p.add_argument("--reference", help="JSON des temps de passage historiques, si tu en as")
    p.add_argument("--splits", help="temps de passage appris (learn_splits.py) : le plan s'y cale")
    p.add_argument("--night-penalty", type=float, default=0.0,
                   help="surcoût mesuré de la nuit, en %% (ex. 4.6)")
    a = p.parse_args()

    try:
        hh, mm = a.target.split(":")
        target = int(hh) * 3600 + int(mm) * 60
    except ValueError:
        print("--target attend un format h:mm, par exemple 28:00", file=sys.stderr)
        return 1
    tz = timezone(timedelta(hours=a.tz))
    try:
        start = datetime.strptime(a.start, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError:
        print("--start attend 'AAAA-MM-JJ HH:MM'", file=sys.stderr)
        return 1

    pts, wpts = read_gpx(Path(a.gpx))
    segs = to_segments(pts)
    aid = locate_waypoints(wpts, pts)
    total_km = segs[-1]["km1"]
    total_up = sum(s["up"] for s in segs)
    print(f"  Trace : {total_km:.1f} km · {total_up:.0f} m D+ · {len(segs)} tronçons de {STEP_M:.0f} m")

    # Dichotomie sur l'allure de base pour atteindre l'objectif.
    lo, hi = 0.25, 4.0
    for _ in range(60):
        mid = (lo + hi) / 2
        _, t = simulate(segs, mid, a)
        if t > target: lo = mid
        else: hi = mid
    rows, total = simulate(segs, (lo + hi) / 2, a)
    print(f"  Calibrage : objectif {hm(target)} · simulé {hms(total)}  (écart {abs(total-target):.0f} s)")

    # --- Apprentissage : on recale chaque inter-ravitaillement sur le temps
    # qu'y ont réellement mis les finishers du même chrono. La physique continue
    # de répartir le temps à l'intérieur du tronçon, elle ne décide plus du rythme.
    learned = None
    if a.splits:
        learned = json.loads(Path(a.splits).read_text(encoding="utf-8"))
        # Seuls les points réellement observés servent d'ancre. Un point interpolé
        # le serait linéairement en kilomètres, ce qui ignore le dénivelé : entre
        # deux ancres, le modèle répartit bien mieux que ça.
        anchors = [(p["km"], p["eta"]) for p in learned["points"]
                   if p.get("matched") and not p.get("start") and p.get("eta")]
        anchors = sorted({km: eta for km, eta in anchors}.items())
        if anchors:
            rows = list(rows)
            prev_km, prev_t = 0.0, 0.0
            shifts, capped = [], []
            for km_mark, eta in anchors:
                idx = [i for i, s in enumerate(segs) if prev_km <= s["km0"] < km_mark]
                if not idx:
                    continue
                raw = sum(rows[i][2] for i in idx)
                want = eta - prev_t
                if raw > 0 and want > 0:
                    # Chaque tronçon a un temps plancher, celui de sa vitesse maximale.
                    # On ne comprime que ce qui dépasse ce plancher, sinon accélérer
                    # un inter-ravitaillement ferait dévaler les descentes à 20 km/h.
                    floor = [segs[i]["dist"] / 1000 / (V_MAX_WALK if rows[i][0] else V_MAX_RUN) * 3600
                             for i in idx]
                    base = sum(floor)
                    if want >= raw:
                        # Ralentir est toujours possible : on étire tout du même facteur.
                        new = [rows[i][2] * (want / raw) for i in idx]
                    elif want > base:
                        # Accélérer, mais sans passer sous le temps plancher de chaque
                        # tronçon : on ne comprime que la marge au-dessus du plancher.
                        slack = [rows[i][2] - f for i, f in zip(idx, floor)]
                        r = (want - base) / sum(slack)
                        new = [f + sl * r for f, sl in zip(floor, slack)]
                    else:
                        # Le temps appris est plus rapide que le plafond de vitesse
                        # ne l'autorise : on pose le plancher et on le signale.
                        new = floor
                        capped.append((prev_km, km_mark, want, base))
                    for i, dt in zip(idx, new):
                        walking, _, _, _, thr = rows[i]
                        rows[i] = (walking, segs[i]["dist"] / 1000 / (dt / 3600), dt, 0.0, thr)
                    shifts.append((prev_km, km_mark, want / raw))
                prev_km, prev_t = km_mark, eta
            # On redéroule les cumuls après recalage.
            t = 0.0
            for i, (walking, v, dt, _, thr) in enumerate(rows):
                t += dt
                rows[i] = (walking, v, dt, t, thr)
            total = t
            if capped:
                print(f"  {len(capped)} inter-ravitaillements demandaient plus vite que le plafond "
                      f"de vitesse : ils ont été posés au plancher.")
            worst = max(shifts, key=lambda s: abs(s[2] - 1)) if shifts else None
            print(f"  Recalé sur {len(anchors)} temps de passage appris de "
                  f"{learned['runners']} finishers · total {hms(total)}")
            if worst:
                print(f"  Plus gros écart au modèle : km {worst[0]:.0f}–{worst[1]:.0f}, "
                      f"{(worst[2]-1)*100:+.0f} % de temps")

    # Construction des tronçons enrichis.
    out_segs, walk_km = [], 0.0
    for s, (walking, v, dt, t, thr) in zip(segs, rows):
        when = start + timedelta(seconds=t)
        alt = (s["alt0"] + s["alt1"]) / 2
        light = light_at(when, a.lat, a.lon)
        temp = temp_at(when, alt, a.tmin, a.tmax, a.ref_alt)
        if walking: walk_km += s["dist"] / 1000
        out_segs.append({
            "km0": round(s["km0"], 2), "km1": round(s["km1"], 2),
            "alt": round(alt), "slope": round(s["slope"], 1),
            "up": round(s["up"]), "down": round(s["down"]),
            "mode": "marche" if walking else "course",
            "poles": bool(walking and s["slope"] >= 15),
            "kmh": round(v, 2), "pace": pace_str(3600 / v),
            # Vitesse ascensionnelle : mètres de dénivelé avalés par heure.
            "vam": round(s["up"] / (dt / 3600)) if dt > 0 and s["up"] > 5 else None,
            "split": int(round(dt)), "cumul": hms(t),
            "clock": when.strftime("%H:%M"), "day": (when - start).days + 1,
            "light": light, "temp": round(temp, 1), "thr": round(thr, 1),
            "lat": round(s["lat"], 5), "lon": round(s["lon"], 5),
        })

    # Ravitaillements : heure de passage interpolée sur le tronçon qui les contient.
    def time_at_km(km):
        for s, (_, _, _, t, _) in zip(segs, rows):
            if s["km1"] >= km:
                return t
        return rows[-1][3]
    out_aid = []
    for w in aid:
        t = time_at_km(w["km"])
        when = start + timedelta(seconds=t)
        temp = temp_at(when, w["alt"], a.tmin, a.tmax, a.ref_alt)
        light = light_at(when, a.lat, a.lon)
        out_aid.append({"km": round(w["km"], 1), "name": w["name"], "alt": round(w["alt"]),
                        "lat": round(w["lat"], 5), "lon": round(w["lon"], 5),
                        "eta": when.strftime("%a %H:%M"), "cumul": hm(t),
                        "temp": round(temp, 1), "light": light, "gear": gear_for(temp, light)})

    # Fenêtres de nuit : on regroupe les tronçons consécutifs de même lumière.
    windows, cur = [], None
    for s in out_segs:
        if cur and cur["light"] == s["light"]:
            cur["km1"], cur["end"] = s["km1"], s["clock"]
            cur["tmin"] = min(cur["tmin"], s["temp"]); cur["tmax"] = max(cur["tmax"], s["temp"])
        else:
            cur = {"light": s["light"], "km0": s["km0"], "km1": s["km1"],
                   "start": s["clock"], "end": s["clock"], "tmin": s["temp"], "tmax": s["temp"]}
            windows.append(cur)
    for w in windows:
        w["km0"], w["km1"] = round(w["km0"], 1), round(w["km1"], 1)

    # Températures par tranche horaire.
    hours = []
    for s in out_segs:
        key = s["clock"][:2] + "h"
        if not hours or hours[-1]["h"] != key:
            hours.append({"h": key, "km0": s["km0"], "km1": s["km1"], "tmin": s["temp"],
                          "tmax": s["temp"], "alt": s["alt"], "light": s["light"]})
        else:
            o = hours[-1]
            o["km1"] = s["km1"]; o["tmin"] = min(o["tmin"], s["temp"]); o["tmax"] = max(o["tmax"], s["temp"])
    for o in hours:
        o["km0"], o["km1"] = round(o["km0"], 1), round(o["km1"], 1)

    plan = {
        "runner": a.runner, "race": a.race,
        "date": start.strftime("%A %d %B %Y"), "start": start.strftime("%H:%M"),
        "goal": hm(target), "projected": hms(total),
        "distanceKm": round(total_km, 1), "elevationM": round(total_up),
        "revised": datetime.now().strftime("%d/%m/%Y"),
        "model": {"walkThr": a.walk_thr, "walkDecay": a.walk_decay, "fatigue": a.fatigue,
                  "walkKm": round(walk_km, 1), "runKm": round(total_km - walk_km, 1)},
        "conditions": {"temp": f"{a.tmin:.0f} à {a.tmax:.0f} °C en vallée",
                       "weather": f"Gradient d'altitude appliqué : −{LAPSE*1000:.1f} °C par 1000 m"},
        "learnedFrom": ({"runners": learned["runners"], "years": learned["years"],
                         "matched": learned["matched"], "total": learned["total"],
                         "points": learned["points"]} if learned else None),
        "profile": [[round(s["km1"], 1), s["alt"]] for s in out_segs],
        "segments": out_segs, "sections": to_sections(out_segs, out_aid),
        "aid": out_aid, "windows": windows, "hours": hours,
    }
    if a.reference:
        plan["reference"] = json.loads(Path(a.reference).read_text(encoding="utf-8"))

    Path(a.out).write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    night = sum(w["km1"] - w["km0"] for w in windows if w["light"] == "nuit")
    print(f"  Marche : {walk_km:.1f} km  ·  Course : {total_km-walk_km:.1f} km")
    secs = plan["sections"]
    print(f"  Nuit   : {night:.1f} km sur {len(out_segs)} tronçons  ·  {len(out_aid)} ravitaillements")
    print(f"  Regroupé en {len(secs)} portions de terrain homogène "
          f"(la plus longue : {max(x['dist'] for x in secs):.1f} km)")
    print(f"  Écrit  : {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
