#!/usr/bin/env python3
"""Où les finishers perdent du temps, et à cause de quoi.

    python3 tools/analyze_legs.py tools/utmb-28h-large.json --out tools/utmb-legs.json

Un tronçon long et raide prend du temps : ça n'apprend rien. La question est de
savoir où ils en perdent **au-delà** de ce que le terrain explique.

On ajuste donc le temps de chaque inter-ravitaillement sur sa distance, sa montée
et sa descente, puis on regarde ce qui reste. Ce résidu se lit ensuite selon :
la distance déjà parcourue (la fatigue), l'heure au mur (la nuit), et la chaleur
de l'édition. Les temps d'arrêt sont comptés à part, ravitaillement par
ravitaillement.
"""
from __future__ import annotations

import argparse, json, math, re, unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import numpy as np

NIGHT_FROM, NIGHT_TO = 21.0, 6.5      # heures locales, fin août à Chamonix
CACHE = Path(__file__).resolve().parent / ".cache-utmb"


def canon(name: str) -> str:
    """« La Giète », « La Giete », « La Giète sortie » désignent le même endroit :
    sans ce nettoyage, un même lieu se retrouve éclaté sur plusieurs lignes."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(sortie|entree|arrivee|depart|ravito)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def field_times(years):
    """Chronos de TOUS les finishers, depuis le cache des classements.
    Sélectionner les coureurs sur leur temps d'arrivée fausse toute comparaison
    entre éditions : pour la météo, il faut le peloton entier."""
    out = {}
    for y in years:
        f = CACHE / f"{y}-classement.xml"
        if not f.is_file():
            continue
        try:
            cl = ET.fromstring(f.read_text(encoding="utf-8")).find("classement")
        except ET.ParseError:
            continue
        if cl is None:
            continue
        ts = []
        for c in cl:
            try:
                h, m, s = (c.get("tps") or "").split(":")
                ts.append(int(h) * 3600 + int(m) * 60 + int(s))
            except ValueError:
                continue
        if len(ts) > 100:
            out[y] = ts
    return out


def to_legs(runners):
    """Transforme les points de passage en tronçons entre deux points."""
    legs = []
    for r in runners:
        sp = sorted((s for s in r["splits"] if s.get("km") is not None), key=lambda s: s["km"])
        for a, b in zip(sp, sp[1:]):
            dist = b["km"] - a["km"]
            climb = b["climb"] - a["climb"]
            if dist <= 0.3 or climb < -50:
                continue
            dt = b["elapsed"] - a["elapsed"]
            if dt <= 60 or dt > 8 * 3600:
                continue
            drop = max(0.0, (climb - (b["alt"] - a["alt"])))   # descente du tronçon
            clock = None
            if b.get("clock"):
                try:
                    hh, mm, _ = b["clock"].split(":")
                    clock = int(hh) + int(mm) / 60
                except ValueError:
                    clock = None
            legs.append({
                "year": r["year"], "bib": r["bib"], "finish": r["time"],
                "name": b["name"], "from_km": a["km"], "to_km": b["km"],
                "dist": dist, "climb": climb, "drop": drop,
                "dt": dt, "start_elapsed": a["elapsed"],
                "frac": a["km"] / sp[-1]["km"], "clock": clock,
                "stop": b.get("stop"),
            })
    return legs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--weather", help="météo par édition (JSON produit par fetch_weather.py)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = json.loads(Path(a.source).read_text(encoding="utf-8"))
    legs = to_legs(data["runners"])
    if len(legs) < 200:
        print("Pas assez de tronçons exploitables.")
        return 1
    weather = json.loads(Path(a.weather).read_text(encoding="utf-8")) if a.weather else {}

    # Modèle de terrain : le temps d'un tronçon suit sa distance, sa montée et sa
    # descente. On travaille en logarithme pour que l'écart se lise en pourcentage.
    y = np.log(np.array([l["dt"] for l in legs]))
    fr = np.array([l["frac"] for l in legs])
    terrain = [
        np.ones(len(legs)),
        np.log(np.array([l["dist"] for l in legs])),
        np.array([l["climb"] / max(1, l["dist"]) for l in legs]),   # m de D+ par km
        np.array([l["drop"] / max(1, l["dist"]) for l in legs]),
    ]
    X = np.column_stack(terrain)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef                 # >0 : plus lent que ce que le terrain prévoit
    r2 = 1 - np.sum(resid ** 2) / np.sum((y - y.mean()) ** 2)

    # Un second modèle ajoute la position dans la course. La différence entre les
    # deux sépare « ce tronçon est tard » de « ce tronçon est dur en lui-même ».
    Xp = np.column_stack(terrain + [fr, fr ** 2])
    coefp, *_ = np.linalg.lstsq(Xp, y, rcond=None)
    residp = y - Xp @ coefp
    r2p = 1 - np.sum(residp ** 2) / np.sum((y - y.mean()) ** 2)
    for i, l in enumerate(legs):
        l["resid"] = float(resid[i])
        l["residNet"] = float(residp[i])   # net de la fatigue de position

    # 1. Où, sur le parcours, perd-on au-delà du terrain ?
    by_name = defaultdict(list)
    for l in legs:
        by_name[canon(l["name"])].append(l)
    spots = []
    for key, ls in by_name.items():
        # Un point de contrôle présent sur une seule édition produit des écarts
        # énormes et ininterprétables : on exige qu'il revienne d'année en année.
        if len(ls) < 40 or len({x["year"] for x in ls}) < 3:
            continue
        label = max((x["name"] for x in ls), key=lambda n: sum(1 for x in ls if x["name"] == n))
        spots.append({"name": label, "km": round(float(np.median([x["to_km"] for x in ls])), 1),
                      "n": len(ls),
                      "lost": round((math.exp(float(np.median([x["resid"] for x in ls]))) - 1) * 100, 1),
                      "lostNet": round((math.exp(float(np.median([x["residNet"] for x in ls]))) - 1) * 100, 1)})
    spots.sort(key=lambda s: -s["lost"])

    # 2. La fatigue : le résidu grandit-il avec la distance déjà faite ?
    fr = np.array([l["frac"] for l in legs])
    bins = []
    for lo in np.arange(0, 1.0, 0.1):
        m = (fr >= lo) & (fr < lo + 0.1)
        if m.sum() > 30:
            bins.append({"from": round(float(lo), 1),
                         "lost": round((math.exp(float(np.median(resid[m]))) - 1) * 100, 1),
                         "n": int(m.sum())})

    # 3. La nuit, à terrain et fatigue comparables.
    night = np.array([1.0 if (l["clock"] is not None and
                              (l["clock"] >= NIGHT_FROM or l["clock"] <= NIGHT_TO)) else 0.0
                      for l in legs])
    known = np.array([l["clock"] is not None for l in legs])
    night_eff = None
    if known.sum() > 200 and 0.05 < night[known].mean() < 0.95:
        Z = np.column_stack([np.ones(int(known.sum())), night[known], fr[known]])
        c, *_ = np.linalg.lstsq(Z, resid[known], rcond=None)
        night_eff = round((math.exp(float(c[1])) - 1) * 100, 1)

    # 4. Météo : sur le peloton entier, jamais sur notre échantillon.
    #    Nos coureurs sont choisis pour finir autour de 28 h ; une année dure,
    #    il faut être meilleur pour y arriver. Mesurer la météo sur eux ferait
    #    croire que la chaleur fait courir plus vite.
    heat = rain_eff = None
    rows = []
    field = field_times(sorted({l["year"] for l in legs}))
    if weather and len(field) >= 6:
        xs_t, xs_r, ys = [], [], []
        for yr, ts in sorted(field.items()):
            w = weather.get(str(yr)) or weather.get(yr)
            if not w:
                continue
            med = float(np.median(ts))
            xs_t.append(w["tmax"]); xs_r.append(w.get("rain") or 0.0); ys.append(med)
            rows.append({"year": yr, "tmax": w["tmax"], "rain": w.get("rain"),
                         "finishers": len(ts), "medianFinish": int(med),
                         "finishRate": None})
        if len(ys) >= 6:
            Z = np.column_stack([np.ones(len(ys)), np.array(xs_t), np.array(xs_r)])
            c, *_ = np.linalg.lstsq(Z, np.array(ys), rcond=None)
            base = float(np.mean(ys))
            heat = round(float(c[1]) / base * 100, 2)        # % du chrono par °C
            rain_eff = round(float(c[2]) / base * 100, 3)    # % du chrono par mm
        rows.sort(key=lambda r: r["tmax"])

    # 5. Temps d'arrêt par ravitaillement.
    stops = defaultdict(list)
    for l in legs:
        if l.get("stop") is not None and 0 < l["stop"] < 3600:
            stops[l["name"]].append(l["stop"])
    stop_rows = sorted(
        ({"name": n, "n": len(v), "median": int(np.median(v)), "p90": int(np.percentile(v, 90))}
         for n, v in stops.items() if len(v) >= 25),
        key=lambda s: -s["median"])

    out = {"runners": len({(l["year"], l["bib"]) for l in legs}), "legs": len(legs),
           "years": sorted({l["year"] for l in legs}),
           "terrainR2": round(float(r2), 3), "terrainPosR2": round(float(r2p), 3),
           "spots": spots[:12], "easiest": spots[-6:][::-1],
           "fatigue": bins, "nightEffect": night_eff,
           "heatPctPerDegree": heat, "rainPctPerMm": rain_eff, "byYear": rows,
           "stops": stop_rows[:14]}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    print(f"  {out['runners']} coureurs · {len(legs)} tronçons · éditions {out['years'][0]}–{out['years'][-1]}")
    print(f"  Le terrain seul explique {r2*100:.0f} % du temps d'un tronçon ;")
    print(f"  en ajoutant la position dans la course, {r2p*100:.0f} %.\n")
    print("  Là où ils perdent le plus, au-delà du terrain :")
    print("    (brut = fatigue incluse · net = une fois la position dans la course retirée)")
    for s in spots[:9]:
        print(f"    km {s['km']:6.1f}  {s['name'][:28]:30s} brut {s['lost']:+6.1f} %   net {s['lostNet']:+6.1f} %   ({s['n']})")
    print("\n  Perte selon la part de course déjà faite :")
    for b in bins:
        bar = "█" * max(0, round(b["lost"] / 2))
        print(f"    {b['from']*100:3.0f}–{(b['from']+0.1)*100:3.0f} %   {b['lost']:+6.1f} %  {bar}")
    if night_eff is not None:
        print(f"\n  Effet de la nuit, à terrain et fatigue égaux : {night_eff:+.1f} %")
    if heat is not None:
        print(f"\n  Sur le peloton entier ({sum(r['finishers'] for r in rows)} finishers) :")
        print(f"    chaleur : {heat:+.2f} % de chrono par °C de maximale")
        print(f"    pluie   : {rain_eff:+.3f} % de chrono par mm")
        print("\n   édition   T max   pluie   finishers   chrono médian")
        for r in rows:
            m=r['medianFinish']
            print(f"    {r['year']}     {r['tmax']:5.1f}  {r['rain']:5.1f}mm   {r['finishers']:5d}      {m//3600:2d}h{m%3600//60:02d}")
    if stop_rows:
        tot = sum(s["median"] for s in stop_rows)
        print(f"\n  Arrêts les plus longs (médiane) — total sur les points listés : {tot//60} min")
        for s in stop_rows[:8]:
            print(f"    {s['name'][:30]:32s} {s['median']//60:3d} min   (90 % : {s['p90']//60} min)")
    print(f"\n  Écrit : {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
