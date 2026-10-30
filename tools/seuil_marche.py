#!/usr/bin/env python3
"""Le seuil de marche par mélange de deux gaussiennes sur la cadence.

    python3 tools/seuil_marche.py ~/Documents/HOLD/i252597_fit_files-3
    python3 tools/seuil_marche.py            # repart du cache de labo_calc

La méthode, dans l'ordre :

1. On nettoie. Les blocs à l'arrêt sont déjà écartés à la construction (moins
   de 3 m parcourus en 15 s) ; on retire ici ceux sous 60 pas/min et ceux
   au-dessus de 220, qui ne sont pas des cadences mais des erreurs de lecture
   de la longueur de foulée.
2. On ajuste un mélange à deux gaussiennes par espérance-maximisation. Le
   seuil est le point où les deux probabilités a posteriori s'égalent, cherché
   entre les deux moyennes par dichotomie.
3. On garde l'incertitude. Aucun bloc n'est forcé à « oui » ou « non » : chacun
   porte sa probabilité d'appartenir à la composante basse, le temps marché
   est une espérance et non un comptage, et les blocs dont la probabilité
   tient entre 0,25 et 0,75 sont comptés comme ambigus.

Et surtout : le résultat n'est publié que s'il passe cinq contrôles. Un
mélange à deux composantes s'ajuste TOUJOURS, y compris sur une distribution
qui n'en contient qu'une — il se contente alors d'attraper les queues. Les
contrôles sont là pour distinguer deux comportements d'un seul comportement
mal modélisé, et la barre des 140 pas/min en fait partie : une composante
basse qui se pose au-dessus n'est pas de la marche.

Le second volet reprend la même mesure par tranche de temps écoulé, pour voir
si le seuil se déplace au fil des heures. Il ne tourne que si le premier a
conclu.
"""
from __future__ import annotations

import math
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labo_calc as L

CAD_MIN, CAD_MAX = 60.0, 220.0
AMBIGU = (0.25, 0.75)
REPERE = 140.0            # au-dessus, une composante « basse » n'est pas de la marche

# Les cinq contrôles, et ce que chacun écarte.
SEPARATION = 1.5          # écarts-types entre les moyennes : deux modes, ou un seul ?
POIDS_MIN = 0.02          # moins de 2 % de marche : rien à en tirer pour un plan


def densite(x, m, s):
    return math.exp(-((x - m) ** 2) / (2 * s * s)) / (s * math.sqrt(2 * math.pi))


