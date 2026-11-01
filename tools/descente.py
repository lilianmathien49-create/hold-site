#!/usr/bin/env python3
"""Les aptitudes d'un coureur en descente, mesurées sur ses séances.

    python3 tools/descente.py --labo ~/Documents/HOLD/Gatien      # fichiers de montre (.fit)
    python3 tools/descente.py --csv tools/athlete-blocks.csv       # blocs simulés
        [--out aptitudes-descente.json]

Trois mesures, chacune avec son intervalle et sa couverture :

1. Le rendement en descente douce (-4 à -15 %) et raide (au-delà de -15 %),
   frais : la vitesse tenue, rapportée à celle que donne le modèle de pente à
   partir de sa propre vitesse sur le plat le même jour. 0,93, c'est 7 % plus
   lent que le modèle. La vitesse du jour sert de référence pour que la forme,
   la météo ou l'intensité de la séance ne passent pas pour de l'aptitude.

2. La fatigue excentrique : ce que la descente perd en plus, à mesure que les
   quadriceps encaissent du dénivelé négatif dans la séance, une fois retirée
   la fatigue générale mesurée sur le plat. En % par 1000 m de D- encaissés.

3. La couverture : combien de temps de descente, à quelle pente, et jusqu'à
   quel D- cumulé. Une mesure sans couverture est dite « non mesurable ».

Chaque intervalle vient d'un bootstrap par séance : on retire au sort des
séances entières, pas des blocs, parce que deux blocs d'une même descente ne
sont pas deux informations indépendantes.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics as st

import numpy as np
from collections import defaultdict
from pathlib import Path

from build_plan import speed_ratio

FRAIS_MIN = (10, 120)  # minutes : après l'échauffement, avant la fatigue
DOUCE, RAIDE = (-15.0, -4.0), (-35.0, -15.0)
TIRAGES = 400
MARCHE_KMH = 6.3  # en dessous, sur le plat, on marche ; au-dessus, même lent et fatigué, on court


def depuis_csv(chemin) -> list[dict]:
    out = []
    with open(chemin, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append({"seance": r["session"], "pente": float(r["slope"]), "v": float(r["kmh"]),
                        "dt": 15.0, "ecoule": float(r["t_s"]) / 60, "type": r.get("type", "")})
    return out


def prepare(blocs):
    """Par séance, dans l'ordre : le D- déjà encaissé, et la vitesse de référence du jour."""
    par = defaultdict(list)
    for b in blocs:
        par[b["seance"]].append(b)
    seances = {}
    for s, bs in par.items():
        bs.sort(key=lambda x: x["ecoule"])
        dm = 0.0
        for b in bs:
            b["dmoins"] = dm
            if b["pente"] < 0:
                dm += -b["pente"] / 100 * b["v"] / 3.6 * b.get("dt", 15)
        # Le plat frais du jour : la référence de vitesse de la séance. Chaque bloc
        # est ramené au plat exact par le modèle de pente : à ±3 %, la vitesse change
        # déjà de plus de 10 %, et la part de petites bosses varie d'une séance à l'autre.
        plat = [b["v"] / speed_ratio(b["pente"] / 100, False) for b in bs
                if abs(b["pente"]) < 3 and b["v"] >= MARCHE_KMH and FRAIS_MIN[0] <= b["ecoule"] <= FRAIS_MIN[1]]
        seances[s] = {"blocs": bs, "plat": st.median(plat) if len(plat) >= 20 else None, "dmax": dm,
                      "duree": bs[-1]["ecoule"] / 60}
    # Une séance sans plat (une sortie tout en côte) prend la vitesse habituelle du coureur.
    connus = [sc["plat"] for sc in seances.values() if sc["plat"]]
    habituel = st.median(connus) if connus else None
    for sc in seances.values():
        if not sc["plat"]:
            sc["plat"], sc["plat_estime"] = habituel, True
    return seances


def log_q(b, plat):
    """Ce que le bloc dit du coureur : sa vitesse rapportée à celle du modèle de pente."""
    return math.log(b["v"] / (plat * speed_ratio(b["pente"] / 100, False)))


