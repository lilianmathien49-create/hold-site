#!/usr/bin/env python3
"""Dessine la progression de Clément sous « Ils nous ont fait confiance ».

    python3 tools/build_progression.py

La section racontait la chose en deux paragraphes. Personne n'arrive sur une
page de coaching pour lire deux paragraphes : on y cherche un chiffre, et on y
cherche à qui se fier. Donc un tableau pour les faits, un schéma pour
l'argument, les captures pour la preuve, et plus de prose.

L'argument tient en une soustraction. À partir de son 10 km, la formule de
Riegel — celle que tous les calculateurs d'allure appliquent — situait son
marathon à 3 h 32. Il en a couru trente-trois de moins. Le schéma pose cet
écart sur un axe de temps d'arrivée, où « plus vite » est « plus à gauche ».

Le schéma est en HTML et non en SVG, et c'est volontaire. Un SVG en largeur
fluide réduit son texte avec lui : les légendes en capitales, lisibles à
760 px, tombent sous les cinq pixels sur un téléphone. Ici les chiffres sont
du texte de la page, positionnés en pourcentage ; ils gardent leur taille à
toute largeur, et un lecteur d'écran les lit dans l'ordre sans qu'on ait à
lui rédiger une description séparée.

Les chronos, allures et distances sont ceux publiés sur Strava, distance GPS
comprise ; la prédiction, elle, part du 10 km officiel.
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PAGE = RACINE / "index.html"
DEBUT = "<!-- PROGRESSION:DEBUT (écrit par tools/build_progression.py) -->"
FIN = "<!-- PROGRESSION:FIN -->"

# Les deux courses, telles que Strava les affiche.
DIX = {"date": "14 août 2025", "nom": "10 km de La Marinade",
       "chrono": "46:06", "allure": "4:35", "km": "10,05 km"}
MAR = {"date": "12 avril 2026", "nom": "Marathon de Paris",
       "chrono": "2 h 59", "allure": "4:13", "km": "42,55 km"}

DIX_S = 46 * 60 + 6          # le 10 km officiel, point de départ de la formule
MAR_MIN = 179.0              # 2 h 59
RIEGEL = 1.06                # l'exposant d'origine, celui des calculateurs

MARGE = 8.0                  # % de vide de chaque côté de l'axe
AVANT, APRES = 9.0, 13.0     # minutes d'axe avant le premier point, après le second


def riegel(t_s: float, d1: float, d2: float) -> float:
    return t_s * (d2 / d1) ** RIEGEL


def hhmm(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60} h {m % 60:02d}"


def main() -> int:
    page = PAGE.read_text(encoding="utf-8")
    if DEBUT not in page or FIN not in page:
        print("Les marqueurs PROGRESSION sont absents d'index.html.", file=sys.stderr)
        return 1

    prevu = riegel(DIX_S, 10.0, 42.195) / 60
    gain = prevu - MAR_MIN

    lo, hi = MAR_MIN - AVANT, prevu + APRES

    def pct(t):
        return MARGE + (t - lo) / (hi - lo) * (100 - 2 * MARGE)

    a, b = pct(MAR_MIN), pct(prevu)

    def colonne(c):
        return (f'<td><span class="pg-c">{html.escape(c["chrono"])}</span>'
                f'<span class="pg-a mono">{html.escape(c["allure"])} /km'
                f' · {html.escape(c["km"])}</span></td>')

    tableau = f'''<table class="pg-t">
        <caption>Ses deux seules courses officielles, à huit mois d'intervalle.</caption>
        <thead>
          <tr><th scope="col"><em class="mono">{DIX["date"]}</em>{html.escape(DIX["nom"])}</th>
            <th scope="col"><em class="mono">{MAR["date"]}</em>{html.escape(MAR["nom"])}</th></tr>
        </thead>
        <tbody><tr>{colonne(DIX)}{colonne(MAR)}</tr></tbody>
      </table>'''

    schema = f'''<div class="pg-d" style="--a:{a:.2f}%;--b:{b:.2f}%;--m:{(a + b) / 2:.2f}%">
          <div class="pg-rail">
            <span class="pg-band" aria-hidden="true"></span>
            <i class="pg-stem pg-stem-a" aria-hidden="true"></i>
            <i class="pg-stem pg-stem-b" aria-hidden="true"></i>
            <i class="pg-dot pg-dot-a" aria-hidden="true"></i>
            <i class="pg-dot pg-dot-b" aria-hidden="true"></i>
            <p class="pg-m pg-m-a"><b>{MAR["chrono"]}</b><em class="mono">ce qu'il a couru</em></p>
            <p class="pg-m pg-m-b"><b>{hhmm(prevu)}</b><em class="mono">ce que la table prévoyait</em></p>
            <p class="pg-gain mono">{round(gain)} minutes de moins</p>
          </div>
        </div>'''

    bloc = f"""{DEBUT}
      {tableau}
      <figure class="pg-f">
        {schema}
        <figcaption>{hhmm(prevu)} : ce que la formule de Riegel — celle de tous les
          calculateurs d'allure — déduit de son 10 km, et ce qu'un plan générique
          lui aurait fait viser.</figcaption>
      </figure>
      {FIN}"""

    avant, reste = page.split(DEBUT, 1)
    _, apres = reste.split(FIN, 1)
    PAGE.write_text(avant + bloc + apres, encoding="utf-8")
    print(f"  progression écrite · prévu {hhmm(prevu)} · couru {MAR['chrono']} · "
          f"{round(gain)} min · points à {a:.1f} % et {b:.1f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
