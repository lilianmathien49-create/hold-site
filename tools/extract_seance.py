#!/usr/bin/env python3
"""Extrait une séance d'un fichier FIT vers tools/test/seance.json.

    python3 tools/extract_seance.py une-seance.fit

Produit ce que tools/build_seance.py dessine : les mesures échantillonnées
toutes les cinq secondes, et les tours tels que la montre les a enregistrés.

Deux choses méritent d'être dites.

Ces montres n'écrivent pas la cadence. Elles écrivent la longueur de foulée :
la cadence s'en déduit, vitesse divisée par foulée. Vérifié sur une séance où
la médiane tombe à 154 pas par minute contre 156 affichés par la montre.

Le fichier produit est anonyme : ni date, ni trace, ni position. Le temps est
compté depuis le départ, et rien n'y situe un lieu.
"""
from __future__ import annotations

import importlib.util
import json
import statistics as st
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "tools" / "test" / "seance.json"
PAS = 5                 # un point toutes les cinq secondes

_spec = importlib.util.spec_from_file_location("fitread", RACINE / "tools" / "fitread.py")
fitread = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fitread)


def cadence(r):
    """Pas par minute, déduits de la vitesse et de la longueur de foulée."""
    v, foulee = r.get("speed"), r.get("foulee")
    if not v or not foulee or foulee < 0.3 or v < 1.5:
        return None
    return v / foulee * 60


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1
    f = Path(argv[1])
    recs, laps = fitread.read_fit(f), fitread.read_laps(f)
    horodates = [r for r in recs if r.get("t")]
    if not horodates:
        print("Aucun point horodaté dans ce fichier.", file=sys.stderr)
        return 1
    t0 = min(r["t"] for r in horodates)

    seaux = {}
    for r in horodates:
        seaux.setdefault(int((r["t"] - t0).total_seconds()) // PAS, []).append(r)

    blocs = []
    for k in sorted(seaux):
        g = seaux[k]

        def med(champ):
            v = [x[champ] for x in g if x.get(champ) is not None]
            return st.median(v) if v else None

        cads = [c for c in (cadence(x) for x in g) if c and 100 < c < 260]
        v = med("speed")
        blocs.append([k * PAS,
                      round(v * 3.6, 1) if v else None,
                      round(med("hr")) if med("hr") else None,
                      round(st.median(cads)) if cads else None,
                      round(med("alt")) if med("alt") is not None else None])

    out = {
        "duree_s": blocs[-1][0] + PAS,
        "km": round(max((r.get("dist") or 0) for r in recs) / 1000, 2),
        "pas": PAS,
        "blocs": blocs,
        "laps": [{"debut": round((l["debut"] - t0).total_seconds()),
                  "duree": round(l.get("duree", 0)),
                  "dist": round(l.get("dist", 0)),
                  "allure": round(1000 / l["speed"]) if l.get("speed", 0) > 0.5 else None,
                  "fc": round(l["hr"]) if l.get("hr") else None}
                 for l in laps],
    }
    SORTIE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")),
                      encoding="utf-8")
    couverts = sum(1 for b in blocs if b[3])
    print(f"  {len(blocs)} points · {out['duree_s'] // 60} min · {out['km']} km · "
          f"{len(out['laps'])} tours")
    print(f"  cadence déduite sur {couverts}/{len(blocs)} points · écrit : {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
