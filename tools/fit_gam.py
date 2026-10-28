#!/usr/bin/env python3
"""Modèle additif de l'athlète : les réponses ne sont pas des droites.

    python3 tools/fit_gam.py tools/athlete-blocks.csv --out tools/athlete-gam.json \
        --truth tools/athlete-truth.json

Les ajustements linéaires supposent qu'un degré de plus coûte autant à 16 °C
qu'à 30 °C, et qu'une heure de course coûte autant la première que la
vingtième. C'est faux, et ça se voit dans les résidus.

On remplace donc chaque effet par une somme de fonctions lisses : des splines
cubiques naturelles, qui épousent la courbe sans la forcer. L'ajustement reste
un moindre carré — pas de boîte noire, chaque terme s'affiche et se lit.

Deux précautions valables pour tout ce fichier :

  · Les effets internes à une séance (pente, durée écoulée) s'estiment à
    l'intérieur des séances. Une sortie longue est lente parce qu'elle est
    longue, pas parce que le coureur s'épuise ; les comparer entre elles
    confondrait les deux.

  · L'effet de la température ne peut s'estimer qu'entre séances, puisqu'elle
    ne bouge pas pendant une sortie.
"""
from __future__ import annotations

import argparse, csv, json, math, random
from collections import defaultdict
from pathlib import Path

import numpy as np


# --- Base de splines cubiques naturelles -------------------------------------
def spline_basis(x: np.ndarray, knots: np.ndarray) -> np.ndarray:
    """Base de régression pour une spline cubique naturelle.
    Naturelle veut dire linéaire au-delà des nœuds extrêmes : sans ça, une
    spline part à l'infini dès qu'on sort de la plage observée."""
    k = np.asarray(knots, dtype=float)
    K = len(k)
    d = lambda j: (np.clip(x - k[j], 0, None) ** 3 - np.clip(x - k[-1], 0, None) ** 3) / (k[-1] - k[j])
    cols = [np.ones_like(x), x]
    for j in range(K - 2):
        cols.append(d(j) - d(K - 2))
    return np.column_stack(cols)


def quantile_knots(x: np.ndarray, n: int) -> np.ndarray:
    """Nœuds posés aux quantiles : ils se concentrent là où il y a des données,
    pas là où l'axe est joli."""
    qs = np.linspace(0, 1, n)
    k = np.unique(np.quantile(x[np.isfinite(x)], qs))
    return k if len(k) >= 4 else np.linspace(np.min(x), np.max(x), 4)


def ridge_fit(X: np.ndarray, y: np.ndarray, lam: float = 1e-6) -> np.ndarray:
    """Moindres carrés avec une régularisation minime, pour rester stable quand
    deux colonnes de la base deviennent presque identiques."""
    A = X.T @ X + lam * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ y)


def within(groups, ycol, xcols):
    """Écarts à la moyenne de chaque séance : la comparaison d'une sortie
    avec elle-même."""
    Y, X = [], []
    for g in groups:
        if len(g) < 60:
            continue
        y = ycol(g)
        x = np.column_stack([c(g) for c in xcols])
        ok = np.isfinite(y) & np.all(np.isfinite(x), axis=1)
        if ok.sum() < 60:
            continue
        y, x = y[ok], x[ok]
        Y.append(y - y.mean())
        X.append(x - x.mean(axis=0))
    return np.concatenate(Y), np.vstack(X)


def load(path: Path):
    by = defaultdict(list)
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            by[int(r["session"])].append((
                float(r["slope"]), float(r["t_s"]) / 3600.0,
                1.0 if r["mode"] == "marche" else 0.0,
                float(r["kmh"]), float(r["hr"]), float(r["temp"]),
            ))
    return [np.array(v) for v in by.values()]


