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
from datetime import datetime
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


def _num(v):
    """Les vraies montres laissent des trous : cardio absent, température non
    mesurée. On les marque comme manquants plutôt que de refuser le fichier."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


TYPES: dict = {}        # type de séance -> indice, rempli à la lecture


def load(path: Path):
    by = defaultdict(list)
    day0 = None
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                d = datetime.strptime(r["date"], "%Y-%m-%d").toordinal()
            except (ValueError, KeyError):
                d = 0
            if day0 is None and d:
                day0 = d
            by[int(r["session"])].append((
                _num(r["slope"]), _num(r["t_s"]) / 3600.0,
                1.0 if r["mode"] == "marche" else 0.0,
                _num(r["kmh"]), _num(r["hr"]), _num(r["temp"]),
                float(d - (day0 or d)),
                float(datetime.fromordinal(d).month) if d else 0.0,
                float(TYPES.setdefault(r.get("type") or "?", len(TYPES))),
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


def flat_speed(g):
    """Vitesse ramenée au plat, pour comparer des efforts comparables."""
    gr = g[:, 0] / 100
    cr = np.clip(155.4*gr**5 - 30.4*gr**4 - 43.3*gr**3 + 46.3*gr**2 + 19.5*gr + 3.6, 1.5, None)
    cw = np.clip(280.5*gr**5 - 58.7*gr**4 - 76.8*gr**3 + 51.9*gr**2 + 19.6*gr + 2.5, 1.2, None)
    return np.where(g[:, 2] > 0.5, g[:, 3] * cw / 2.5, g[:, 3] * cr / 3.6)


def hr_response(groups, n_knots=5):
    """FC = lisse(pente) + lisse(heures) + lisse(vitesse) + marche, à l'intérieur
    des séances ; puis température entre séances.

    La vitesse est indispensable : sans elle, la « dérive » mesure la structure
    de la séance — échauffement, corps de séance, retour au calme — et non la
    montée du cœur à effort constant. Sur de vraies données elle sort négative."""
    allrows = np.vstack(groups)
    kn_s = quantile_knots(allrows[:, 0], n_knots)
    kn_h = quantile_knots(allrows[:, 1], n_knots)
    kn_v = quantile_knots(flat_speed(allrows), n_knots)
    # Les constantes des deux bases disparaissent au centrage : on les retire.
    bs = lambda g: spline_basis(g[:, 0], kn_s)[:, 1:]
    bh = lambda g: spline_basis(g[:, 1], kn_h)[:, 1:]
    bv = lambda g: spline_basis(flat_speed(g), kn_v)[:, 1:]
    # Le nombre de colonnes se déduit de la base, jamais du nombre de nœuds :
    # une spline naturelle en rend K-1 une fois la constante retirée.
    ns = bs(allrows[:1]).shape[1]
    nh = bh(allrows[:1]).shape[1]
    nv = bv(allrows[:1]).shape[1]
    cols = [lambda g, j=j: bs(g)[:, j] for j in range(ns)] \
         + [lambda g, j=j: bh(g)[:, j] for j in range(nh)] \
         + [lambda g, j=j: bv(g)[:, j] for j in range(nv)] \
         + [lambda g: g[:, 2]]
    y, X = within(groups, lambda g: g[:, 4], cols)
    coef = ridge_fit(X, y)

    def slope_effect(v):
        return float((spline_basis(np.array([v]), kn_s)[:, 1:] @ coef[:ns])[0])
    def hour_effect(v):
        return float((spline_basis(np.array([v]), kn_h)[:, 1:] @ coef[ns:ns + nh])[0])

    # Entre séances : ce qui reste de la FC moyenne une fois le reste retiré.
    mt, my, mdays = [], [], []
    for g in groups:
        if len(g) < 60:
            continue
        ok = np.isfinite(g[:, 4]) & np.isfinite(g[:, 5])
        if ok.sum() < 60:          # séance sans cardio ou sans température
            continue
        gg = g[ok]
        pred = (bs(gg) @ coef[:ns] + bh(gg) @ coef[ns:ns + nh]
                + bv(gg) @ coef[ns + nh:ns + nh + nv] + gg[:, 2] * coef[-1])
        my.append(gg[:, 4].mean() - pred.mean())
        mt.append(gg[:, 5].mean())
        mdays.append(gg[0, 6] if g.shape[1] > 6 else 0.0)
    mt, my = np.array(mt), np.array(my)
    # Une seule observation par séance : ~230 points. Une spline y trouverait
    # de la courbure là où il n'y a que du bruit, surtout aux extrêmes. On reste
    # donc sur une droite au-dessus de 15 °C, où l'effet est attendu.
    # Quatre ans séparent la première séance de la dernière, et la forme change.
    # Sans contrôler le temps long, l'effet « chaleur » capte cette dérive :
    # sur ces données il sortait négatif, c'est-à-dire que la chaleur aurait
    # ralenti le cœur.
    warm = np.clip(mt - 15.0, 0, None)
    trend = (np.array(mdays) - np.mean(mdays)) / 365.0 if mdays else np.zeros(len(mt))
    Bt = np.column_stack([np.ones(len(mt)), warm, trend])
    ct = ridge_fit(Bt, my, 1e-3)
    temp_effect = lambda v: float(ct[0] + ct[1] * max(0.0, v - 15.0))

    base = temp_effect(15.0)
    # La dérive se mesure là où il y a des données, pas sur une plage choisie
    # d'avance : sur un coureur dont les séances font une heure, demander
    # l'écart entre la première et la quatrième revient à extrapoler.
    hs = allrows[:, 1]
    lo_h = float(np.quantile(hs, 0.20))
    hi_h = float(np.quantile(hs, 0.95))
    span = max(0.25, hi_h - lo_h)
    drift_obs = (hour_effect(hi_h) - hour_effect(lo_h)) / span
    return {
        "slope": [[s, round(slope_effect(s), 2)] for s in range(-20, 26, 2)],
        "hours": [[h, round(hour_effect(h), 2)] for h in (0, .5, 1, 2, 3, 4, 6, 8)],
        "temp": [[t, round(temp_effect(t) - base, 2)] for t in range(0, 36, 2)],
        "walkOffset": round(float(coef[-1]), 2),
        "driftPerHour": round(drift_obs, 3),
        "driftRange": [round(lo_h, 2), round(hi_h, 2)],
        "driftPerHour1to4": round((hour_effect(4) - hour_effect(1)) / 3, 3),
        "heatPerDegAt25": round((temp_effect(26) - temp_effect(24)) / 2, 3),
        "heatPerDegAt18": round((temp_effect(19) - temp_effect(17)) / 2, 3),
    }


def trim(out):
    """Efface du profil tout ce que les données ne soutiennent pas.

    Un profil qui transporte un chiffre faux est un piège : il ne provoque
    aucune erreur, il s'affiche. Mieux vaut un champ vide, que le tableau de
    bord sait traiter, qu'une courbe plausible et fausse.
    """
    cov, hr = out["coverage"], out.get("hr") or {}
    mx = cov.get("maxHours") or 0

    # Une courbe ne vaut que sur l'intervalle observé : au-delà, c'est du dessin.
    if hr.get("hours"):
        hr["hours"] = [[h, v] for h, v in hr["hours"] if h <= mx + 0.1]
        hr["hoursRange"] = [0, round(mx, 1)]

    # La dérive entre 1 h et 4 h demande des séances de 4 h.
    if mx < 4 and hr.get("driftPerHour1to4") is not None:
        hr["driftPerHour1to4"] = None
        hr["driftWhy1to4"] = f"séance la plus longue : {mx:.1f} h"

    # Le surcoût cardiaque par degré n'a été estimé qu'entre séances, sans
    # tenir le mois : la température y est confondue avec la saison, donc
    # avec la forme. Seule l'estimation à mois égal (heatSpeed) est gardée.
    hs = out.get("heatSpeed")
    if not (hs and hs.get("sure")):
        hr["temp"] = None
        hr["heatPerDegAt18"] = hr["heatPerDegAt25"] = None
        hr["heatWhy"] = ("effet non séparable de la saison à l'échelle de la FC"
                         if hs else "pas assez de séances avec température")
    return out


def heat_cost(groups):
    """Ce que la chaleur coûte en VITESSE, à mois égal.

    Trois pièges, et il a fallu les trois pour arriver ici.

    1. Mesurer le surcoût CARDIAQUE à vitesse égale suppose qu'on tient son
       allure quand il fait chaud. En réalité on ralentit : la fréquence
       cardiaque ne bouge pas et c'est la vitesse qui tombe. C'est donc la
       vitesse qu'il faut regarder, et c'est aussi ce qu'un plan demande.

    2. Mais il ne faut surtout PAS corriger de la fréquence cardiaque au
       passage. La chaleur fait monter le cœur ET baisser la vitesse : tenir
       la FC constante revient à conditionner sur un médiateur. Vérifié contre
       un simulateur dont l'effet vrai valait -0,60 % par degré : avec ce
       contrôle l'estimation donnait -0,59 % puis, une fois la spécification
       corrigée, +1,01 % — signe inversé. Sans le contrôle : -0,30 %.

    3. La température suit les saisons, et la forme aussi. On compare donc des
       séances du même mois, où seule la météo du jour varie, et on tient le
       type et la durée de séance, qui sont eux-mêmes saisonniers.

    Reste une limite assumée : sur ce même simulateur la méthode ne retrouve
    que la moitié de l'effet vrai. Le chiffre rendu est donc un PLANCHER, et
    `floor` le dit.
    """
    xs, ys, ms, ts, ds = [], [], [], [], []
    for g in groups:
        ok = np.isfinite(g[:, 5]) & np.isfinite(g[:, 3])
        if ok.sum() < 60:
            continue
        gg = g[ok]
        v = flat_speed(gg)
        m = np.isfinite(v) & (v > 3) & (v < 25)
        if m.sum() < 60:
            continue
        ys.append(float(np.median(v[m])))
        xs.append(float(np.median(gg[m][:, 5])))
        ms.append(int(gg[0, 7]) if g.shape[1] > 7 else 0)
        ts.append(int(gg[0, 8]) if g.shape[1] > 8 else 0)
        ds.append(float(gg[-1, 1]))
    if len(xs) < 40:
        return None
    xs, ys, ms, ds = map(np.array, (xs, ys, ms, ds))
    ts = np.array(ts)

    # Un mois ne sert que s'il contient plusieurs séances ET de l'écart de
    # température : sinon son effet fixe absorbe entièrement la chaleur.
    keep = np.zeros(len(xs), bool)
    for mm in np.unique(ms):
        sel = ms == mm
        if sel.sum() >= 4 and xs[sel].std() >= 1.5:
            keep |= sel
    if keep.sum() < 40:
        return None
    xs, ys, ms, ds, ts = xs[keep], ys[keep], ms[keep], ds[keep], ts[keep]

    months, kinds = np.unique(ms), np.unique(ts)
    def design(x, mm, tt, dd):
        cols = [(mm == v).astype(float) for v in months]
        cols.append(np.clip(x - 15, 0, None))          # l'effet n'existe qu'au chaud
        cols += [(tt == v).astype(float) for v in kinds[1:]]
        cols.append(dd - ds.mean())
        return np.column_stack(cols)

    i = len(months)
    X = design(xs, ms, ts, ds)
    per = float(ridge_fit(X, ys, 1e-3)[i])
    base = float(np.mean(ys))

    rng = np.random.default_rng(7)
    boot = []
    for _ in range(400):
        k = rng.integers(0, len(ys), len(ys))
        if len(np.unique(ms[k])) < 2:
            continue
        try:
            boot.append(float(ridge_fit(X[k], ys[k], 1e-3)[i]))
        except np.linalg.LinAlgError:
            continue
    lo, hi = (np.quantile(boot, [0.1, 0.9]) if len(boot) > 50 else (np.nan, np.nan))
    chaud = xs > 15
    return {"perDegree": round(per, 4),
            "pctPerDegree": round(per / base * 100, 3),
            "ci80": [round(float(lo), 4), round(float(hi), 4)],
            "sure": bool(np.isfinite(lo) and lo < 0 and hi < 0),
            "floor": True,          # la méthode sous-estime : voir la docstring
            "above15": int(chaud.sum()),
            "sessions": int(len(ys)), "months": int(len(months)),
            "withinMonthSpread": round(float(np.mean([xs[ms == m].std() for m in months])), 1),
            "tempSpread": [round(float(np.quantile(xs, .05)), 0), round(float(np.quantile(xs, .95)), 0)]}


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
    # Vitesses de référence sur le plat, séparées par mode : c'est ce que le plan
    # utilisait jusqu'ici comme réglage par défaut, sans l'avoir jamais mesuré.
    allk = np.vstack(keep)
    fresh = allk[allk[:, 0] <= 1.0]                      # première heure, avant fatigue
    runf = fresh[fresh[:, 2] < 0.5][:, 1]
    walkf = fresh[fresh[:, 2] > 0.5][:, 1]
    eff = lambda v: float((spline_basis(np.array([v]), kn)[:, 1:] @ coef_h)[0])
    e0 = eff(0.5)
    return {
        "base": round(base, 2),
        "runFlat": round(float(np.median(runf)), 2) if len(runf) > 200 else None,
        "walkFlat": round(float(np.median(walkf)), 2) if len(walkf) > 200 else None,
        "curve": [[h, round((eff(h) - e0) / base * 100, 2)] for h in (0.5, 1, 2, 3, 4, 5, 6, 7, 8)],
        "lossPerHour1to3": round(-(eff(3) - eff(1)) / 2 / base * 100, 3),
        "lossPerHour5to8": round(-(eff(8) - eff(5)) / 3 / base * 100, 3),
    }




BLOCK_S = 15.0        # durée d'un bloc, en secondes (posée par import_watch.py)


def climbs(groups):
    """Les montées présentes dans l'entraînement, en mètres de dénivelé d'affilée.

    On intègre la pente sur la distance réellement parcourue, et on coupe la
    montée dès que la pente retombe sous 2 % : ce qui compte n'est pas le D+
    total d'une séance mais la plus longue ascension continue, puisque c'est la
    durée d'une montée qui décide si on la court ou si on la marche.
    """
    tot, best = [], []
    for g in groups:
        slope, kmh = g[:, 0], g[:, 3]
        dist = np.where(np.isfinite(kmh), kmh, 0.0) * 1000 / 3600 * BLOCK_S
        up = np.clip(slope, 0, None) / 100 * dist
        tot.append(float(up.sum()))
        run = top = 0.0
        for sl, u in zip(slope, up):
            if sl > 2:
                run += u
            else:
                top = max(top, run)
                run = 0.0
        best.append(max(top, run))
    tot, best = np.array(tot), np.array(best)
    return {
        "sessions": int(len(tot)),
        "medianGain": int(np.median(tot)), "maxGain": int(tot.max()),
        "medianContinuous": int(np.median(best)),
        "q90Continuous": int(np.quantile(best, 0.9)),
        "maxContinuous": int(best.max()),
        "above300": int((best >= 300).sum()), "above800": int((best >= 800).sum()),
    }


def coverage(groups):
    """Ce que les données permettent réellement d'estimer.

    Un modèle qui extrapole produit des chiffres d'allure sérieuse et sans
    aucun fondement : un seuil de marche négatif, une chaleur qui ralentit le
    cœur. Mieux vaut refuser que répondre n'importe quoi."""
    allr = np.vstack(groups)
    n = len(allr)
    hours = allr[:, 1]
    slope = allr[:, 0]
    walk = allr[:, 2]
    temp = allr[:, 5]

    # Zone de bascule : il faut des blocs des deux côtés, et des deux issues.
    zone = (slope > 4) & (slope < 25)
    walked = walk[zone].sum() if zone.sum() else 0
    thr_ok = zone.sum() >= 2000 and 0.02 < (walked / max(1, zone.sum())) < 0.98

    # Chute du seuil : elle se lit dans la durée, donc il faut de la durée.
    late = (hours > 2).sum()
    decay_h = float(np.quantile(hours, 0.999))
    decay_ok = late >= 1500 and decay_h >= 3

    # Durabilité : mêmes exigences, la fatigue ne se lit pas sur une heure.
    dur_ok = late >= 1500

    # Chaleur : il faut de l'écart de température, ET pas seulement entre deux
    # années différentes — sinon on mesure un changement de forme, pas la chaleur.
    tok = np.isfinite(temp)
    heat_ok = False
    heat_why = "aucune température dans les fichiers"
    if tok.sum() > 3000:
        tv = temp[tok]
        spread = float(np.quantile(tv, 0.9) - np.quantile(tv, 0.1))
        heat_ok = spread >= 8
        heat_why = "" if heat_ok else f"seulement {spread:.0f} °C d'écart entre les séances mesurées"

    # Les montées du coureur, mesurées : c'est ce qui décide si son seuil est
    # transférable. Un seuil appris sur des bosses de quinze mètres ne dit rien
    # d'un col de mille — sur une rampe courte on court ce qu'on marcherait sur
    # une longue, et la différence n'est pas de la fatigue, c'est la montée.
    cl = climbs(groups)

    return {
        "blocks": int(n), "hours": round(n * 15 / 3600, 1),
        "climbs": cl,
        "zoneBlocks": int(zone.sum()), "walkedInZone": round(float(walked / max(1, zone.sum())) * 100, 1),
        "blocksBeyond2h": int(late), "maxHours": round(decay_h, 1),
        "tempBlocks": int(tok.sum()),
        "threshold": {"ok": bool(thr_ok), "why": "" if thr_ok else
                      f"seulement {int(zone.sum())} blocs entre 4 et 25 % de pente",
                      # Mesurable n'est pas transférable : on dit jusqu'où le
                      # chiffre vaut, pour que le planificateur puisse refuser.
                      "validUpToClimbM": cl["q90Continuous"]},
        "decay": {"ok": bool(decay_ok), "why": "" if decay_ok else
                  f"seulement {late} blocs au-delà de deux heures de course"},
        "durability": {"ok": bool(dur_ok), "why": "" if dur_ok else
                       f"séances trop courtes : {late} blocs au-delà de deux heures"},
        "heat": {"ok": bool(heat_ok), "why": heat_why},
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

    cov = coverage(groups)
    w = walk_threshold(rows, a.knots)
    hc = heat_cost(groups) if cov["heat"]["ok"] else None
    hr = hr_response(groups, a.knots)
    du = durability(groups, a.knots)

    # Ce qui n'est pas mesurable est retiré, pas affiché avec un avertissement :
    # un chiffre affiché finit toujours par être utilisé.
    if not cov["threshold"]["ok"]:
        w = {k: None for k in w}
    if not cov["decay"]["ok"]:
        w["decay4h"] = None
        w["curve"] = [c for c in (w.get("curve") or []) if c[0] <= 2]
    if not cov["durability"]["ok"]:
        du = {**du, "lossPerHour1to3": None, "lossPerHour5to8": None, "curve": None}
    if not cov["heat"]["ok"]:
        hr = {**hr, "heatPerDegAt18": None, "heatPerDegAt25": None, "temp": None}

    out = {"sessions": len(groups), "blocks": len(rows), "knots": a.knots,
           "coverage": cov, "walk": w, "hr": hr, "speed": du, "heatSpeed": hc}
    trim(out)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("  CE QUE CES DONNÉES PERMETTENT DE MESURER")
    for k, lab in (("threshold", "seuil de marche"), ("decay", "chute du seuil"),
                   ("durability", "durabilité"), ("heat", "coût de la chaleur")):
        c = cov[k]
        print(f"    {lab:22s} {'OUI' if c['ok'] else 'non'}"
              + (f"   — {c['why']}" if not c["ok"] else ""))
    print()
    if w.get("curve"):
        print("  SEUIL DE MARCHE, heure par heure")
        for h, t in w["curve"]:
            print(f"    après {h} h   {t:5.2f} %")
    r = hr.get("driftRange") or [0, 0]
    print(f"\n  DÉRIVE CARDIAQUE   {hr['driftPerHour']:5.2f} bpm par heure"
          f"   (mesurée entre {r[0]:.1f} h et {r[1]:.1f} h, là où il y a des données)")
    if hc:
        if hc["sure"]:
            print(f"  COÛT DE LA CHALEUR  au moins {abs(hc['perDegree']):.3f} km/h par degré "
                  f"au-dessus de 15 °C  ({abs(hc['pctPerDegree']):.2f} % de vitesse)")
            print(f"                      intervalle {hc['ci80'][0]:+.3f} à {hc['ci80'][1]:+.3f}")
        else:
            # Éprouvée sur un coureur dont la sensibilité vraie valait -0,60 %
            # par degré, la méthode répond aussi « non distinguable de zéro ».
            # Une absence de résultat n'est donc pas une absence d'effet.
            print(f"  COÛT DE LA CHALEUR  non mesurable — l'effet estimé "
                  f"({hc['perDegree']:+.3f} km/h/°C) n'est pas distinguable de zéro,"
                  f" ce qui ne veut pas dire qu'il est nul")
            print(f"                      intervalle {hc['ci80'][0]:+.3f} à {hc['ci80'][1]:+.3f} km/h/°C")
        print(f"                      à mois égal · {hc['sessions']} séances dont "
              f"{hc['above15']} au-dessus de 15 °C · "
              f"{hc['months']} mois · écart intra-mois {hc['withinMonthSpread']:.1f} °C · "
              f"{hc['tempSpread'][0]:.0f}-{hc['tempSpread'][1]:.0f} °C")
    if du.get("lossPerHour1to3") is not None:
        print(f"\n  DURABILITÉ, perte de vitesse (% par heure)")
        print(f"    entre 1 et 3 h   {du['lossPerHour1to3']:5.2f}")
        print(f"    entre 5 et 8 h   {du['lossPerHour5to8']:5.2f}")

    print(f"\n  Couverture : {cov['hours']} h · {cov['zoneBlocks']} blocs dans la zone de bascule "
          f"({cov['walkedInZone']} % marchés) · {cov['blocksBeyond2h']} blocs au-delà de 2 h")

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
