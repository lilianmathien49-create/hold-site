#!/usr/bin/env python3
"""Monte-Carlo : au lieu d'un chrono, une distribution de chronos.

    python3 tools/simulate.py --gpx data/utmb.gpx --target 28:00 \
        --start "2027-08-27 18:00" --tmin 4 --tmax 24 --runs 10000

Le plan déterministe suppose que tout se passe comme prévu. Ici, chaque course
simulée tire au sort ce qu'on ne connaît qu'approximativement :

  · la vitesse de base du jour (forme, sommeil, stress du départ) ;
  · la vitesse à laquelle le seuil de marche s'effondre ;
  · la perte de rendement horaire, c'est-à-dire la durabilité ;
  · la température réellement rencontrée ;
  · le temps passé arrêté aux ravitaillements.

On en sort une probabilité de tenir l'objectif, et une fourchette honnête.
Les écarts-types par défaut sont prudents : remplace-les par ceux mesurés sur
tes coureurs dès que tu en as assez.
"""
from __future__ import annotations

import argparse, json, math, random, statistics as st
from datetime import datetime, timedelta, timezone
from pathlib import Path

from build_plan import (read_gpx, to_segments, locate_waypoints, speed_ratio,
                        V_MAX_RUN, V_MAX_WALK, V_MIN, hms, hm)