# --- Les trois réponses -------------------------------------------------------
def walk_threshold(rows: np.ndarray, n_knots=5):
    """Probabilité de marcher = logistique d'une spline en pente, dont le
    décalage dépend du temps écoulé. On en déduit le seuil heure par heure."""
    slope, hours, walk = rows[:, 0], rows[:, 1], rows[:, 2]
    m = (slope > -8) & (slope < 28)
    s, h, w = slope[m], hours[m], walk[m]
    kn = quantile_knots(s, n_knots)
    B = spline_basis(s, kn)
    X = np.column_stack([B, h, (B[:, 1:2] * h[:, None])])  # pente × heures
    b = np.zeros(X.shape[1])
    for _ in range(45):
        p = 1 / (1 + np.exp(-np.clip(X @ b, -30, 30)))
        wgt = np.clip(p * (1 - p), 1e-6, None)
        H = (X * wgt[:, None]).T @ X + 1e-4 * np.eye(X.shape[1])
        step = np.linalg.solve(H, X.T @ (w - p) - 1e-4 * b)
        b += step
        if np.max(np.abs(step)) < 1e-10:
            break

    def thr_at(hr):
        """Pente où la probabilité de marcher atteint 50 %, à hr heures."""
        grid = np.linspace(-5, 26, 620)
        Bg = spline_basis(grid, kn)
        Xg = np.column_stack([Bg, np.full(len(grid), hr), Bg[:, 1:2] * hr])
        p = 1 / (1 + np.exp(-np.clip(Xg @ b, -30, 30)))
        i = np.argmin(np.abs(p - 0.5))
        return float(grid[i])

    hrs = [0, 1, 2, 3, 4, 6, 8]
    return {"curve": [[h_, round(thr_at(h_), 2)] for h_ in hrs],
            "thr0": round(thr_at(0), 2),
            "decay4h": round((thr_at(0) - thr_at(4)) / 4, 3)}


def hr_response(groups, n_knots=5):
    """FC = lisse(pente) + lisse(heures) + marche, à l'intérieur des séances ;
    puis lisse(température) entre séances."""
    allrows = np.vstack(groups)
    kn_s = quantile_knots(allrows[:, 0], n_knots)
    kn_h = quantile_knots(allrows[:, 1], n_knots)
    # Les constantes des deux bases disparaissent au centrage : on les retire.
    bs = lambda g: spline_basis(g[:, 0], kn_s)[:, 1:]
    bh = lambda g: spline_basis(g[:, 1], kn_h)[:, 1:]
    # Le nombre de colonnes se déduit de la base, jamais du nombre de nœuds :
    # une spline naturelle en rend K-1 une fois la constante retirée.
    ns = bs(allrows[:1]).shape[1]
    nh = bh(allrows[:1]).shape[1]
    cols = [lambda g, j=j: bs(g)[:, j] for j in range(ns)] \
         + [lambda g, j=j: bh(g)[:, j] for j in range(nh)] \
         + [lambda g: g[:, 2]]
    y, X = within(groups, lambda g: g[:, 4], cols)
    coef = ridge_fit(X, y)

    def slope_effect(v):
        return float((spline_basis(np.array([v]), kn_s)[:, 1:] @ coef[:ns])[0])
    def hour_effect(v):
        return float((spline_basis(np.array([v]), kn_h)[:, 1:] @ coef[ns:ns + nh])[0])

    # Entre séances : ce qui reste de la FC moyenne une fois le reste retiré.
    mt, my = [], []
    for g in groups:
        if len(g) < 60:
            continue
        pred = (bs(g) @ coef[:ns] + bh(g) @ coef[ns:ns + nh] + g[:, 2] * coef[-1])
        my.append(g[:, 4].mean() - pred.mean())
        mt.append(g[:, 5].mean())
    mt, my = np.array(mt), np.array(my)
    # Une seule observation par séance : ~230 points. Une spline y trouverait
    # de la courbure là où il n'y a que du bruit, surtout aux extrêmes. On reste
    # donc sur une droite au-dessus de 15 °C, où l'effet est attendu.
    warm = np.clip(mt - 15.0, 0, None)
    Bt = np.column_stack([np.ones(len(mt)), warm])
    ct = ridge_fit(Bt, my, 1e-3)
    temp_effect = lambda v: float(ct[0] + ct[1] * max(0.0, v - 15.0))

    base = temp_effect(15.0)
    return {
        "slope": [[s, round(slope_effect(s), 2)] for s in range(-20, 26, 2)],
        "hours": [[h, round(hour_effect(h), 2)] for h in (0, .5, 1, 2, 3, 4, 6, 8)],
        "temp": [[t, round(temp_effect(t) - base, 2)] for t in range(0, 36, 2)],
        "walkOffset": round(float(coef[-1]), 2),
        "driftPerHour1to4": round((hour_effect(4) - hour_effect(1)) / 3, 3),
        "heatPerDegAt25": round((temp_effect(26) - temp_effect(24)) / 2, 3),
        "heatPerDegAt18": round((temp_effect(19) - temp_effect(17)) / 2, 3),
    }


