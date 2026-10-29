#!/usr/bin/env python3
"""Dessine la séance brute affichée sous « On calcule sur tes données ».

    python3 tools/build_seance.py

La section affirme qu'on part des données du coureur. Encore faut-il les
montrer. Ce dessin reprend la mise en page d'un analyseur de séances — une
colonne par tour, les pistes empilées dessous — dans la typographie et les
couleurs du site.

Deux tentatives ont précédé celle-ci, et leur défaut était le même : les tours
étaient reconstruits à partir des changements d'allure, donc faux. Une montre
enregistre ses propres tours ; ce sont eux qui font foi, et ils viennent
maintenant du fichier FIT. Pour cette séance de 4 × 2 km, les vingt-trois tours
correspondent exactement à ce que la montre affiche.

La source est tools/test/seance.json, produit par tools/extract_seance.py
depuis un fichier FIT réel, dépouillé de sa date et de sa trace.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SRC = RACINE / "tools" / "test" / "seance.json"
PAGE = RACINE / "index.html"
DEBUT = "<!-- SEANCE:DEBUT (écrit par tools/build_seance.py) -->"
FIN = "<!-- SEANCE:FIN -->"

W = 1000
G, D = 54, 8                      # marges gauche (noms de pistes) et droite
ENTETE = 42                       # bandeau des tours : allure puis cardio
# Une piste par mesure. La hauteur dit l'importance : l'allure et le cardio
# portent la séance, la cadence et le relief l'expliquent.
PISTES = (("allure", "Allure", 58, "v"),
          ("fc", "Cardio", 52, "h"),
          ("cadence", "Cadence", 34, "c"),
          ("alt", "Relief", 26, "a"))
ECART = 7
H = ENTETE + sum(p[2] for p in PISTES) + ECART * len(PISTES) + 16

IDX = {"allure": 1, "fc": 2, "cadence": 3, "alt": 4}


def mmss(s):
    return f"{int(s) // 60}:{int(s) % 60:02d}"


def piste(nom, blocs, x, y0, hauteur):
    """L'aire sous la courbe, puis la courbe.

    Les vitesses sont en km/h : un effort rapide monte donc naturellement,
    sans inversion d'axe.
    """
    i = IDX[nom]
    vals = [(b[0], b[i]) for b in blocs if b[i] is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(v for _, v in vals), max(v for _, v in vals)
    if hi == lo:
        hi = lo + 1
    m = (hi - lo) * 0.12
    lo, hi = lo - m, hi + m

    def y(v):
        return y0 + hauteur - (v - lo) / (hi - lo) * hauteur

    # Les trous — cadence absente à l'arrêt — coupent la courbe au lieu de la
    # faire plonger vers zéro.
    bouts, cour = [], []
    precedent = None
    for t, v in vals:
        if precedent is not None and t - precedent > 30:
            bouts.append(cour)
            cour = []
        cour.append((t, v))
        precedent = t
    bouts.append(cour)

    sortie = []
    for bout in bouts:
        if len(bout) < 2:
            continue
        trace = " ".join(f"{'M' if k == 0 else 'L'}{x(t):.1f} {y(v):.1f}"
                         for k, (t, v) in enumerate(bout))
        aire = (f"M{x(bout[0][0]):.1f} {y0 + hauteur:.1f} " + trace[1:]
                + f" L{x(bout[-1][0]):.1f} {y0 + hauteur:.1f} Z")
        sortie.append(f'<path class="sq-aire sq-{nom}" d="{aire}"/>'
                      f'<path class="sq-trait sq-{nom}" d="{trace}"/>')
    return "".join(sortie)


def main() -> int:
    if not SRC.is_file():
        print(f"Séance introuvable : {SRC}", file=sys.stderr)
        return 1
    s = json.loads(SRC.read_text(encoding="utf-8"))
    page = PAGE.read_text(encoding="utf-8")
    if DEBUT not in page or FIN not in page:
        print("Les marqueurs SEANCE sont absents d'index.html.", file=sys.stderr)
        return 1

    blocs, laps, duree = s["blocs"], s["laps"], s["duree_s"]

    def x(t):
        return G + t / duree * (W - G - D)

    # Un tour enregistré d'une seconde est un appui sur le bouton, pas un
    # effort : il n'a ni colonne ni libellé.
    colonnes, etiquettes = [], []
    for lp in laps:
        if lp["duree"] < 5:
            continue
        x0, x1 = x(lp["debut"]), x(lp["debut"] + lp["duree"])
        large = x1 - x0
        colonnes.append(f'<line x1="{x1:.1f}" x2="{x1:.1f}" y1="0" y2="{H - 16:.1f}" '
                        f'class="sq-sep"/>')
        if large < 30:                 # pas la place d'écrire sans déborder
            continue
        cx = (x0 + x1) / 2
        allure = f"{mmss(lp['allure'])}" if lp.get("allure") else "—"
        etiquettes.append(
            f'<text x="{cx:.1f}" y="15" text-anchor="middle" class="sq-a">{allure}</text>'
            + (f'<text x="{cx:.1f}" y="29" text-anchor="middle" class="sq-f">{lp["fc"]}</text>'
               if lp.get("fc") else ""))

    y = ENTETE
    dessins, noms = [], []
    for nom, titre, hauteur, _ in PISTES:
        dessins.append(piste(nom, blocs, x, y, hauteur))
        noms.append(f'<text x="{G - 8}" y="{y + hauteur / 2 + 3:.1f}" text-anchor="end" '
                    f'class="sq-l">{titre}</text>')
        y += hauteur + ECART

    minutes = "".join(
        f'<text x="{x(m * 60):.1f}" y="{H - 3}" text-anchor="middle" class="sq-t">{m}′</text>'
        for m in range(0, duree // 60 + 1, 15))

    svg = f'''<svg viewBox="0 0 {W} {H}" class="sq-svg" role="img"
     aria-label="Une séance de {duree // 60} minutes et {s['km']} kilomètres : allure, fréquence cardiaque, cadence et relief, découpés en {len(laps)} tours enregistrés par la montre">
  {"".join(colonnes)}
  <line x1="{G}" x2="{W - D}" y1="{ENTETE - 4}" y2="{ENTETE - 4}" class="sq-sol"/>
  {"".join(etiquettes)}{"".join(dessins)}{"".join(noms)}{minutes}
</svg>'''

    rapides = sorted((l for l in laps if l.get("allure") and l["dist"] > 500),
                     key=lambda l: l["allure"])[:4]
    cads = [b[3] for b in blocs if b[3]]
    fc_max = max((l["fc"] for l in laps if l.get("fc")), default=0)

    bloc = f"""{DEBUT}
      <figure class="sq reveal">
        <figcaption class="sq-tete">
          <span class="sq-quoi">Une vraie séance, telle que la montre l'a enregistrée</span>
          <span class="sq-meta mono">{duree // 60} min · {s['km']} km · {len([l for l in laps if l['duree'] >= 5])} tours</span>
        </figcaption>
        {svg}
        <figcaption class="sq-pied">
          <span class="sq-e"><i class="sq-sw sq-allure"></i>allure</span>
          <span class="sq-e"><i class="sq-sw sq-fc"></i>cardio</span>
          <span class="sq-e"><i class="sq-sw sq-cadence"></i>cadence</span>
          <span class="sq-e"><i class="sq-sw sq-alt"></i>relief</span>
          <span class="sq-note">Quatre kilomètres rapides à
            {", ".join(mmss(l["allure"]) for l in rapides)}/km, jusqu'à {fc_max} battements,
            à {round(sum(cads) / len(cads))} pas par minute. Chaque colonne est un tour
            de la montre — les chiffres du haut sont son allure et son cardio moyens.</span>
        </figcaption>
      </figure>
      {FIN}"""

    avant, reste = page.split(DEBUT, 1)
    _, apres = reste.split(FIN, 1)
    PAGE.write_text(avant + bloc + apres, encoding="utf-8")
    labels = len(etiquettes)
    print(f"  séance écrite · {duree // 60} min · {len(laps)} tours dont {labels} étiquetés · "
          f"cadre {W}×{H}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
