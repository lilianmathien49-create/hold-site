#!/usr/bin/env python3
"""Fabrique une année d'entraînement pour un coureur qui prépare 28 h à l'UTMB.

    python3 tools/simulate_athlete.py --out tools/athlete-blocks.csv

Le coureur a des paramètres physiologiques cachés : la pente à laquelle il passe
à la marche, la vitesse à laquelle ce seuil s'effondre quand il fatigue, sa dérive
cardiaque, sa sensibilité à la chaleur, sa durabilité. Le script déroule 52 semaines
de séances variées — hiver et été, courtes et longues, plat et montagne — et écrit
des blocs de 15 secondes, exactement ce qu'une montre enregistre.

Ces paramètres cachés ne sont écrits nulle part dans le CSV : c'est le travail de
fit_athlete.py de les retrouver. Si l'ajustement tombe juste, c'est que la méthode
qu'on appliquera aux vraies données tient debout.
"""
from __future__ import annotations

import argparse, csv, json, math, random
from datetime import date, timedelta
from pathlib import Path

BLOCK_S = 15

# --- Ce que le coureur est vraiment. Caché du CSV, retrouvé par l'ajustement.
TRUE = {
    "walk_thr0": 8.8,     # pente (%) où il marche une fois sur deux, frais
    "walk_decay": 0.78,   # points de pente perdus par heure de course
    "walk_k": 0.27,       # raideur de la bascule marche/course
    "run_flat": 11.4,     # km/h sur le plat à allure endurance, frais
    "walk_flat": 5.6,
    "durability": 1.15,   # % de vitesse perdue par heure au-delà de la première
    "hr_flat": 141.0,     # FC en courant sur le plat, frais, à 15 °C
    "hr_drift": 2.3,      # bpm de dérive par heure à effort constant
    "hr_heat": 0.95,      # bpm par °C au-dessus de 15
    "hr_slope": 0.85,     # bpm par point de pente
    "hr_walk": -14.0,     # la marche coûte moins cher au cœur
}

# type, durée (min), caractère du terrain, part dans la semaine
SESSIONS = [
    ("footing",   (45, 80),   "plat",     0.34),
    ("tempo",     (50, 75),   "plat",     0.10),
    ("cotes",     (60, 100),  "raide",    0.14),
    ("longue",    (120, 240), "vallonne", 0.26),
    ("montagne",  (240, 540), "montagne", 0.16),
]


def terrain(kind: str, blocks: int, rng: random.Random) -> list[float]:
    """Suite de pentes plausible : on alterne des montées et des descentes
    de longueur réaliste plutôt que de tirer chaque bloc indépendamment."""
    cfg = {"plat": (1.5, 40), "vallonne": (5.5, 60), "raide": (11.0, 25),
           "montagne": (13.0, 90)}[kind]
    amp, run_len = cfg
    out, i = [], 0
    while i < blocks:
        n = max(4, int(rng.gauss(run_len, run_len * 0.4)))
        target = rng.gauss(0, amp)
        if kind in ("raide", "montagne") and rng.random() < 0.5:
            target = abs(target) * rng.choice([1, -1]) * 1.4
        for _ in range(min(n, blocks - i)):
            out.append(max(-35, min(35, target + rng.gauss(0, 1.8))))
            i += 1
    return out


def season_temp(d: date, rng: random.Random) -> float:
    """Température de la séance : cycle annuel plus l'aléa du jour."""
    day = d.timetuple().tm_yday
    # Maximum vers le 19 juillet (jour 200), minimum en janvier.
    base = 12.5 + 9.5 * math.cos(2 * math.pi * (day - 200) / 365)
    return round(base + rng.gauss(0, 3.0), 1)


def run_session(sid: int, d: date, kind: str, minutes: int, shape: str,
                rng: random.Random, w) -> int:
    blocks = int(minutes * 60 / BLOCK_S)
    slopes = terrain(shape, blocks, rng)
    temp = season_temp(d, rng)
    # L'intensité du jour : un tempo se court plus vite qu'un footing.
    effort = {"footing": 0.88, "tempo": 1.07, "cotes": 0.97, "longue": 0.92, "montagne": 0.86}[kind]
    freshness = rng.gauss(1.0, 0.035)          # forme du jour
    written = 0
    for i, slope in enumerate(slopes):
        hours = i * BLOCK_S / 3600
        thr = max(3.5, TRUE["walk_thr0"] - TRUE["walk_decay"] * hours)
        p_walk = 1 / (1 + math.exp(-TRUE["walk_k"] * (slope - thr)))
        walking = rng.random() < p_walk
        grade = slope / 100
        # Coût énergétique de la pente (Minetti 2002) : la vitesse suit l'inverse du coût.
        if walking:
            cost = max(1.2, 280.5*grade**5 - 58.7*grade**4 - 76.8*grade**3 + 51.9*grade**2 + 19.6*grade + 2.5)
            v = TRUE["walk_flat"] * (2.5 / cost)
        else:
            cost = max(1.5, 155.4*grade**5 - 30.4*grade**4 - 43.3*grade**3 + 46.3*grade**2 + 19.5*grade + 3.6)
            v = TRUE["run_flat"] * (3.6 / cost)
        fade = max(0.6, 1 - TRUE["durability"] / 100 * max(0, hours - 1))
        heat_cost = 1 - max(0.0, temp - 15) * 0.006
        v = max(1.2, v * effort * freshness * fade * heat_cost * rng.gauss(1, 0.045))

        hr = (TRUE["hr_flat"]
              + TRUE["hr_slope"] * slope
              + TRUE["hr_drift"] * hours
              + TRUE["hr_heat"] * max(0.0, temp - 15)
              + (TRUE["hr_walk"] if walking else 0.0)
              + (effort - 0.9) * 55
              + rng.gauss(0, 3.2))
        hr = max(80, min(190, hr))

        w.writerow([sid, d.isoformat(), kind, i * BLOCK_S, round(slope, 2),
                    "marche" if walking else "course", round(v, 2), round(hr), temp])
        written += 1
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--weeks", type=int, default=52)
    ap.add_argument("--seed", type=int, default=20)
    ap.add_argument("--truth", help="écrit les paramètres cachés, pour vérifier l'ajustement")
    a = ap.parse_args()

    rng = random.Random(a.seed)
    start = date(2026, 9, 1)
    kinds = [k for k, _, _, _ in SESSIONS]
    weights = [w for _, _, _, w in SESSIONS]

    total_blocks = sessions = 0
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["session", "date", "type", "t_s", "slope", "mode", "kmh", "hr", "temp"])
        for week in range(a.weeks):
            # Volume variable : trois semaines de charge, une de récupération.
            n = 3 if week % 4 == 3 else rng.choice([4, 5, 5, 6])
            for j in range(n):
                kind = rng.choices(kinds, weights)[0]
                lo, hi = next(d for k, d, _, _ in SESSIONS if k == kind)
                shape = next(s for k, _, s, _ in SESSIONS if k == kind)
                minutes = int(rng.uniform(lo, hi))
                d = start + timedelta(days=week * 7 + j)
                sessions += 1
                total_blocks += run_session(sessions, d, kind, minutes, shape, rng, w)

    print(f"  {sessions} séances · {total_blocks:,} blocs de {BLOCK_S} s"
          f" · {total_blocks*BLOCK_S/3600:.0f} h de course".replace(",", " "))
    print(f"  Écrit : {a.out}")
    if a.truth:
        Path(a.truth).write_text(json.dumps(TRUE, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Paramètres cachés : {a.truth}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
