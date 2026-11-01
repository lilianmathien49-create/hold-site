#!/usr/bin/env python3
"""Ce que disent les éditions précédentes : la fenêtre de passage pour réussir
l'objectif, et la chance de le tenir selon l'heure à laquelle on passe.

    python3 tools/editions.py plan.json tools/utmb-field.json tools/utmb-28h-large.json

Ajoute au plan une clé « editions », que l'espace du coureur affiche dans
l'onglet « Éditions précédentes ». Le plan est réécrit en place (ou --out).

Deux calculs, dans cet ordre :

1. La fenêtre. Parmi les finishers des éditions passées qui ont réussi
   l'objectif sans le dépasser (arrivés dans l'heure qui le précède), on relève
   à chaque ravitaillement l'heure de passage : 1 sur 10 était plus tôt, 1 sur
   10 plus tard. Entre les deux, c'est la route qu'ont prise ceux qui ont réussi.

2. Le Monte-Carlo. Pour une heure de passage donnée à un ravitaillement, on
   reprend les coureurs passés au même endroit à peu près à la même heure, on
   tire au sort la suite de leur course (ramenée à ton allure), vingt mille fois,
   et on compte combien de ces fins de course tiennent l'objectif. On en tire la
   chance de réussir si tu passes à ton heure cible, et l'heure au-delà de
   laquelle cette chance tombe sous une sur deux.

3. Le Monte-Carlo portion par portion. Vingt mille courses sont déroulées d'un
   ravitaillement au suivant. À chaque portion, on tire au sort un vrai coureur
   des éditions passées qui avait, à cet endroit, le même retard ou la même
   avance que la course simulée sur le temps habituel ; on prend l'écart qu'il a
   fait sur la portion suivante par rapport au temps habituel, et on l'applique
   à ton temps prévu. Un retard pris tôt pèse donc sur la suite, comme dans la
   réalité. On en tire, à chaque ravitaillement, la fourchette où tu passes 8
   fois sur 10, et la fourchette d'arrivée.

La cible elle-même vient du plan, c'est-à-dire de tes séances : ce script ne la
change pas, il la situe dans ce qu'ont fait les autres.

Les archives ne contiennent que des finishers : les abandons n'y sont pas, et
toutes les chances calculées ici sont des chances parmi ceux qui finissent.

Les coureurs sont repérés par la fraction de distance parcourue plutôt que par
le nom du point : le parcours a un peu bougé d'une édition à l'autre.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from bisect import bisect_left
from pathlib import Path

TIRAGES = 20000
VOISINS = 200   # coureurs passés au plus près de l'heure étudiée
GRAINE = 7


def secondes(t) -> int | None:
    """« 28h00 », « 28:00 », « 4h11 », « 12:53:35 » → secondes."""
    s = str(t or "").strip()
    m = re.fullmatch(r"(\d+)h(\d{1,2})?", s)
    if m:
        return int(m[1]) * 3600 + int(m[2] or 0) * 60
    m = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", s)
    if m:
        return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3] or 0)
    return None


def coureurs(fichiers: list[Path]) -> list[dict]:
    """Tous les finishers des fichiers, une seule fois chacun, avec leurs passages
    exprimés en fraction de la distance de leur édition."""
    vus, out = set(), []
    for f in fichiers:
        for r in json.loads(f.read_text())["runners"]:
            cle = (r["year"], r["bib"])
            if cle in vus or not r.get("time"):
                continue
            pts = [(s["km"], s["elapsed"]) for s in r["splits"] if s.get("elapsed") is not None]
            if len(pts) < 5:
                continue
            total = pts[-1][0]
            vus.add(cle)
            out.append({"annee": r["year"], "fin": r["time"],
                        "frac": [k / total for k, _ in pts], "t": [e for _, e in pts]})
    return out


def passage(r: dict, f: float) -> float | None:
    """Heure de passage interpolée à la fraction f du parcours."""
    xs, ys = r["frac"], r["t"]
    if f <= xs[0]:
        return ys[0]
    if f >= xs[-1]:
        return None
    i = bisect_left(xs, f)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (f - x0) / (x1 - x0) if x1 > x0 else y0


def quantile(v: list[float], q: float) -> float:
    v = sorted(v)
    i = q * (len(v) - 1)
    a = int(i)
    return v[a] + (v[min(a + 1, len(v) - 1)] - v[a]) * (i - a)


def chance(pool: list[tuple[float, float]], t: float, objectif: int, rng: random.Random) -> float:
    """Monte-Carlo : chance de finir sous l'objectif en passant à t.

    pool : (heure de passage, temps final) des coureurs passés à ce point.
    On garde les VOISINS les plus proches de t ; chaque tirage prend l'un d'eux
    au hasard (les plus proches pèsent plus), ramène la suite de sa course à
    l'allure de quelqu'un qui passe à t, et regarde où elle finit."""
    proches = sorted(pool, key=lambda p: abs(p[0] - t))[:VOISINS]
    if not proches:
        return float("nan")
    largeur = max(abs(proches[-1][0] - t), 60.0)
    poids = [max(1e-6, 1 - (abs(p[0] - t) / largeur) ** 2) for p in proches]
    tirages = rng.choices(proches, weights=poids, k=TIRAGES)
    ok = sum(1 for tp, fin in tirages if t + (fin - tp) * (t / tp) <= objectif)
    return ok / TIRAGES


def borne(pool, objectif, rng, seuil, t_lo, t_hi) -> float:
    """L'heure de passage à laquelle la chance vaut « seuil » (dichotomie)."""
    for _ in range(22):
        mid = (t_lo + t_hi) / 2
        if chance(pool, mid, objectif, rng) >= seuil:
            t_lo = mid
        else:
            t_hi = mid
    return (t_lo + t_hi) / 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("donnees", nargs="+", help="fichiers de passages (collect_utmb.py)")
    ap.add_argument("--out")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text())
    objectif = secondes(plan.get("goal"))
    distance = plan.get("distanceKm")
    if not objectif or not distance:
        raise SystemExit("  Le plan doit avoir un objectif (goal) et une distance (distanceKm).")

    tous = coureurs([Path(f) for f in args.donnees])
    reussi = [r for r in tous if objectif - 3600 <= r["fin"] <= objectif]
    annees = sorted({r["annee"] for r in tous})
    print(f"  {len(tous)} finishers ({annees[0]} à {annees[-1]}), dont {len(reussi)} arrivés "
          f"dans l'heure avant l'objectif")

    rng = random.Random(GRAINE)
    points = []
    for a in plan.get("aid", []):
        if a["km"] <= 0.5 or a["km"] >= distance - 0.5:
            continue
        f = a["km"] / distance
        heures = [h for h in (passage(r, f) for r in reussi) if h is not None]
        pool = [(h, r["fin"]) for r in tous if (h := passage(r, f)) is not None]
        cible = secondes(a.get("cumul"))
        if len(heures) < 30 or not cible:
            continue
        lo, med, hi = (quantile(heures, q) for q in (0.1, 0.5, 0.9))
        t50 = borne(pool, objectif, rng, 0.5, lo * 0.8, hi * 1.3)
        points.append({
            "name": a["name"], "km": a["km"],
            "lo": round(lo), "med": round(med), "hi": round(hi),
            "cible": cible, "p": round(chance(pool, cible, objectif, rng), 3),
            "t50": round(t50), "n": len(heures),
        })
        print(f"  {a['name'][:28]:28} fenêtre {lo/3600:5.2f}–{hi/3600:5.2f} h · cible {cible/3600:5.2f} h"
              f" · chance {points[-1]['p']:.0%} · limite {t50/3600:5.2f} h")

    # --- Le Monte-Carlo portion par portion -------------------------------
    # Les repères : chaque ravitaillement retenu, puis l'arrivée.
    fracs = [p["km"] / distance for p in points] + [1.0]
    cibles = [p["cible"] for p in points] + [secondes(plan.get("projected")) or objectif]
    meds = [p["med"] for p in points] + [quantile([r["fin"] for r in reussi], 0.5)]
    # Les passages de chaque coureur à chaque repère (None si l'interpolation échoue).
    pass_r = []
    for r in tous:
        ts = [passage(r, f) for f in fracs[:-1]] + [r["fin"]]
        if all(t is not None for t in ts):
            pass_r.append(ts)
    # Le rythme de chacun sur chaque portion, rapporté à sa propre allure jusque-là :
    # 1, c'est la portion courue comme le finisher médian l'aurait courue à cette
    # allure ; 1,1, dix pour cent plus lentement. Rapporté à soi plutôt qu'au
    # temps habituel, un départ prudent ne passe pas pour un manque de niveau.
    K = len(fracs)
    jambe_med = [meds[0]] + [meds[k] - meds[k - 1] for k in range(1, K)]
    jambe_cible = [cibles[0]] + [cibles[k] - cibles[k - 1] for k in range(1, K)]
    rho = [[0.0] * len(pass_r) for _ in range(K)]
    for i, ts in enumerate(pass_r):
        rho[0][i] = ts[0] / (meds[0] * ts[-1] / meds[-1])
        for k in range(1, K):
            rho[k][i] = (ts[k] - ts[k - 1]) / (ts[k - 1] * jambe_med[k] / meds[k - 1])

    # Pour chaque portion, les coureurs triés par leur rythme : on y cherche vite
    # ceux qui venaient de courir la portion précédente au même rythme.
    from bisect import bisect_left as _bl
    tri = [sorted(range(len(pass_r)), key=lambda i, k=k: rho[k][i]) for k in range(K)]
    cles = [[rho[k][i] for i in tri[k]] for k in range(K)]

    def voisin(k, r_):
        """Un coureur tiré parmi les VOISINS dont le rythme sur la portion k est le plus proche de r_."""
        j = _bl(cles[k], r_)
        lo_, hi_ = max(0, j - VOISINS // 2), min(len(cles[k]), j + VOISINS // 2)
        return tri[k][rng.randrange(lo_, hi_)]

    sims = [[0.0] * K for _ in range(TIRAGES)]
    for n in range(TIRAGES):
        i = rng.randrange(len(pass_r))
        r_ = rho[0][i]
        t = jambe_cible[0] * r_
        sims[n][0] = t
        for k in range(1, K):
            i = voisin(k - 1, r_)      # quelqu'un qui venait de courir comme toi
            r_ = rho[k][i]             # ce qu'il a fait sur la portion suivante
            t += jambe_cible[k] * r_
            sims[n][k] = t
    for k, p in enumerate(points):
        col = sorted(s_[k] for s_ in sims)
        p["mcLo"], p["mcMed"], p["mcHi"] = (round(quantile(col, q)) for q in (0.1, 0.5, 0.9))
    arrivees = sorted(s_[-1] for s_ in sims)
    mc = {
        "lo": round(quantile(arrivees, 0.1)), "med": round(quantile(arrivees, 0.5)),
        "hi": round(quantile(arrivees, 0.9)),
        "chance": round(sum(1 for a_ in arrivees if a_ <= objectif) / TIRAGES, 3),
    }
    print(f"  Monte-Carlo portion par portion : arrivée 8 fois sur 10 entre {mc['lo']/3600:.2f} et "
          f"{mc['hi']/3600:.2f} h (médiane {mc['med']/3600:.2f} h) · {mc['chance']:.0%} sous l'objectif")

    # La phrase de tête : au premier tiers, là où la course se décide sans être jouée.
    tete = min(points, key=lambda p: abs(p["km"] / distance - 1 / 3)) if points else None
    plan["editions"] = {
        "target": plan["goal"], "targetSec": objectif,
        "runners": len(tous), "finishers": len(reussi), "years": [annees[0], annees[-1]],
        "draws": TIRAGES,
        "source": "Archives publiques LiveTrail (chronométreur officiel UTMB)",
        "points": points,
        "headline": {"name": tete["name"], "p": tete["p"]} if tete else None,
        "simulation": mc,
    }
    Path(args.out or args.plan).write_text(json.dumps(plan, ensure_ascii=False))
    print(f"  écrit : {args.out or args.plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