def mesure(seances, noms):
    """Une seule estimation pour tout : sur chaque bloc couru,

        log(v / (plat du jour × modèle de pente)) = c_classe − a·h − k·D-

    où c_classe vaut pour le plat, la descente douce ou la descente raide, h est
    l'heure de course au-delà de la première, et D- le dénivelé négatif déjà
    encaissé (le terme k ne joue que dans les descentes). Le rendement frais en
    descente est exp(c_douce − c_plat) et exp(c_raide − c_plat) : la vitesse à
    zéro mètre de D-, et non la moyenne des débuts de sortie, qui en contiennent
    déjà un peu. Estimer tout ensemble évite qu'un biais sur l'un fausse l'autre."""
    X, y, n = [], [], {"douce": 0, "raide": 0}
    for s_ in noms:
        sc = seances[s_]
        if not sc["plat"]:
            continue
        for b in sc["blocs"]:
            if b["ecoule"] < FRAIS_MIN[0]:
                continue
            g = b["pente"]
            h = max(0.0, b["ecoule"] / 60 - 1)
            if abs(g) < 3:
                if b["v"] < MARCHE_KMH:
                    continue
                X.append((1, 0, 0, h, 0.0))
            elif -35 <= g <= -4:
                attendu = sc["plat"] * speed_ratio(g / 100, False)
                if b["v"] < 0.45 * attendu:   # marché ou arrêté, pas couru
                    continue
                if g > -15:
                    X.append((0, 1, 0, h, b["dmoins"] / 1000)); n["douce"] += 1
                else:
                    X.append((0, 0, 1, h, b["dmoins"] / 1000)); n["raide"] += 1
            else:
                continue
            y.append(log_q(b, sc["plat"]))
    out = {"douce": None, "raide": None, "excentrique": None, "generale": None,
           "n_douce": n["douce"], "n_raide": n["raide"]}
    if len(y) < 200:
        return out
    X, y = np.array(X, float), np.array(y)
    garde = [0, 3] + [j for j, k in ((1, "douce"), (2, "raide")) if n[k] >= 40]
    if sum(1 for x in X if x[4] > 1.0) >= 100:
        garde.append(4)
    garde.sort()
    beta = np.linalg.lstsq(X[:, garde], y, rcond=None)[0]
    c = dict(zip(garde, beta))
    out["generale"] = -c[3] * 100
    if 1 in c:
        out["douce"] = math.exp(c[1] - c[0])
    if 2 in c:
        out["raide"] = math.exp(c[2] - c[0])
    if 4 in c:
        out["excentrique"] = -c[4] * 100
    return out


def intervalle(vals):
    vals = sorted(v for v in vals if v is not None)
    if len(vals) < TIRAGES * 0.8:
        return None
    return [vals[int(0.1 * len(vals))], vals[int(0.9 * len(vals)) - 1]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--labo", help="dossier des .fit (ou de son cache)")
    src.add_argument("--csv", help="blocs simulés (simulate_athlete.py)")
    ap.add_argument("--sans-courses", action="store_true", help="écarte les séances de type « course »")
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.csv:
        blocs = depuis_csv(args.csv)
        if args.sans_courses:
            blocs = [b for b in blocs if b["type"] != "course"]
    else:
        import labo_calc
        blocs = labo_calc.charger(Path(args.labo).expanduser())
    seances = prepare(blocs)
    noms = sorted(seances)

    m = mesure(seances, noms)
    rng = random.Random(5)
    boot = [mesure(seances, [rng.choice(noms) for _ in noms]) for _ in range(TIRAGES)]
    ic = {k: intervalle([b[k] for b in boot]) for k in ("douce", "raide", "excentrique")}

    desc = [b for s in noms for b in seances[s]["blocs"] if b["pente"] <= -4]
    couv = {
        "seances": len(noms),
        "heures_descente": round(sum(b.get("dt", 15) for b in desc) / 3600, 1),
        "heures_raide": round(sum(b.get("dt", 15) for b in desc if b["pente"] <= -15) / 3600, 1),
        "dmoins_max": round(max(sc["dmax"] for sc in seances.values())),
        "heures_descente_apres_1000m": round(sum(b.get("dt", 15) for b in desc if b["dmoins"] > 1000) / 3600, 1),
        "seance_max_h": round(max(sc["duree"] for sc in seances.values()), 1),
    }

    def dire(nom, v, i, fmt):
        if v is None:
            return f"  {nom:34} non mesurable"
        return f"  {nom:34} {fmt(v)}" + (f"   (8 fois sur 10 entre {fmt(i[0])} et {fmt(i[1])})" if i else "")
    pc = lambda q: f"{q:.2f}"
    print(f"  {couv['seances']} séances · {couv['heures_descente']} h de descente dont {couv['heures_raide']} h au-delà "
          f"de 15 % · D- max encaissé en une séance : {couv['dmoins_max']} m · "
          f"{couv['heures_descente_apres_1000m']} h de descente après 1000 m de D-")
    print(dire("Descente douce, frais (× modèle)", m["douce"], ic["douce"], pc))
    print(dire("Descente raide, frais (× modèle)", m["raide"], ic["raide"], pc))
    print(dire("Fatigue excentrique (%/1000 m D-)", m["excentrique"], ic["excentrique"], lambda x: f"{x:+.1f}"))
    exc_ok = ic["excentrique"] and (ic["excentrique"][0] > 0 or ic["excentrique"][1] < 0)
    if m["excentrique"] is not None and not exc_ok:
        print("    → l'intervalle contient zéro : la fatigue excentrique n'est pas mesurable sur ces séances.")
    if args.out:
        Path(args.out).write_text(json.dumps({"mesure": m, "intervalles": ic, "couverture": couv,
                                              "excentrique_mesurable": bool(exc_ok)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
