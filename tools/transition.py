#!/usr/bin/env python3
"""La transition course-marche, par régression sur la pente.

    python3 tools/transition.py ~/Documents/HOLD/Gatien

Chaque bloc de 15 s est classé par sa cadence : sous 140 pas par minute, il
marche. On range ensuite les blocs par point de pente et on ajuste la part
marchée par une courbe logistique à quatre paramètres :

    P(pente) = plancher + (plafond − plancher) / (1 + exp(−(pente − milieu) / largeur))

Une logistique ordinaire à deux paramètres a été essayée d'abord. Elle force
la courbe à partir de zéro et à monter jusqu'à un : or au plat, 1 à 4 % des
blocs passent sous 140 sans que personne ne marche (relances, ravitaillements,
foulée mal lue), et dans le raide un traileur court encore un bloc sur quatre.
Contrainte à 0 et 1, la courbe compensait en s'aplatissant, et plaçait la
transition à 19 % de pente, là où il n'y a presque aucune donnée. Le plancher
et le plafond libres règlent les deux défauts : la courbe colle aux
proportions observées à moins de cinq points sur toutes les tranches garnies.

La transition est la pente où la probabilité de marcher franchit 50 %.
Son intervalle vient d'un rééchantillonnage par blocs mobiles de cinq minutes
à l'intérieur de chaque séance : deux blocs de 15 s consécutifs ne sont pas
deux mesures indépendantes, et les tirer un par un donnerait un intervalle
faussement étroit.
"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labo_calc as L

SEUIL = 140.0              # pas par minute : en dessous, il marche
PAS = 1.0                  # largeur des tranches de pente, en points
PENTE_HAUTE = 18.0         # au-delà, moins d'une poignée de blocs par tranche
BLOC_BOOT = 20             # 20 × 15 s = cinq minutes d'un seul tenant
TIRAGES = 200
RAIDE_MIN = 10           # blocs au-dessus de 6 % pour qu'une séance compte comme montagne


def blocs(b):
    return [x for x in L.propres(b) if x.get("cad") and 60 <= x["cad"] <= 220]


def tranches(bl, seuil=SEUIL):
    t = {}
    for x in bl:
        if 0 <= x["pente"] < PENTE_HAUTE:
            k = int(x["pente"] // PAS)
            n, w = t.get(k, (0, 0))
            t[k] = (n + 1, w + (x["cad"] < seuil))
    return [((k + .5) * PAS, n, w) for k, (n, w) in sorted(t.items())]


def courbe(p, x):
    f, c, m, s = p
    return f + (c - f) / (1 + math.exp(-(x - m) / s))


def _nll(p, d):
    f, c, m, s = p
    if not (0 <= f < .4 and f + .1 < c <= 1 and 0 < s < 8 and -5 < m < 40):
        return 1e18
    t = 0.0
    for x, n, w in d:
        q = min(1 - 1e-9, max(1e-9, courbe(p, x)))
        t -= w * math.log(q) + (n - w) * math.log(1 - q)
    return t


def _nelder(fn, x0, pas, it=900):
    """Nelder-Mead, sans dépendance. Quatre paramètres, ça suffit largement."""
    k = len(x0)
    pts = [x0] + [[v + (pas[i] if j == i else 0) for j, v in enumerate(x0)] for i in range(k)]
    val = [fn(p) for p in pts]
    for _ in range(it):
        o = sorted(range(k + 1), key=lambda i: val[i])
        pts, val = [pts[i] for i in o], [val[i] for i in o]
        c = [sum(p[j] for p in pts[:-1]) / k for j in range(k)]
        r = [2 * c[j] - pts[-1][j] for j in range(k)]
        fr = fn(r)
        if fr < val[0]:
            e = [3 * c[j] - 2 * pts[-1][j] for j in range(k)]
            fe = fn(e)
            pts[-1], val[-1] = (e, fe) if fe < fr else (r, fr)
        elif fr < val[-2]:
            pts[-1], val[-1] = r, fr
        else:
            q = [(c[j] + pts[-1][j]) / 2 for j in range(k)]
            fq = fn(q)
            if fq < val[-1]:
                pts[-1], val[-1] = q, fq
            else:
                pts = [pts[0]] + [[(pts[0][j] + p[j]) / 2 for j in range(k)] for p in pts[1:]]
                val = [val[0]] + [fn(p) for p in pts[1:]]
    i = min(range(k + 1), key=lambda i: val[i])
    return pts[i], val[i]


def ajuste(bl, seuil=SEUIL):
    """Plusieurs départs : une logistique a parfois deux creux voisins."""
    d = tranches(bl, seuil)
    meilleur = None
    for m0 in (5, 9, 13):
        p, v = _nelder(lambda p: _nll(p, d), [.05, .85, m0, 2.0], [.03, .05, 2, 1])
        if meilleur is None or v < meilleur[1]:
            meilleur = (p, v)
    return meilleur[0], d


def mi_chemin(p):
    """La pente où la probabilité de marcher franchit 50 %."""
    f, c, m, s = p
    return m + s * math.log((.5 - f) / (c - .5)) if f < .5 < c else None


def wilson(n, w, z=1.96):
    """Intervalle d'une proportion, juste même sur dix blocs."""
    if n == 0:
        return 0.0, 1.0
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    e = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - e), min(1.0, c + e)


