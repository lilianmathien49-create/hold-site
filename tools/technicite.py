#!/usr/bin/env python3
"""La technicité, portion par portion : ce que les finishers perdent au-delà de
ce que la pente et la durée expliquent, confronté à ce que dit OpenStreetMap.

    python3 tools/technicite.py PLAN_SANS_SPLITS.json tools/utmb-terrain.json \
        tools/utmb-field.json tools/utmb-28h-large.json [--out tools/utmb-technicite.json]

PLAN_SANS_SPLITS est un plan construit sur le même GPX sans --splits : ses temps
de tronçon sont ceux du modèle de pente seul, c'est la référence « théorique ».

Trois étapes :

1. Pour chaque portion (d'un ravitaillement au suivant), le temps réel médian
   des finishers, rapporté à leur temps total et sans l'arrêt au ravitaillement
   quand le passage est pris à la sortie.
2. On retire ce qu'expliquent le dénivelé (positif, négatif, et la part de
   descente raide au-delà de 15 %), la place dans la course (fatigue, effet
   départ) et la nuit. Ce qui reste, en z-score, est ce que le terrain coûte
   en plus ou en moins.
3. On met ce reste en face des mesures OpenStreetMap de la portion (type de
   voie, difficulté T1–T6, revêtement, sinuosité) et on regarde lesquelles
   l'expliquent, avec un test de permutation : sur vingt-trois portions, une
   corrélation de 0,4 peut sortir du hasard.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics as st
from pathlib import Path

import numpy as np

from learn_splits import canon

MEME_PARCOURS = 2018  # depuis 2018 : Saint-Gervais, Checrouit, La Giète, Les Tseppes, comme le tracé actuel


def coureurs_bruts(fichiers, depuis):
    """Les finishers des éditions sur le parcours actuel, avec leurs passages par nom.

    Un ravitaillement peut avoir deux pointages (entrée et sortie) qui portent le
    même nom une fois nettoyé : on garde l'arrivée et la sortie, pour pouvoir
    retirer l'arrêt de la portion."""
    out, vus = [], set()
    for f in fichiers:
        for r in json.loads(Path(f).read_text())["runners"]:
            if r["year"] < depuis or (r["year"], r["bib"]) in vus or not r.get("time"):
                continue
            vus.add((r["year"], r["bib"]))
            arrivee, sortie = {}, {}
            for sp in r["splits"]:
                if sp.get("elapsed") is None or sp["km"] < 1.0:
                    continue
                k = canon(sp["name"])
                arrivee.setdefault(k, sp["elapsed"])
                sortie[k] = sp["elapsed"] + (sp.get("stop") or 0 if 0 < (sp.get("stop") or 0) < 5400 else 0)
            out.append({"fin": r["time"], "annee": r["year"], "arrivee": arrivee, "sortie": sortie})
    return out


def heures(r, aid):
    """(arrivée, sortie) du coureur à chaque ravitaillement du plan. Un point qu'il n'a
    pas pointé est interpolé, au kilomètre, entre ses deux voisins pointés."""
    noms = [canon(a["name"]) for a in aid]
    arr = [0.0 if i == 0 else (r["fin"] if i == len(aid) - 1 else r["arrivee"].get(n)) for i, n in enumerate(noms)]
    sor = [0.0 if i == 0 else (r["fin"] if i == len(aid) - 1 else r["sortie"].get(n)) for i, n in enumerate(noms)]
    connus = [i for i, t in enumerate(arr) if t is not None]
    for i, t in enumerate(arr):
        if t is None:
            a = max(k for k in connus if k < i)
            b = min(k for k in connus if k > i)
            f = (aid[i]["km"] - aid[a]["km"]) / (aid[b]["km"] - aid[a]["km"])
            arr[i] = sor[i] = sor[a] + (arr[b] - sor[a]) * f
    return arr, sor


def part(points, a, b, cle, val=None):
    """Part de la portion [a, b] (km) où points[cle] vaut val (ou est vrai)."""
    p = [x for x in points if a <= x["km"] < b]
    if not p:
        return float("nan")
    return sum(1 for x in p if (x.get(cle) == val if val is not None else bool(x.get(cle)))) / len(p)


