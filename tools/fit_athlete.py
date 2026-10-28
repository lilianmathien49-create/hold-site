#!/usr/bin/env python3
"""Retrouve le profil d'un coureur à partir de ses blocs de montre.

    python3 tools/fit_athlete.py tools/athlete-blocks.csv --out tools/athlete-fit.json \
        --truth tools/athlete-truth.json

Trois ajustements, chacun sur la question qu'il sert :

  1. Seuil de marche — régression logistique de marche/course sur la pente et le
     temps écoulé. Donne la pente de bascule et sa décroissance horaire.
  2. Réponse cardiaque — régression linéaire de la FC sur la pente, la durée
     écoulée et la température. Donne la dérive et le coût de la chaleur.
  3. Durabilité — perte de vitesse par heure, à pente et effort comparables.

Les intervalles viennent d'un bootstrap **par séance** et non par bloc : deux blocs
voisins de la même sortie ne sont pas deux mesures indépendantes, et l'ignorer
donnerait des intervalles ridiculement étroits.
"""
from __future__ import annotations

import argparse, csv, json, math, random
from collections import defaultdict
from pathlib import Path

import numpy as np


def _num(v):
    """Les vraies montres laissent des trous : cardio absent, température non
    mesurée. On les marque comme manquants plutôt que de refuser le fichier."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def load(path: Path):
    by_session = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by_session[int(r["session"])].append((
                _num(r["slope"]), _num(r["t_s"]) / 3600.0,
                1.0 if r["mode"] == "marche" else 0.0,
                _num(r["kmh"]), _num(r["hr"]), _num(r["temp"]),
            ))
    return by_session


def logistic_fit(X: np.ndarray, y: np.ndarray, iters: int = 40) -> np.ndarray | None:
    """Régression logistique par Newton-Raphson pondéré (IRLS), avec une petite
    régularisation pour rester stable quand une variable est presque constante."""
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        w = np.clip(p * (1 - p), 1e-6, None)
        grad = X.T @ (y - p) - 1e-4 * b
        H = (X * w[:, None]).T @ X + 1e-4 * np.eye(X.shape[1])
        try:
            step = np.linalg.solve(H, grad)
        except np.linalg.LinAlgError:
            return None
        b += step
        if np.max(np.abs(step)) < 1e-9:
            break
    return b


def fit_walk(rows: np.ndarray):
    """P(marche) = logistique(b0 + b1·pente + b2·heures + b3·pente×heures).
    Le seuil est la pente qui annule le logit, et il bouge avec les heures."""
    slope, hours, walk = rows[:, 0], rows[:, 1], rows[:, 2]
    # On se limite aux pentes où la décision se joue vraiment.
    m = (slope > -6) & (slope < 26)
    X = np.column_stack([np.ones(m.sum()), slope[m], hours[m], slope[m] * hours[m]])
    b = logistic_fit(X, walk[m])
    if b is None:
        return None
    def thr_at(h):           # pente où le logit s'annule, à h heures de course
        num, den = -(b[0] + b[2] * h), (b[1] + b[3] * h)
        return num / den if abs(den) > 1e-9 else float("nan")
    t0, t4 = thr_at(0.0), thr_at(4.0)
    return {"thr0": t0, "decay": (t0 - t4) / 4.0, "k": b[1]}


def flat_equivalent(rows: np.ndarray) -> np.ndarray:
    """Vitesse ramenée à ce qu'elle vaudrait sur le plat, via le coût de la pente."""
    slope, _, walk, kmh = rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 3]
    g = slope / 100
    c_run = np.clip(155.4*g**5 - 30.4*g**4 - 43.3*g**3 + 46.3*g**2 + 19.5*g + 3.6, 1.5, None)
    c_walk = np.clip(280.5*g**5 - 58.7*g**4 - 76.8*g**3 + 51.9*g**2 + 19.6*g + 2.5, 1.2, None)
    return np.where(walk > 0.5, kmh * c_walk / 2.5, kmh * c_run / 3.6)


