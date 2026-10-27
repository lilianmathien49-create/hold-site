#!/usr/bin/env python3
"""Recale la fatigue du modèle sur la façon dont les finishers courent vraiment.

    python3 tools/calibrate.py --gpx data/utmb.gpx --target 28:00 \
        --reference tools/utmb-reference.json --fatigue-measured 1.66

L'entraînement mesure la durabilité sur des sorties de quelques heures. Une course
de 28 h fatigue autrement : le chiffre mesuré sous-estime ce qui se passe à la
vingtième heure. Les finishers, eux, l'ont vécue.

On cherche donc la perte de rendement horaire qui reproduit leur façon de répartir
l'effort : à chaque fraction de distance, la même part de temps dépensée qu'eux.
La valeur mesurée à l'entraînement sert de point de départ et de garde-fou.
"""
from __future__ import annotations

import argparse, json
from pathlib import Path

from build_plan import read_gpx, to_segments, cost_run, cost_walk


def race_curve(segs, scale, fatigue, thr0, decay, floor, run_flat, walk_flat, grid):
    """Déroule la course et renvoie, pour chaque fraction de distance,
    la fraction du temps total déjà dépensée."""
    t, xs, ys = 0.0, [], []
    for s in segs:
        hours = t / 3600
        thr = max(floor, thr0 - decay * hours)
        walking = s["slope"] >= thr
        g = s["slope"] / 100
        base = walk_flat if walking else run_flat
        cost = cost_walk(g) if walking else cost_run(g)
        flat = cost_walk(0) if walking else cost_run(0)
        fade = max(0.45, 1 - fatigue / 100 * max(0, hours - 1))
        v = max(1.0, min(22.0, base * (flat / cost) * fade * scale))
        t += s["dist"] / 1000 / v * 3600
        xs.append(s["km1"])
        ys.append(t)
    total_km, total_t = xs[-1], ys[-1]
    fx = [x / total_km for x in xs]
    fy = [y / total_t for y in ys]
    out = []
    for g in grid:
        if g <= fx[0]:
            out.append(fy[0]); continue
        for i in range(1, len(fx)):
            if g <= fx[i]:
                x0, x1, y0, y1 = fx[i-1], fx[i], fy[i-1], fy[i]
                out.append(y0 + (y1 - y0) * (g - x0) / (x1 - x0) if x1 > x0 else y1)
                break
        else:
            out.append(fy[-1])
    return out, total_t


def fit_scale(segs, fatigue, target, p):
    """Cale l'allure de base pour que la course tombe sur l'objectif."""
    lo, hi = 0.25, 4.0
    for _ in range(45):
        mid = (lo + hi) / 2
        _, t = race_curve(segs, mid, fatigue, p["thr0"], p["decay"], p["floor"],
                          p["run_flat"], p["walk_flat"], [1.0])
        if t > target: lo = mid
        else: hi = mid
    return (lo + hi) / 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gpx", required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--fatigue-measured", type=float, required=True,
                    help="durabilité mesurée à l'entraînement, en %%/h")
    ap.add_argument("--thr0", type=float, default=8.62)
    ap.add_argument("--decay", type=float, default=0.742)
    ap.add_argument("--floor", type=float, default=4.0)
    ap.add_argument("--run-flat", type=float, default=11.0)
    ap.add_argument("--walk-flat", type=float, default=5.6)
    ap.add_argument("--out")
    a = ap.parse_args()

    hh, mm = a.target.split(":")
    target = int(hh) * 3600 + int(mm) * 60
    ref = json.loads(Path(a.reference).read_text(encoding="utf-8"))
    pts = [p for p in ref["points"] if 0 < p["dist"] < 1]
    grid = [p["dist"] for p in pts]
    theirs = [p["median"] for p in pts]

    p = {"thr0": a.thr0, "decay": a.decay, "floor": a.floor,
         "run_flat": a.run_flat, "walk_flat": a.walk_flat}
    segs = to_segments(read_gpx(Path(a.gpx))[0])

    def gap(fatigue):
        scale = fit_scale(segs, fatigue, target, p)
        mine, _ = race_curve(segs, scale, fatigue, p["thr0"], p["decay"], p["floor"],
                             p["run_flat"], p["walk_flat"], grid)
        return sum(abs(m - t) for m, t in zip(mine, theirs)) / len(grid) * 100, mine

    print(f"  Référence : {ref['runners']} finishers autour de {ref['target']}"
          f" ({ref['years'][0]}–{ref['years'][-1]})\n")
    print("   fatigue   écart moyen à leur courbe")
    best = None
    for f in [a.fatigue_measured + i * 0.25 for i in range(0, 25)]:
        g, _ = gap(f)
        mark = ""
        if best is None or g < best[1]:
            best, mark = (f, g), "  ←"
        if abs(f * 4 - round(f * 4)) < 1e-9 and (f - a.fatigue_measured) % 1 < 0.26:
            print(f"   {f:5.2f} %/h   {g:5.2f} pt{mark}")
    # Affinage autour du minimum.
    lo, hi = max(a.fatigue_measured, best[0] - 0.25), best[0] + 0.25
    for _ in range(18):
        m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
        if gap(m1)[0] < gap(m2)[0]: hi = m2
        else: lo = m1
    fatigue = round((lo + hi) / 2, 3)
    g, mine = gap(fatigue)
    g0, mine0 = gap(a.fatigue_measured)

    print(f"\n  Mesurée à l'entraînement : {a.fatigue_measured} %/h  →  écart {g0:.2f} pt")
    print(f"  Recalée sur la course    : {fatigue} %/h  →  écart {g:.2f} pt")
    print(f"  Soit {fatigue / a.fatigue_measured:.1f} fois plus de fatigue qu'en sortie longue.\n")
    print("   distance   recalé    les finishers")
    for i, d in enumerate(grid):
        if abs(d * 100 - round(d * 100 / 10) * 10) < 1e-9:
            print(f"    {d*100:5.0f} %    {mine[i]*100:6.1f} %   {theirs[i]*100:6.1f} %")

    if a.out:
        Path(a.out).write_text(json.dumps({
            "fatigueMeasured": a.fatigue_measured, "fatigueRace": fatigue,
            "gapBefore": round(g0, 3), "gapAfter": round(g, 3),
            "ratio": round(fatigue / a.fatigue_measured, 2),
            "runners": ref["runners"], "years": ref["years"],
            "grid": grid, "theirs": theirs, "mine": [round(x, 4) for x in mine],
            "mineBefore": [round(x, 4) for x in mine0],
        }, ensure_ascii=False), encoding="utf-8")
        print(f"\n  Écrit : {a.out}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