def bootstrap(bl, tirages=TIRAGES, graine=4):
    par = {}
    for x in bl:
        par.setdefault(x["seance"], []).append(x)
    random.seed(graine)
    r = []
    for _ in range(tirages):
        e = []
        for g in par.values():
            t = []
            while len(t) < len(g):
                i = random.randrange(0, max(1, len(g) - BLOC_BOOT))
                t += g[i:i + BLOC_BOOT]
            e += t[:len(g)]
        q = mi_chemin(ajuste(e)[0])
        if q is not None:
            r.append(q)
    return L.intervalle(r)


def a_transition(b, tirages=TIRAGES):
    bl = blocs(b)
    p, d = ajuste(bl)
    x50 = mi_chemin(p)
    if x50 is None:
        return None
    lo, hi = bootstrap(bl, tirages)
    compte = {}
    for x in bl:
        if x["pente"] > 6:
            compte[x["seance"]] = compte.get(x["seance"], 0) + 1
    raides = {k for k, n in compte.items() if n >= RAIDE_MIN}
    return {"p": p, "x50": x50, "lo": lo, "hi": hi, "tranches": d,
            "n": len(bl), "seances": len({x["seance"] for x in bl}),
            "seances_raides": len(raides),
            "ecart_max": max(abs(w / n - courbe(p, x)) for x, n, w in d if n >= 25)}


def a_duree(b, t):
    """Le seuil après quelques heures, si la cadence dérive comme mesuré.

    La dérive de cadence est mesurée sur les séances courues à allure tenue.
    Après t heures, une cadence qui a perdu δ·t pas se lit comme une cadence
    fraîche comparée à un seuil relevé d'autant : on réajuste donc la même
    courbe avec SEUIL + δ·t. On ne va pas au-delà de la durée sur laquelle la
    dérive a été mesurée — le reste serait une promesse.
    """
    d = L.a_derive_cadence(b)
    if not d:
        return None
    bl = blocs(b)
    g = L.regulieres([x for x in L.propres(b) if x.get("cad")])
    tmax = max(x["ecoule"] for x in g) / 60
    pts = []
    pas = .25
    k = 0
    while k * pas <= t + 1e-9:
        h = k * pas
        ligne = {"h": h, "mesure": h <= tmax}
        for cle in ("par_h", "lo", "hi"):
            ligne[cle] = mi_chemin(ajuste(bl, SEUIL - d[cle] * h)[0])
        pts.append(ligne)
        k += 1
    return {"pts": pts, "derive": d, "tmax": tmax}


def main() -> int:
    src = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    b = L.charger(src)
    r = a_transition(b)
    if not r:
        print("  la part marchée ne franchit jamais 50 % : pas de transition.")
        return 2
    f, c, m, s = r["p"]
    print(f"\n  {r['n']} blocs avec cadence sur {r['seances']} séances, "
          f"dont {r['seances_raides']} avec du relief au-dessus de 6 %")
    print(f"\n  tranche      n   sous {SEUIL:.0f}    modèle")
    for x, n, w in r["tranches"]:
        print(f"  {x:5.1f} %  {n:5d}   {w / n * 100:5.1f} %   {courbe(r['p'], x) * 100:5.1f} %")
    print(f"\n  plancher {f * 100:.1f} %  plafond {c * 100:.1f} %  largeur {s:.2f} point")
    print(f"  écart maximal modèle–données sur les tranches garnies : "
          f"{r['ecart_max'] * 100:.1f} points")
    print(f"\n  TRANSITION : {r['x50']:.2f} % de pente, IC 95 % [{r['lo']:.2f} ; {r['hi']:.2f}]")
    du = a_duree(b, 3)
    if du:
        dv = du["derive"]
        print(f"\n  DURÉE : cadence {dv['par_h']:+.2f} pas/min par heure "
              f"[{dv['lo']:+.2f} ; {dv['hi']:+.2f}], mesurée jusqu'à {du['tmax'] * 60:.0f} min")
        for q in du["pts"]:
            print(f"    {q['h']:4.2f} h  {q['par_h']:5.2f} %  "
                  f"({q['hi']:.2f} – {q['lo']:.2f})" + ("" if q["mesure"] else "  hors mesure"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