def durability(groups, n_knots=5):
    """Vitesse ramenée au plat, en fonction des heures écoulées. La perte n'est
    pas constante : elle s'accélère."""
    keep = []
    for g in groups:
        sl, walk, kmh = g[:, 0], g[:, 2], g[:, 3]
        gr = sl / 100
        cr = np.clip(155.4*gr**5 - 30.4*gr**4 - 43.3*gr**3 + 46.3*gr**2 + 19.5*gr + 3.6, 1.5, None)
        cw = np.clip(280.5*gr**5 - 58.7*gr**4 - 76.8*gr**3 + 51.9*gr**2 + 19.6*gr + 2.5, 1.2, None)
        fe = np.where(walk > 0.5, kmh * cw / 2.5, kmh * cr / 3.6)
        ok = np.isfinite(fe) & (fe > 1) & (fe < 25)
        if ok.sum() >= 60:
            # La marche est gardée en colonne : sa part grimpe avec les heures
            # (18 % la première, 38 % la cinquième) et sa vitesse équivalente est
            # bien plus basse. Sans ce contrôle, ce glissement de composition se
            # lirait comme de la fatigue.
            keep.append(np.column_stack([g[ok][:, 1], fe[ok], g[ok][:, 2]]))
    allh = np.concatenate([k[:, 0] for k in keep])
    kn = quantile_knots(allh, n_knots)
    bh = lambda g: spline_basis(g[:, 0], kn)[:, 1:]
    nb = bh(keep[0][:1]).shape[1]
    cols = [lambda g, j=j: bh(g)[:, j] for j in range(nb)] + [lambda g: g[:, 2]]
    y, X = within(keep, lambda g: g[:, 1], cols)
    coef = ridge_fit(X, y)
    coef_h = coef[:nb]
    base = float(np.mean([k[:, 1].mean() for k in keep]))
    eff = lambda v: float((spline_basis(np.array([v]), kn)[:, 1:] @ coef_h)[0])
    e0 = eff(0.5)
    return {
        "base": round(base, 2),
        "curve": [[h, round((eff(h) - e0) / base * 100, 2)] for h in (0.5, 1, 2, 3, 4, 5, 6, 7, 8)],
        "lossPerHour1to3": round(-(eff(3) - eff(1)) / 2 / base * 100, 3),
        "lossPerHour5to8": round(-(eff(8) - eff(5)) / 3 / base * 100, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--out", required=True)
    ap.add_argument("--truth")
    ap.add_argument("--knots", type=int, default=5)
    a = ap.parse_args()

    groups = load(Path(a.source))
    rows = np.vstack(groups)
    print(f"  {len(groups)} séances · {len(rows):,} blocs".replace(",", " "))
    print(f"  Splines à {a.knots} nœuds, posés aux quantiles\n")

    w = walk_threshold(rows, a.knots)
    hr = hr_response(groups, a.knots)
    du = durability(groups, a.knots)
    out = {"sessions": len(groups), "blocks": len(rows), "knots": a.knots,
           "walk": w, "hr": hr, "speed": du}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("  SEUIL DE MARCHE, heure par heure")
    for h, t in w["curve"]:
        print(f"    après {h} h   {t:5.2f} %")
    print(f"\n  RÉPONSE CARDIAQUE à la chaleur (bpm par degré)")
    print(f"    vers 18 °C   {hr['heatPerDegAt18']:5.2f}")
    print(f"    vers 25 °C   {hr['heatPerDegAt25']:5.2f}   "
          f"{'— le coût s augmente avec la chaleur' if hr['heatPerDegAt25'] > hr['heatPerDegAt18'] * 1.2 else ''}")
    print(f"\n  DURABILITÉ, perte de vitesse (% par heure)")
    print(f"    entre 1 et 3 h   {du['lossPerHour1to3']:5.2f}")
    print(f"    entre 5 et 8 h   {du['lossPerHour5to8']:5.2f}")
    if du["lossPerHour5to8"] > du["lossPerHour1to3"] * 1.3:
        print("    → la perte s'accélère : un modèle linéaire la sous-estime en fin de course")

    if a.truth:
        t = json.loads(Path(a.truth).read_text(encoding="utf-8"))
        print("\n  Contrôle sur les paramètres réellement utilisés pour fabriquer les données :")
        print(f"    seuil à 0 h        réel {t['walk_thr0']:6.2f}   retrouvé {w['thr0']:6.2f}")
        print(f"    chute par heure    réel {t['walk_decay']:6.2f}   retrouvé {w['decay4h']:6.2f}")
        print(f"    dérive cardiaque   réel {t['hr_drift']:6.2f}   retrouvé {hr['driftPerHour1to4']:6.2f}")
        print(f"    chaleur bpm/°C     réel {t['hr_heat']:6.2f}   retrouvé {hr['heatPerDegAt25']:6.2f}")
        print(f"    durabilité %/h     réel {t['durability']:6.2f}   retrouvé {du['lossPerHour1to3']:6.2f}")

    print(f"\n  Écrit : {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