def _within(groups: list[np.ndarray], ycol, xcols):
    """Empile les écarts à la moyenne de chaque séance. Une séance longue est
    courue moins vite parce qu'elle est longue, pas parce que le coureur
    s'épuise : comparer une séance à elle-même supprime ce biais."""
    Y, X = [], []
    for g in groups:
        if len(g) < 40:
            continue
        y = ycol(g)
        x = np.column_stack([c(g) for c in xcols])
        Y.append(y - y.mean())
        X.append(x - x.mean(axis=0))
    return np.concatenate(Y), np.vstack(X)


def fit_hr(by_session):
    """Dérive, pente et marche s'estiment à l'intérieur des séances ; la chaleur
    ne peut s'estimer qu'entre elles, puisqu'elle ne bouge pas pendant une sortie."""
    groups = [np.array(v) for v in by_session.values()]
    y, X = _within(groups, lambda g: g[:, 4], [lambda g: g[:, 0], lambda g: g[:, 1], lambda g: g[:, 2]])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    b_slope, b_drift, b_walk = coef
    resid = 1 - np.sum((y - X @ coef) ** 2) / np.sum(y ** 2)

    # Entre séances : ce qui reste de la FC moyenne une fois les effets internes retirés.
    mt, my = [], []
    for g in groups:
        if len(g) < 40:
            continue
        adj = g[:, 4].mean() - (b_slope * g[:, 0].mean() + b_drift * g[:, 1].mean() + b_walk * g[:, 2].mean())
        my.append(adj)
        mt.append(max(0.0, g[:, 5].mean() - 15))
    B = np.column_stack([np.ones(len(mt)), np.array(mt)])
    inter, b_heat = np.linalg.lstsq(B, np.array(my), rcond=None)[0]
    return {"hr_flat": inter, "hr_slope": b_slope, "hr_drift": b_drift,
            "hr_heat": b_heat, "hr_walk": b_walk, "r2": resid}


def fit_durability(by_session):
    """Même principe : la perte de vitesse se lit au sein d'une séance,
    le coût de la chaleur se lit d'une séance à l'autre."""
    groups = [np.array(v) for v in by_session.values()]
    keep = []
    for g in groups:
        fe = flat_equivalent(g)
        m = np.isfinite(fe) & (fe > 1) & (fe < 25)
        if m.sum() >= 40:
            # Colonne de marche : sans elle, la montée de la part marchée au fil
            # des heures se confond avec la fatigue.
            keep.append(np.column_stack([g[m][:, 1], fe[m], g[m][:, 5], g[m][:, 2]]))
    y, X = _within(keep, lambda g: g[:, 1], [lambda g: g[:, 0], lambda g: g[:, 3]])
    slope_h = np.linalg.lstsq(X, y, rcond=None)[0][0]
    base = float(np.mean([g[:, 1].mean() for g in keep]))

    mt = np.array([max(0.0, g[:, 2].mean() - 15) for g in keep])
    mv = np.array([g[:, 1].mean() - slope_h * g[:, 0].mean() for g in keep])
    B = np.column_stack([np.ones(len(mt)), mt])
    inter, b_heat = np.linalg.lstsq(B, mv, rcond=None)[0]
    return {"run_flat": inter, "durability": -slope_h / base * 100,
            "heat_speed": -b_heat / base * 100}


def bootstrap(by_session, n: int, seed: int):
    """Ré-échantillonne des séances entières, pas des blocs."""
    ids = list(by_session)
    rng = random.Random(seed)
    out = defaultdict(list)
    for _ in range(n):
        pick = [rng.choice(ids) for _ in ids]
        rows = np.array([r for s in pick for r in by_session[s]])
        sub = {i: by_session[s] for i, s in enumerate(pick)}
        w, h, d = fit_walk(rows), fit_hr(sub), fit_durability(sub)
        if w:
            out["thr0"].append(w["thr0"]); out["decay"].append(w["decay"])
        for k, v in h.items(): out[k].append(v)
        for k, v in d.items(): out[k].append(v)
    return out