def em(xs, iters=500):
    """Espérance-maximisation, deux composantes, une dimension.

    Départ aux quantiles 20 % et 70 % plutôt qu'à des valeurs choisies : une
    initialisation écrite en dur impose au résultat la forme qu'on attendait.
    """
    q = sorted(xs)
    m1, m2 = q[len(q) // 5], q[len(q) * 7 // 10]
    if m2 - m1 < 1:
        m1, m2 = q[0], q[-1]
    s1 = s2 = max(1.0, st.pstdev(xs) / 2)
    w1 = 0.5
    for _ in range(iters):
        r = []
        for x in xs:
            a, b = w1 * densite(x, m1, s1), (1 - w1) * densite(x, m2, s2)
            r.append(a / (a + b) if a + b > 0 else 0.5)
        n1 = sum(r)
        if n1 < 2 or len(xs) - n1 < 2:
            return None
        w1 = n1 / len(xs)
        m1 = sum(ri * x for ri, x in zip(r, xs)) / n1
        m2 = sum((1 - ri) * x for ri, x in zip(r, xs)) / (len(xs) - n1)
        s1 = max(1.0, math.sqrt(sum(ri * (x - m1) ** 2 for ri, x in zip(r, xs)) / n1))
        s2 = max(1.0, math.sqrt(sum((1 - ri) * (x - m2) ** 2
                                    for ri, x in zip(r, xs)) / (len(xs) - n1)))
    if m1 > m2:                       # la composante basse reste la première
        w1, m1, s1, m2, s2 = 1 - w1, m2, s2, m1, s1
    return {"w": w1, "m1": m1, "s1": s1, "m2": m2, "s2": s2}


def seuil(p):
    """Le point où les deux probabilités a posteriori s'égalent."""
    f = lambda x: p["w"] * densite(x, p["m1"], p["s1"]) \
        - (1 - p["w"]) * densite(x, p["m2"], p["s2"])
    a, z = p["m1"], p["m2"]
    if f(a) * f(z) > 0:
        return None                   # aucune bascule entre les deux moyennes
    for _ in range(200):
        mid = (a + z) / 2
        if f(a) * f(mid) <= 0:
            z = mid
        else:
            a = mid
    return (a + z) / 2


def proba(x, p):
    a, b = p["w"] * densite(x, p["m1"], p["s1"]), \
        (1 - p["w"]) * densite(x, p["m2"], p["s2"])
    return a / (a + b) if a + b > 0 else 0.5


def bic(xs, p):
    ll = sum(math.log(max(1e-300, p["w"] * densite(x, p["m1"], p["s1"])
                          + (1 - p["w"]) * densite(x, p["m2"], p["s2"]))) for x in xs)
    return -2 * ll + 5 * math.log(len(xs))


def bic_une(xs):
    m, s = st.fmean(xs), max(1e-9, st.pstdev(xs))
    ll = sum(math.log(max(1e-300, densite(x, m, s))) for x in xs)
    return -2 * ll + 2 * math.log(len(xs))


def mesure(cads):
    """Ajuste, puis juge. Renvoie le diagnostic complet, verdict compris."""
    p = em(cads)
    if not p:
        return {"ok": False, "pourquoi": "le mélange ne converge pas"}
    s = seuil(p)
    sep = abs(p["m2"] - p["m1"]) / ((p["s1"] + p["s2"]) / 2)
    b2, b1 = bic(cads, p), bic_une(cads)
    probas = [proba(x, p) for x in cads]
    controles = [
        ("deux composantes valent mieux qu'une", b2 < b1, f"BIC {b2:.0f} contre {b1:.0f}"),
        ("les composantes se séparent", sep >= SEPARATION, f"{sep:.2f} écart-type"),
        ("il existe une bascule entre les deux", s is not None, "—" if s else "aucune"),
        ("la composante basse pèse", p["w"] >= POIDS_MIN, f"{p['w'] * 100:.1f} %"),
        ("le seuil est plausible", s is not None and s <= REPERE,
         f"{s:.0f} pas/min" if s else "sans objet"),
    ]
    return {"ok": all(c[1] for c in controles), "p": p, "seuil": s, "sep": sep,
            "bic2": b2, "bic1": b1, "controles": controles,
            "attendu": sum(probas), "n": len(cads),
            "ambigus": sum(1 for q in probas if AMBIGU[0] < q < AMBIGU[1]),
            "surs": sum(1 for q in probas if q >= AMBIGU[1])}


def nettoie(b):
    return [x for x in b if x.get("cad") and CAD_MIN <= x["cad"] <= CAD_MAX]


def essai():
    """Vérifie que l'instrument détecte ce qu'il prétend détecter.

    Un verdict « non mesurable » ne vaut que si la méthode sait dire oui
    ailleurs. On lui donne donc un coureur simulé dont on connaît la vérité :
    30 % de marche à 115 pas/min, le reste de course à 157, le seuil vrai
    tombant vers 134. Puis un coureur qui ne marche jamais, où elle doit
    refuser de conclure.
    """
    import random
    random.seed(1)

    def tire(n, part, mm, sm, mc, sc):
        return [random.gauss(mm, sm) if random.random() < part else random.gauss(mc, sc)
                for _ in range(n)]

    cas = [("un coureur qui marche 30 % du temps", tire(8000, 0.30, 115, 8, 157, 8), True),
           ("un coureur qui marche 8 % du temps", tire(8000, 0.08, 118, 8, 156, 7), True),
           ("un coureur qui ne marche jamais", tire(8000, 0.0, 0, 1, 155, 9), False)]
    ko = 0
    for nom, cads, attendu in cas:
        r = mesure([c for c in cads if CAD_MIN <= c <= CAD_MAX])
        bon = r["ok"] == attendu
        ko += not bon
        detail = f"seuil {r['seuil']:.0f}" if r.get("seuil") and r["ok"] else "refus"
        print(f"    {'oui' if bon else 'NON'}  {nom:38s} {detail}")
        if r["ok"] and attendu:
            vrai = sum(1 for c in cads if c < 136) / len(cads)
            print(f"         marche attendue {r['attendu'] * 100 / r['n']:.1f} % "
                  f"contre {vrai * 100:.1f} % en vérité")
    bilan = "les trois cas passent" if not ko else f"{ko} cas en échec"
    print("\n  " + bilan)
    return 1 if ko else 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--essai":
        print("\n  ESSAI SUR COUREURS SIMULÉS")
        return essai()
    src = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    brut = L.charger(src)
    b = nettoie(brut)
    seances = len({x["seance"] for x in b})
    print(f"\n  {len(brut)} blocs de {L.PAS} s sur {seances} séances")
    print(f"  {len(brut) - len(b)} retirés hors de {CAD_MIN:.0f}–{CAD_MAX:.0f} pas/min, "
          f"il en reste {len(b)}")

    r = mesure([x["cad"] for x in b])
    if "p" in r:
        p = r["p"]
        print(f"\n  MÉLANGE")
        print(f"    basse   poids {p['w'] * 100:5.1f} %   moyenne {p['m1']:6.1f}   "
              f"écart-type {p['s1']:5.1f}")
        print(f"    haute   poids {(1 - p['w']) * 100:5.1f} %   moyenne {p['m2']:6.1f}   "
              f"écart-type {p['s2']:5.1f}")
        print(f"    seuil   {r['seuil']:.1f} pas/min" if r["seuil"] else
              "    seuil   aucun entre les deux moyennes")
        print(f"\n  INCERTITUDE")
        print(f"    temps attendu en marche   {r['attendu'] * L.PAS / 60:.1f} min "
              f"({r['attendu'] * 100 / r['n']:.2f} % des blocs)")
        print(f"    blocs ambigus             {r['ambigus']} "
              f"({r['ambigus'] * 100 / r['n']:.2f} %)")

    print(f"\n  CONTRÔLES")
    for nom, ok, detail in r.get("controles", []):
        print(f"    {'oui' if ok else 'NON'}  {nom:38s} {detail}")

    if not r["ok"]:
        rates = [c[0] for c in r.get("controles", []) if not c[1]]
        print(f"\n  VERDICT : seuil de marche NON MESURABLE sur ces séances.")
        print(f"            {len(rates)} contrôle(s) en échec : {', '.join(rates)}.")
        if "p" in r and r["p"]["m1"] > REPERE:
            print(f"            La composante basse se pose à {r['p']['m1']:.0f} pas/min,")
            print(f"            au-dessus du repère de {REPERE:.0f} : ce n'est pas de la marche,")
            print(f"            c'est la queue basse d'une seule et même façon de courir.")
        print(f"\n            Rien n'est publié. Il faut des séances où l'on marche")
        print(f"            vraiment — du trail, ou des montées longues.")
        return 2

    print(f"\n  VERDICT : seuil à {r['seuil']:.0f} pas/min, mesuré.")
    print(f"\n  DURÉE — le seuil bouge-t-il au fil des heures ?")
    for lo, hi in [(0, 45), (45, 90), (90, 150), (150, 400)]:
        g = [x["cad"] for x in b if lo <= x["ecoule"] < hi]
        ns = len({x["seance"] for x in b if lo <= x["ecoule"] < hi})
        if len(g) < 400:
            print(f"    {lo:3d}–{hi:3d} min   n={len(g):5d}   trop peu pour conclure")
            continue
        rr = mesure(g)
        print(f"    {lo:3d}–{hi:3d} min   n={len(g):5d} ({ns} séances)   "
              + (f"seuil {rr['seuil']:.0f} pas/min" if rr["ok"]
                 else "non mesurable sur cette tranche"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