def one_race(segs, p, rng=None) -> tuple[float, list[float]]:
    """Déroule une course. Sans rng, les paramètres valent leur moyenne : c'est la
    course « centrale », celle qui sert à caler l'allure de base sur l'objectif.
    Renvoie le temps total et le temps cumulé à chaque tronçon."""
    if rng is None:
        speed, decay, fatigue, heat, stop = 1.0, p["walk_decay"], p["fatigue"], 0.0, p["stop_total"]
    else:
        speed = rng.gauss(1.0, p["sd_speed"])
        decay = max(0.1, rng.gauss(p["walk_decay"], p["sd_decay"]))
        fatigue = max(0.0, rng.gauss(p["fatigue"], p["sd_fatigue"]))
        heat = rng.gauss(0.0, p["sd_heat"])      # erreur de prévision météo
        stop = max(0.0, rng.gauss(p["stop_total"], p["sd_stop"]))
    t, cum = 0.0, []
    for s in segs:
        hours = t / 3600
        thr = max(p["walk_floor"], p["walk_thr"] - decay * hours)
        walking = s["slope"] >= thr
        grade = s["slope"] / 100
        base = p["walk_flat"] if walking else p["run_flat"]
        fade = max(0.55, 1 - fatigue / 100 * max(0, hours - 1))
        # La chaleur coûte surtout quand on court : ~0,8 % de vitesse par degré au-dessus de 15.
        heat_cost = 1 - max(0.0, heat) * 0.008 * (0.3 if walking else 1.0)
        v = base * speed_ratio(grade, walking) * fade * speed * p["scale"] * heat_cost
        v = max(V_MIN, min(V_MAX_WALK if walking else V_MAX_RUN, v))
        t += s["dist"] / 1000 / v * 3600
        cum.append(t)
    return t + stop, cum


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gpx", required=True)
    ap.add_argument("--target", required=True, help="objectif h:mm")
    ap.add_argument("--runs", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=12)
    ap.add_argument("--keep-within", type=int, default=60,
                    help="ne garder que les courses finissant à +/- N minutes de l'objectif")
    ap.add_argument("--out", help="écrit le résultat en JSON")
    ap.add_argument("--walk-thr", type=float, default=8.8)
    ap.add_argument("--walk-decay", type=float, default=0.775)
    ap.add_argument("--walk-floor", type=float, default=4.0)
    ap.add_argument("--fatigue", type=float, default=1.2)
    ap.add_argument("--run-flat", type=float, default=11.0)
    ap.add_argument("--walk-flat", type=float, default=5.6)
    ap.add_argument("--stop-total", type=float, default=3600, help="temps arrêté total attendu (s)")
    # Incertitudes. Ce sont les hypothèses les plus discutables du modèle.
    ap.add_argument("--sd-speed", type=float, default=0.055, help="dispersion de la forme du jour")
    ap.add_argument("--sd-decay", type=float, default=0.25)
    ap.add_argument("--sd-fatigue", type=float, default=0.45)
    ap.add_argument("--sd-heat", type=float, default=3.0, help="erreur de prévision, en °C")
    ap.add_argument("--sd-stop", type=float, default=900)
    a = ap.parse_args()

    hh, mm = a.target.split(":")
    target = int(hh) * 3600 + int(mm) * 60

    pts, wpts = read_gpx(Path(a.gpx))
    segs = to_segments(pts)
    aid = locate_waypoints(wpts, pts)
    p = {k: getattr(a, k) for k in ("walk_thr", "walk_decay", "walk_floor", "fatigue",
                                    "run_flat", "walk_flat", "stop_total",
                                    "sd_speed", "sd_decay", "sd_fatigue", "sd_heat", "sd_stop")}

    # On cale l'allure de base sur la course centrale, pour que l'objectif soit
    # le scénario médian et non un coup de chance.
    rng = random.Random(a.seed)
    lo, hi = 0.25, 4.0
    for _ in range(50):
        p["scale"] = (lo + hi) / 2
        if one_race(segs, p)[0] > target: lo = p["scale"]
        else: hi = p["scale"]
    p["scale"] = (lo + hi) / 2

    print(f"  {a.runs} courses simulées sur {len(segs)} tronçons…")
    # On ne garde les trajectoires que des courses qui tiennent l'objectif :
    # la fourchette d'un passage doit décrire les scénarios de réussite, pas
    # mélanger ceux qui explosent avec ceux qui volent.
    keep = a.keep_within * 60
    times, curves = [], []
    for _ in range(a.runs):
        t, cum = one_race(segs, p, rng)
        times.append(t)
        if abs(t - target) <= keep and len(curves) < 1500:
            curves.append(cum)

    times.sort()
    def q(x): return times[max(0, min(len(times) - 1, int(x * (len(times) - 1))))]
    under = sum(1 for t in times if t <= target) / len(times)

    # Fourchette de passage à chaque ravitaillement.
    km_marks = [w["km"] for w in aid if w["km"] > 0.3]
    checkpoints = []
    kept = len(curves)
    for w in aid:
        idx = next((i for i, s in enumerate(segs) if s["km1"] >= w["km"]), len(segs) - 1)
        col = sorted(c[idx] for c in curves)
        pick = lambda x: col[max(0, min(len(col) - 1, int(x * (len(col) - 1))))]
        checkpoints.append({"km": round(w["km"], 1), "name": w["name"],
                            "p10": hms(pick(0.1)), "median": hms(pick(0.5)), "p90": hms(pick(0.9))})

    # Distribution des chronos, en tranches de six minutes : de quoi dessiner
    # la forme du risque plutôt que d'en donner trois quantiles.
    BIN = 360
    counts = {}
    for t in times:
        k = int(t // BIN) * BIN
        counts[k] = counts.get(k, 0) + 1
    lo_b, hi_b = min(counts), max(counts)
    histogram = [[k, counts.get(k, 0)] for k in range(lo_b, hi_b + BIN, BIN)]

    # Viser sa médiane, c'est jouer à pile ou face. Voici le chrono à annoncer
    # selon le niveau de certitude qu'on veut avoir en franchissant la ligne.
    confidence = [{"level": int(c * 100), "time": hm(q(c))} for c in (0.5, 0.7, 0.8, 0.9)]

    res = {"target": a.target, "runs": a.runs,
           "probability": round(under, 4),
           "p10": hms(q(0.10)), "p25": hms(q(0.25)), "median": hms(q(0.50)),
           "p75": hms(q(0.75)), "p90": hms(q(0.90)),
           "confidence": confidence,
           "keptWithinMin": a.keep_within, "kept": kept,
           "histogram": histogram, "binSec": BIN,
           "checkpoints": checkpoints,
           "assumptions": {k: v for k, v in p.items() if k.startswith("sd_") or k == "stop_total"}}

    print(f"\n  Probabilité de tenir {a.target} : {under*100:.1f} %")
    print(f"  Fourchette : {hm(q(0.10))} (10 %) · {hm(q(0.5))} (médiane) · {hm(q(0.90))} (90 %)")
    print(f"  Course la plus rapide {hm(times[0])} · la plus lente {hm(times[-1])}")
    print(f"\n  Passages, parmi les {kept} courses qui finissent à ±{a.keep_within} min "
          f"de l'objectif (10 % – médiane – 90 %) :")
    for c in checkpoints[::4]:
        print(f"    km {c['km']:6.1f}  {c['name'][:26]:28s} {c['p10']:>9s}  {c['median']:>9s}  {c['p90']:>9s}")

    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        print(f"\n  Écrit : {a.out}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