def ci(vals):
    v = sorted(vals)
    pick = lambda q: v[max(0, min(len(v) - 1, round(q * (len(v) - 1))))]
    return [round(pick(0.025), 3), round(pick(0.975), 3)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--out", required=True)
    ap.add_argument("--truth", help="paramètres réels, pour contrôler l'ajustement")
    ap.add_argument("--boot", type=int, default=60)
    ap.add_argument("--seed", type=int, default=5)
    a = ap.parse_args()

    by_session = load(Path(a.source))
    rows = np.array([r for s in by_session.values() for r in s])
    print(f"  {len(by_session)} séances · {len(rows):,} blocs".replace(",", " "))

    walk, hr, dur = fit_walk(rows), fit_hr(by_session), fit_durability(by_session)
    print(f"  Bootstrap par séance ({a.boot} tirages)…")
    boot = bootstrap(by_session, a.boot, a.seed)

    fit = {
        "blocks": len(rows), "sessions": len(by_session),
        "walk": {"thr0": round(walk["thr0"], 2), "thr0CI": ci(boot["thr0"]),
                 "decay": round(walk["decay"], 3), "decayCI": ci(boot["decay"]),
                 "k": round(walk["k"], 3)},
        "hr": {k: round(v, 3) for k, v in hr.items()} |
              {"driftCI": ci(boot["hr_drift"]), "heatCI": ci(boot["hr_heat"])},
        "speed": {k: round(v, 3) for k, v in dur.items()} |
                 {"durabilityCI": ci(boot["durability"])},
    }
    Path(a.out).write_text(json.dumps(fit, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n  Seuil de marche      {fit['walk']['thr0']:.2f} %  (IC95 {fit['walk']['thr0CI'][0]}–{fit['walk']['thr0CI'][1]})")
    print(f"  Décroissance         {fit['walk']['decay']:.3f} pt/h  (IC95 {fit['walk']['decayCI'][0]}–{fit['walk']['decayCI'][1]})")
    print(f"  Dérive cardiaque     {fit['hr']['hr_drift']:.2f} bpm/h  (IC95 {fit['hr']['driftCI'][0]}–{fit['hr']['driftCI'][1]})")
    print(f"  Coût de la chaleur   {fit['hr']['hr_heat']:.2f} bpm/°C  (IC95 {fit['hr']['heatCI'][0]}–{fit['hr']['heatCI'][1]})")
    print(f"  Durabilité           {fit['speed']['durability']:.2f} %/h  (IC95 {fit['speed']['durabilityCI'][0]}–{fit['speed']['durabilityCI'][1]})")
    print(f"  Qualité du modèle FC  R² = {fit['hr']['r2']:.3f}")

    if a.truth:
        t = json.loads(Path(a.truth).read_text(encoding="utf-8"))
        print("\n  Contrôle — valeur réelle vs retrouvée :")
        pairs = [("seuil de marche", t["walk_thr0"], fit["walk"]["thr0"], fit["walk"]["thr0CI"]),
                 ("décroissance", t["walk_decay"], fit["walk"]["decay"], fit["walk"]["decayCI"]),
                 ("dérive cardiaque", t["hr_drift"], fit["hr"]["hr_drift"], fit["hr"]["driftCI"]),
                 ("chaleur (bpm/°C)", t["hr_heat"], fit["hr"]["hr_heat"], fit["hr"]["heatCI"]),
                 ("durabilité", t["durability"], fit["speed"]["durability"], fit["speed"]["durabilityCI"])]
        for name, real, got, iv in pairs:
            inside = iv[0] <= real <= iv[1]
            print(f"    {name:20s} réel {real:7.3f}   retrouvé {got:7.3f}   "
                  f"IC95 [{iv[0]}, {iv[1]}]  {'✓' if inside else '✗ hors intervalle'}")

    print(f"\n  Écrit : {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
