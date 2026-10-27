#!/usr/bin/env python3
"""Tire une courbe de référence des finishers proches d'un objectif.

    python3 tools/analyze_utmb.py tools/utmb-28h.json --out tools/utmb-reference.json

Le parcours bouge d'une édition à l'autre : les ravitaillements changent de nom,
de place et le kilométrage total varie. On ne compare donc pas des points de
contrôle entre eux, mais des **fractions** : à 30 % de la distance, quelle part
de son temps total un finisher a-t-il déjà dépensée ?

Une course parfaitement régulière donnerait 30 % du temps à 30 % de la distance.
L'écart à cette diagonale dit comment la course se distribue réellement.
"""
from __future__ import annotations

import argparse, json, statistics as st
from pathlib import Path

GRID = [i / 20 for i in range(21)]          # tous les 5 % de la distance


def interp(xs: list[float], ys: list[float], x: float) -> float | None:
    """Interpolation linéaire, sans extrapoler hors des bornes mesurées."""
    if not xs or x < xs[0] or x > xs[-1]:
        return None
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1, y0, y1 = xs[i-1], xs[i], ys[i-1], ys[i]
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = json.loads(Path(a.source).read_text(encoding="utf-8"))
    runners = data["runners"]
    if not runners:
        print("Aucun coureur dans le fichier.")
        return 1

    curves, stops, totals = [], [], []
    for r in runners:
        sp = [s for s in r["splits"] if s["km"] is not None]
        if len(sp) < 6:
            continue
        total_km, total_t = sp[-1]["km"], r["time"]
        if not total_km or not total_t:
            continue
        xs = [s["km"] / total_km for s in sp]
        ys = [s["elapsed"] / total_t for s in sp]
        curve = [interp(xs, ys, g) for g in GRID]
        if any(v is None for v in curve):
            continue
        curves.append(curve)
        totals.append(total_t)
        stopped = sum(s["stop"] for s in sp if s.get("stop"))
        if stopped:
            stops.append(stopped)

    if not curves:
        print("Pas assez de données exploitables.")
        return 1

    def pct(vals, q):
        v = sorted(vals)
        i = max(0, min(len(v) - 1, round(q * (len(v) - 1))))
        return v[i]

    points = []
    for i, g in enumerate(GRID):
        col = [c[i] for c in curves]
        points.append({
            "dist": round(g, 3),
            "p25": round(pct(col, 0.25), 4),
            "median": round(st.median(col), 4),
            "p75": round(pct(col, 0.75), 4),
            # Écart à une course parfaitement régulière, en points de pourcentage.
            "drift": round((st.median(col) - g) * 100, 2),
        })

    half = next(p for p in points if abs(p["dist"] - 0.5) < 1e-6)
    years = sorted({r["year"] for r in runners})
    out = {
        "target": data.get("target"),
        "windowMin": data.get("windowMin"),
        "runners": len(curves),
        "years": years,
        "source": data.get("source"),
        "medianTime": int(st.median(totals)),
        "halfTimeShare": half["median"],
        "stopMedianSec": int(st.median(stops)) if stops else None,
        "stopP75Sec": int(pct(stops, 0.75)) if stops else None,
        "points": points,
    }
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")

    print(f"  {len(curves)} coureurs retenus · éditions {years[0]}–{years[-1]}")
    print(f"  Chrono médian : {out['medianTime']//3600}h{out['medianTime']%3600//60:02d}")
    print(f"  À mi-distance, ils ont dépensé {half['median']*100:.1f} % de leur temps "
          f"(une course régulière donnerait 50 %)")
    if out["stopMedianSec"]:
        m = out["stopMedianSec"] // 60
        print(f"  Temps arrêté aux ravitaillements : {m//60}h{m%60:02d} en médiane")
    print("\n  distance   part du temps écoulé (médiane)   écart à la régularité")
    for p in points[::4]:
        bar = "█" * max(0, round(p["drift"] * 2))
        print(f"    {p['dist']*100:5.0f} %        {p['median']*100:6.1f} %"
              f"                {p['drift']:+5.1f} pt {bar}")
    print(f"\n  Écrit : {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
