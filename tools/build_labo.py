#!/usr/bin/env python3
"""Dessine les trois analyses du laboratoire dans index.html.

    python3 tools/build_labo.py ~/Documents/HOLD/i252597_fit_files-3
    python3 tools/build_labo.py            # repart du cache

Les chiffres viennent de tools/labo_calc.py, qui lit les .fit. Rien n'est
écrit à la main ici : si une séance s'ajoute, les trois panneaux changent.

Les graphiques sont des SVG figés, sans curseur. Un curseur demandait au
visiteur de chercher lui-même le résultat ; un graphique le montre.
"""
from __future__ import annotations

import html
import math
import sys
from statistics import fmean as st_moyenne
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labo_calc as L

RACINE = Path(__file__).resolve().parent.parent
PAGE = RACINE / "index.html"
DEBUT = "<!-- LABO:DEBUT (écrit par tools/build_labo.py) -->"
FIN = "<!-- LABO:FIN -->"

W = 560
G, DR, HAUT = 52, 58, 24           # marges gauche, droite, haut


def fr(v, d=1):
    return f"{v:.{d}f}".replace(".", ",").replace("-", "−")


def milliers(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def echelle(valeurs, span_min):
    """Un domaine qui contient tout, avec des graduations rondes.

    Les bornes étaient écrites en dur. Elles suffisaient aux données du jour,
    et auraient laissé un point hors du cadre dès la première séance de trail.
    L'amplitude minimale, elle, reste : zoomer sur une courbe plate la rendrait
    ondulante, et c'est précisément sa platitude qu'on veut montrer.
    """
    lo, hi = min(valeurs), max(valeurs)
    marge = max((hi - lo) * 0.08, span_min * 0.05)
    for pas in (1, 2, 5, 10, 20, 50, 100):
        a = math.floor((lo - marge) / pas) * pas
        z = math.ceil((hi + marge) / pas) * pas
        while z - a < span_min:          # on élargit par pas entiers, des deux côtés
            a -= pas
            if z - a < span_min:
                z += pas
        if (z - a) / pas <= 5:          # au-delà, l'axe devient une trame
            return a, z, [a + i * pas for i in range(int(round((z - a) / pas)) + 1)]
    return lo, hi, [lo, hi]


def axe_x(x, valeurs, y, suffixe=""):
    return "".join(
        f'<text class="lb-ax" x="{x(v):.1f}" y="{y}" text-anchor="middle">'
        f'{fr(v, 0)}{suffixe}</text>' for v in valeurs)


def axe_y(y, valeurs, suffixe=""):
    return "".join(
        f'<text class="lb-ax" x="{G - 8}" y="{y(v) + 4:.1f}" text-anchor="end">'
        f'{fr(v, 0)}{suffixe}</text>'
        f'<line class="lb-gr" x1="{G}" x2="{W - DR}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
        for v in valeurs)


def courbe(pts, x, y, base, classe, points=True):
    """L'aire puis le trait. Une aire pleine se voit de loin, un trait seul non."""
    trace = " ".join(f"{'M' if i == 0 else 'L'}{x(a):.1f} {y(bb):.1f}"
                     for i, (a, bb) in enumerate(pts))
    aire = (f"M{x(pts[0][0]):.1f} {base:.1f} " + trace[1:]
            + f" L{x(pts[-1][0]):.1f} {base:.1f} Z")
    ronds = "".join(f'<circle class="lb-pt {classe}" cx="{x(a):.1f}" cy="{y(bb):.1f}" r="4"/>'
                    for a, bb in pts) if points else ""
    return (f'<path class="lb-a {classe}" d="{aire}"/>'
            f'<path class="lb-l {classe}" d="{trace}"/>{ronds}')


def etiquette(xv, yv, texte, classe="", ancre="start", dx=10, dy=5):
    return (f'<text class="lb-val {classe}" x="{xv + dx:.1f}" y="{yv + dy:.1f}" '
            f'text-anchor="{ancre}">{texte}</text>')


def svg_pente(p):
    """Deux pistes sur le même axe de pente : la vitesse, puis la cadence.

    Deux échelles dans un seul cadre cacheraient le résultat au lieu de le
    montrer. Empilées, elles le disent d'un coup d'œil : l'une plonge, l'autre
    ne bouge pas. Les deux valeurs extrêmes sont écrites sur le dessin —
    chercher un chiffre en remontant à l'axe, personne ne le fait.
    """
    h1, h2, ecart = 132, 96, 48
    H = HAUT + h1 + ecart + h2 + 34
    x0, x1 = p[0]["lo"], p[-1]["hi"]

    def x(v):
        return G + (v - x0) / (x1 - x0) * (W - G - DR)

    vlo, vhi, tv = echelle([q["v"] for q in p], 6)
    clo, chi, tc = echelle([q["cad"] for q in p], 25)

    def y1(v):
        return HAUT + h1 - (v - vlo) / (vhi - vlo) * h1

    def y2(v):
        return HAUT + h1 + ecart + h2 - (v - clo) / (chi - clo) * h2

    cmin, cmax = min(q["cad"] for q in p), max(q["cad"] for q in p)
    haut = max(p, key=lambda q: q["v"])
    bande = (f'<rect class="lb-bande" x="{G}" y="{y2(cmax):.1f}" width="{W - G - DR}" '
             f'height="{y2(cmin) - y2(cmax):.1f}"/>')
    return f'''<svg viewBox="0 0 {W} {H}" class="lb" role="img" aria-label="\
Vitesse et cadence selon la pente : la vitesse tombe de {fr(max(q["v"] for q in p))} \
à {fr(p[-1]["v"])} kilomètres par heure, la cadence reste entre {fr(cmin, 0)} et \
{fr(cmax, 0)} pas par minute.">
  {axe_y(y1, tv)}
  {courbe([(q["x"], q["v"]) for q in p], x, y1, HAUT + h1, "lb-v")}
  {etiquette(x(p[-1]["x"]), y1(p[-1]["v"]), fr(p[-1]["v"]), "lb-v")}
  {etiquette(x(haut["x"]), y1(haut["v"]), fr(haut["v"]), "lb-v", "middle", 0, -13)}
  <text class="lb-t" x="{G}" y="{HAUT - 6}">vitesse · km/h</text>
  {bande}{axe_y(y2, tc)}
  {courbe([(q["x"], q["cad"]) for q in p], x, y2, HAUT + h1 + ecart + h2, "lb-c")}
  {etiquette(x(p[-1]["x"]), y2(p[-1]["cad"]), f"{fr(cmin, 0)}–{fr(cmax, 0)}", "lb-c")}
  <text class="lb-t" x="{G}" y="{HAUT + h1 + ecart - 14}">cadence · pas/min</text>
  <line class="lb-zero" x1="{x(0):.1f}" x2="{x(0):.1f}" y1="{HAUT}" y2="{HAUT + h1 + ecart + h2:.1f}"/>
  {axe_x(x, [-10, -5, 0, 5, 10], H - 10, " %")}
</svg>'''


def svg_fatigue(f):
    h = 158
    H = HAUT + h + 34
    pts = f["pts"]
    x0, x1 = 0, max(q["x"] for q in pts) + 12
    ligne = lambda t: f["bpm_h"] / 60 * (t - f["t_moy"])
    t2 = f["t_dense"]
    lo, hi, ty = echelle([q["y"] for q in pts] + [ligne(0), ligne(t2)], 12)

    def x(v):
        return G + (v - x0) / (x1 - x0) * (W - G - DR)

    def y(v):
        return HAUT + h - (v - lo) / (hi - lo) * h

    # La droite s'arrête où les séances cessent d'être nombreuses : la
    # prolonger sur trois sorties en ferait une promesse.
    droite = (f'<line class="lb-fit" x1="{x(0):.1f}" y1="{y(ligne(0)):.1f}" '
              f'x2="{x(t2):.1f}" y2="{y(ligne(t2)):.1f}"/>')
    return f'''<svg viewBox="0 0 {W} {H}" class="lb" role="img" aria-label="\
Écart de fréquence cardiaque à vitesse égale selon le temps écoulé : la dérive \
vaut {fr(f["bpm_h"])} battement par heure.">
  {axe_y(y, ty)}
  <line class="lb-base" x1="{G}" x2="{W - DR}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>
  {courbe([(q["x"], q["y"]) for q in pts], x, y, y(0), "lb-v")}
  {droite}{etiquette(x(t2), y(ligne(t2)), f"+{fr(f['bpm_h'])} bpm/h", "lb-fit-t", "end", -8, -10)}
  <text class="lb-t" x="{G}" y="{HAUT - 6}">écart de FC · battements</text>
  {axe_x(x, [0, 30, 60, 90, 120, 150], H - 10, "′")}
</svg>'''


def svg_chaleur(c):
    h = 158
    H = HAUT + h + 34
    pts = c["pts"]
    x0 = min(q["x"] for q in pts) - 1
    x1 = max(q["x"] for q in pts) + 1
    a, pente = c["droite"]
    lo, hi, ty = echelle([q["y"] for q in pts] + [a + pente * x0, a + pente * x1], 20)

    def x(v):
        return G + (v - x0) / (x1 - x0) * (W - G - DR)

    def y(v):
        return HAUT + h - (v - lo) / (hi - lo) * h

    # L'incertitude dessinée plutôt qu'écrite : le cône que tracent les deux
    # pentes extrêmes de l'intervalle, pivotant sur le centre du nuage.
    cx = st_moyenne([q["x"] for q in pts])
    cy = a + pente * cx
    cone = " ".join([f"M{x(x0):.1f} {y(cy + c['lo'] * (x0 - cx)):.1f}",
                     f"L{x(x1):.1f} {y(cy + c['lo'] * (x1 - cx)):.1f}",
                     f"L{x(x1):.1f} {y(cy + c['hi'] * (x1 - cx)):.1f}",
                     f"L{x(x0):.1f} {y(cy + c['hi'] * (x0 - cx)):.1f} Z"])
    ronds = "".join(f'<circle class="lb-nuage" cx="{x(q["x"]):.1f}" '
                    f'cy="{y(q["y"]):.1f}" r="5"/>' for q in pts)
    return f'''<svg viewBox="0 0 {W} {H}" class="lb" role="img" aria-label="\
Une sortie par point : la fréquence cardiaque à allure égale monte de \
{fr(c["bpm_c"], 2)} battement par degré.">
  {axe_y(y, ty)}
  <path class="lb-cone" d="{cone}"/>
  {ronds}
  <line class="lb-fit lb-plein" x1="{x(x0):.1f}" y1="{y(a + pente * x0):.1f}" x2="{x(x1):.1f}" y2="{y(a + pente * x1):.1f}"/>
  {etiquette(x(x1), y(a + pente * x1), f"+{fr(c['bpm_c'], 2)} bpm/°C", "lb-fit-t", "end", -4, -12)}
  <text class="lb-t" x="{G}" y="{HAUT - 6}">FC à {fr(L.V0)} km/h · battements</text>
  {axe_x(x, [15, 20, 25], H - 10, " °C")}
</svg>'''


def panneau(ident, onglet, titre, gros, lecture, svg, source, premier=False):
    return f'''
  <div class="lab-panel" role="tabpanel" id="{ident}" aria-labelledby="{onglet}"{"" if premier else " hidden"}>
    <div class="lab-text">
      <h4>{titre}</h4>
      <p class="lab-big">{gros}</p>
      <p class="lab-sens">{lecture}</p>
      <p class="lab-src mono">{source}</p>
    </div>
    <div class="lab-chart">{svg}</div>
  </div>'''


def main() -> int:
    src = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    b = L.charger(src)
    p, f, c = L.a_pente(b), L.a_fatigue(b), L.a_chaleur(b)
    if not (p and f and c):
        print("Analyse impossible sur ces fichiers.", file=sys.stderr)
        return 1
    heures = len(b) * L.PAS / 3600
    seances = len({x["seance"] for x in b})

    vmax = max(q["v"] for q in p)
    perte = (1 - p[-1]["v"] / vmax) * 100
    cmin, cmax = min(q["cad"] for q in p), max(q["cad"] for q in p)

    blocs = [
      panneau("p-pente", "tab-pente", "Ce que la pente prend",
              f"−{fr(perte, 0)} %",
              f"De plat à {fr(p[-1]['lo'], 0)} %, ta vitesse perd {fr(perte, 0)} %. "
              f"Ta cadence, elle, ne bouge pas : elle reste entre {fr(cmin, 0)} et "
              f"{fr(cmax, 0)} pas par minute sur toute la plage. La pente ne se paie "
              f"pas en fréquence de pas, elle se paie en longueur de foulée.",
              svg_pente(p),
              f"{milliers(len(b))} blocs de {L.PAS} s · {seances} séances · "
              f"{fr(heures, 0)} h · pente lissée sur 50 m",
              premier=True),
      panneau("p-fatigue", "tab-fatigue", "Ce que les heures prennent",
              f"+{fr(f['bpm_h'])} bpm/h",
              f"À vitesse égale, ton cœur monte de {fr(f['bpm_h'])} battements par "
              f"heure de course. L'intervalle va de {fr(f['lo'])} à {fr(f['hi'])}. "
              f"C'est ce qui fait qu'une allure tenue au kilomètre 10 ne l'est plus "
              f"au kilomètre 30, sans que rien n'ait changé dehors.",
              svg_fatigue(f),
              f"{milliers(f['n'])} blocs sur {f['seances']} séances, pente entre "
              f"−3 et 3 % · mesuré à l'intérieur de chaque séance · intervalle à "
              f"95 % par rééchantillonnage des séances"),
      panneau("p-chaleur", "tab-chaleur", "Ce que la chaleur prend",
              f"+{fr(c['bpm_c'], 2)} bpm/°C",
              f"Chaque degré de plus coûte {fr(c['bpm_c'], 2)} battement à allure "
              f"égale, soit {fr(c['bpm_c'] * 10)} battements pour dix degrés. "
              f"L'intervalle va de {fr(c['lo'], 2)} à {fr(c['hi'], 2)} : l'effet est "
              f"là, sa taille exacte reste approximative.",
              svg_chaleur(c),
              f"{c['seances']} séances comparées entre elles, de "
              f"{fr(min(q['x'] for q in c['pts']))} à {fr(max(q['x'] for q in c['pts']))} °C · "
              f"FC ramenée à {fr(L.V0)} km/h · tendance de forme retirée"),
    ]

    bloc = DEBUT + "".join(blocs) + "\n  " + FIN
    page = PAGE.read_text(encoding="utf-8")
    if DEBUT not in page or FIN not in page:
        print("Les marqueurs LABO sont absents d'index.html.", file=sys.stderr)
        return 1
    avant, reste = page.split(DEBUT, 1)
    _, apres = reste.split(FIN, 1)
    PAGE.write_text(avant + bloc + apres, encoding="utf-8")
    print(f"  labo écrit · {len(b)} blocs · {seances} séances · {fr(heures, 0)} h")
    print(f"    pente    vitesse {fr(vmax)} → {fr(p[-1]['v'])} km/h, "
          f"cadence {fr(cmin, 0)}–{fr(cmax, 0)} pas/min")
    print(f"    fatigue  {fr(f['bpm_h'])} bpm/h [{fr(f['lo'])} ; {fr(f['hi'])}]")
    print(f"    chaleur  {fr(c['bpm_c'], 2)} bpm/°C [{fr(c['lo'], 2)} ; {fr(c['hi'], 2)}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