def permutation_r(x, y, n=5000, rng=random.Random(3)):
    """Corrélation, et la part des permutations qui font au moins aussi bien."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = ~(np.isnan(x) | np.isnan(y))
    x, y = x[ok], y[ok]
    if len(x) < 6 or x.std() == 0:
        return float("nan"), float("nan")
    r = float(np.corrcoef(x, y)[0, 1])
    yy = list(y)
    plus = 0
    for _ in range(n):
        rng.shuffle(yy)
        if abs(np.corrcoef(x, yy)[0, 1]) >= abs(r):
            plus += 1
    return r, plus / n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("terrain")
    ap.add_argument("donnees", nargs="+")
    ap.add_argument("--out")
    ap.add_argument("--annees", choices=["paires", "impaires"], help="contrôle de stabilité : une moitié des éditions")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text())
    terr = json.loads(Path(args.terrain).read_text())
    pts, virages = terr["points"], terr["virages"]
    D, segs, aid = plan["distanceKm"], plan["segments"], plan["aid"]
    run = coureurs_bruts(args.donnees, MEME_PARCOURS)
    if args.annees:
        run = [r for r in run if r["annee"] % 2 == (0 if args.annees == "paires" else 1)]
    noms_pointes = {canon(a["name"]) for a in aid[1:-1]}
    pointes = {n for n in noms_pointes if sum(1 for r in run if n in r["arrivee"]) > len(run) * 0.5}
    print(f"  {len(run)} finishers de {MEME_PARCOURS} à {max(r['annee'] for r in run)} · "
          f"{len(pointes)} ravitaillements sur {len(noms_pointes)} pointés par la plupart d'entre eux")
    passages = [heures(r, aid) for r in run]
    print(f"  non pointés, fusionnés avec la portion voisine : "
          f"{', '.join(a['name'] for a in aid[1:-1] if canon(a['name']) not in pointes) or 'aucun'}")
    # Les bornes de mesure : on enjambe les points que la plupart n'ont pas pointés.
    bornes = [0] + [i for i, a in enumerate(aid[1:-1], 1) if canon(a["name"]) in pointes] + [len(aid) - 1]

    L = []
    for ja, jb in zip(bornes, bornes[1:]):
        a, b = aid[ja], aid[jb]
        sg = [s for s in segs if a["km"] - 0.01 <= s["km0"] < b["km"]]
        if not sg:
            continue
        dist = b["km"] - a["km"]
        fa, fb = a["km"] / D, b["km"] / D
        parts = []
        for r, (arr, sor) in zip(run, passages):
            leg = arr[jb] - sor[ja]   # de la sortie d'un ravitaillement à l'arrivée au suivant
            if leg > 0:
                parts.append(leg / r["fin"])
        if len(parts) < 100:
            continue
        v = [dc for k, dc in virages if a["km"] <= k < b["km"]]
        L.append({
            "de": a["name"], "a": b["name"], "km0": a["km"], "km1": b["km"],
            "dplus": sum(s["up"] for s in sg) / dist, "dmoins": sum(s["down"] for s in sg) / dist,
            "raide": sum(s["km1"] - s["km0"] for s in sg if s["slope"] <= -15) / dist,
            "pos": (fa + fb) / 2, "nuit": sum(1 for s in sg if s["light"] == "nuit") / len(sg),
            "reel": st.median(parts), "modele": sum(s["split"] for s in sg),
            # OpenStreetMap et la trace
            "sentier": part(pts, a["km"], b["km"], "voie", "sentier"),
            "piste": part(pts, a["km"], b["km"], "voie", "piste"),
            "route": part(pts, a["km"], b["km"], "voie", "route"),
            "t3": (lambda p: sum(1 for x in p if (x.get("sac") or 0) >= 3) / len(p) if p else float("nan"))(
                [x for x in pts if a["km"] <= x["km"] < b["km"]]),
            "roche": part(pts, a["km"], b["km"], "rev", "roche"),
            "terre": part(pts, a["km"], b["km"], "rev", "terre"),
            "sac_moy": (lambda p: st.mean(p) if p else float("nan"))(
                [x["sac"] for x in pts if a["km"] <= x["km"] < b["km"] and x.get("sac")]),
            "sac_couv": part(pts, a["km"], b["km"], "sac"),
            "virages": sum(v) / dist if v else float("nan"),
        })

    tr = sum(l["reel"] for l in L)
    tm = sum(l["modele"] for l in L)
    y = np.array([math.log((l["reel"] / tr) / (l["modele"] / tm)) for l in L])
    X = np.column_stack([np.ones(len(L)),
                         [l["dplus"] / 100 for l in L], [l["dmoins"] / 100 for l in L], [l["raide"] for l in L],
                         [l["pos"] for l in L], [l["pos"] ** 2 for l in L], [l["nuit"] for l in L]])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ beta
    r2 = 1 - (res ** 2).sum() / ((y - y.mean()) ** 2).sum()
    sd = res.std(ddof=X.shape[1])
    for l, e in zip(L, res):
        l["reste"], l["z"] = float(e), float(e / sd)
    print(f"\n  Pente, descente raide, place dans la course et nuit expliquent {r2:.0%} des écarts entre portions ;"
          f" il reste {sd * 100:.0f} % d'écart typique.\n")
    print(f"  {'portion':36} {'reste':>6} {'z':>5} │ {'sentier':>7} {'T3+':>4} {'roche':>5} {'terre':>5} {'virages':>7} {'diff. renseignée':>16}")
    for l in sorted(L, key=lambda l: -l["z"]):
        print(f"  {l['de'][:16] + ' → ' + l['a'][:16]:36} {(math.exp(l['reste']) - 1) * 100:+5.0f}% {l['z']:+5.1f} │"
              f" {l['sentier'] * 100:6.0f}% {l['t3'] * 100:3.0f}% {l['roche'] * 100:4.0f}% {l['terre'] * 100:4.0f}%"
              f" {l['virages']:6.0f}°/km {l['sac_couv'] * 100:15.0f}%")

    print("\n  Ce qui, dans OpenStreetMap, va avec le reste (corrélation · part du hasard) :")
    zs = [l["z"] for l in L]
    tests = {}
    for k, nom in (("sentier", "part de sentier"), ("t3", "part en T3 ou plus"), ("sac_moy", "difficulté moyenne"),
                   ("roche", "part rocheuse"), ("terre", "part terre/herbe"), ("piste", "part de piste"),
                   ("route", "part de route"), ("virages", "sinuosité")):
        r, p = permutation_r([l[k] for l in L], zs)
        tests[k] = {"r": r, "p": p}
        print(f"    {nom:22} r = {r:+.2f} · {p:.0%}{'   ◀' if p < 0.1 else ''}")

    if args.out:
        Path(args.out).write_text(json.dumps({"r2": r2, "ecartType": sd, "beta": beta.tolist(),
                                              "portions": L, "tests": tests}, ensure_ascii=False, indent=1))
        print(f"\n  écrit : {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
