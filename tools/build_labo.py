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
import transition as T

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


def courbe(pts, x, y, base, classe, points=True, aire=True):
    """L'aire puis le trait. Une aire pleine se voit de loin, un trait seul non.

    Deux aires superposées se masqueraient l'une l'autre : quand il y a deux
    courbes, seule la première en reçoit une.
    """
    trace = " ".join(f"{'M' if i == 0 else 'L'}{x(a):.1f} {y(bb):.1f}"
                     for i, (a, bb) in enumerate(pts))
    fond = ""
    if aire and base is not None:
        d = (f"M{x(pts[0][0]):.1f} {base:.1f} " + trace[1:]
             + f" L{x(pts[-1][0]):.1f} {base:.1f} Z")
        fond = f'<path class="lb-a {classe}" d="{d}"/>'
    ronds = "".join(f'<circle class="lb-pt {classe}" cx="{x(a):.1f}" cy="{y(bb):.1f}" r="4"/>'
                    for a, bb in pts) if points else ""
    return f'{fond}<path class="lb-l {classe}" d="{trace}"/>{ronds}'


def etiquette(xv, yv, texte, classe="", ancre="start", dx=10, dy=5):
    return (f'<text class="lb-val {classe}" x="{xv + dx:.1f}" y="{yv + dy:.1f}" '
            f'text-anchor="{ancre}">{texte}</text>')


def svg_transition(r):
    """La part marchée selon la pente, et la courbe qui la résume.

    Chaque point est une tranche d'un point de pente ; sa taille dit combien de
    blocs elle contient, son trait vertical l'intervalle de sa proportion. Un
    point posé sur sept blocs ne pèse pas comme un point posé sur deux mille,
    et le dessin doit le montrer au lieu de les aligner à égalité.
    """
    h = 186
    H = HAUT + h + 34
    x0, x1 = 0.0, 16.0

    def x(v):
        return G + (v - x0) / (x1 - x0) * (W - G - DR)

    def y(p):
        return HAUT + h - p * h

    bande = (f'<rect class="lb-ic" x="{x(r["lo"]):.1f}" y="{HAUT}" '
             f'width="{x(r["hi"]) - x(r["lo"]):.1f}" height="{h}"/>')
    trace = " ".join(f"{'M' if i == 0 else 'L'}{x(v):.1f} {y(T.courbe(r['p'], v)):.1f}"
                     for i, v in enumerate([k / 5 for k in range(int(x1 * 5) + 1)]))
    points = []
    for v, n, w in r["tranches"]:
        if v > x1 or n < 5:
            continue
        lo, hi = T.wilson(n, w)
        rayon = min(9.0, 2.6 + n ** .5 / 6)
        points.append(f'<line class="lb-barre" x1="{x(v):.1f}" x2="{x(v):.1f}" '
                      f'y1="{y(lo):.1f}" y2="{y(hi):.1f}"/>'
                      f'<circle class="lb-obs" cx="{x(v):.1f}" cy="{y(w / n):.1f}" r="{rayon:.1f}"/>')
    pct = "".join(f'<text class="lb-ax" x="{G - 8}" y="{y(p) + 4:.1f}" text-anchor="end">'
                  f'{int(p * 100)} %</text>'
                  f'<line class="lb-gr" x1="{G}" x2="{W - DR}" y1="{y(p):.1f}" y2="{y(p):.1f}"/>'
                  for p in (0, .25, .5, .75, 1))
    return f'''<svg viewBox="0 0 {W} {H}" class="lb" role="img" aria-label="\
Part des blocs marchés selon la pente. La courbe franchit 50 % à {fr(r["x50"])} % \
de pente, intervalle de {fr(r["lo"])} à {fr(r["hi"])}.">
  {bande}{pct}
  <line class="lb-seuil" x1="{G}" x2="{W - DR}" y1="{y(.5):.1f}" y2="{y(.5):.1f}"/>
  {"".join(points)}
  <path class="lb-l lb-v" d="{trace}"/>
  <circle class="lb-pivot" cx="{x(r["x50"]):.1f}" cy="{y(.5):.1f}" r="6.5"/>
  {etiquette(x(r["x50"]), y(.5), f"{fr(r['x50'])} %", "lb-cle", "start", 14, 30)}
  <text class="lb-t" x="{G}" y="{HAUT - 8}">part des blocs sous {fr(T.SEUIL, 0)} pas/min</text>
  {axe_x(x, [0, 4, 8, 12, 16], H - 10, " %")}
</svg>'''


def svg_duree(du, r):
    """La transition heure après heure, et l'endroit où la mesure s'arrête.

    La bande est l'intervalle de la transition elle-même, déplacé avec elle :
    c'est lui, et non la dérive, qui borne ce qu'on sait. Au-delà de la durée
    sur laquelle la dérive a été mesurée, le tracé passe en pointillé sur un
    fond hachuré : on y voit ce que donnerait la règle, pas ce qu'on a mesuré.
    """
    h = 186
    H = HAUT + h + 34
    pts = du["pts"]
    t1 = pts[-1]["h"]
    bas = r["x50"] - r["lo"]
    haut = r["hi"] - r["x50"]
    lo, hi, ty = echelle([p["par_h"] - bas for p in pts] + [p["par_h"] + haut for p in pts], 3)

    def x(t):
        return G + t / t1 * (W - G - DR)

    def y(v):
        return HAUT + h - (v - lo) / (hi - lo) * h

    bande = ("M" + " L".join(f"{x(p['h']):.1f} {y(p['par_h'] + haut):.1f}" for p in pts)
             + " L" + " L".join(f"{x(p['h']):.1f} {y(p['par_h'] - bas):.1f}" for p in reversed(pts))
             + " Z")
    mes = [p for p in pts if p["mesure"]]
    hors = [mes[-1]] + [p for p in pts if not p["mesure"]]
    ligne = lambda ps: " ".join(f"{'M' if i == 0 else 'L'}{x(p['h']):.1f} {y(p['par_h']):.1f}"
                                for i, p in enumerate(ps))
    tm = du["tmax"]
    return f'''<svg viewBox="0 0 {W} {H}" class="lb" role="img" aria-label="\
La transition reste entre {fr(min(p["par_h"] for p in mes))} et \
{fr(max(p["par_h"] for p in mes))} % de pente sur la durée mesurée.">
  <defs><pattern id="lbHach" width="7" height="7" patternUnits="userSpaceOnUse" \
patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="7" class="lb-hach"/></pattern></defs>
  <rect x="{x(tm):.1f}" y="{HAUT}" width="{x(t1) - x(tm):.1f}" height="{h}" fill="url(#lbHach)"/>
  {axe_y(y, ty, " %")}
  <path class="lb-cone" d="{bande}"/>
  <path class="lb-l lb-v" d="{ligne(mes)}"/>
  <path class="lb-l lb-v lb-pt-hors" d="{ligne(hors)}"/>
  <circle class="lb-pivot" cx="{x(0):.1f}" cy="{y(pts[0]["par_h"]):.1f}" r="6.5"/>
  {etiquette(x(0), y(pts[0]["par_h"]), f"{fr(pts[0]['par_h'])} %", "lb-cle", "start", 14, -14)}
  <text class="lb-t lb-hors-t" x="{x(tm) + 10:.1f}" y="{HAUT + 16}">au-delà, pas de mesure</text>
  <text class="lb-t" x="{G}" y="{HAUT - 8}">pente de la transition · %</text>
  {axe_x(x, [0, 1, 2, 3], H - 10, " h")}
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
    r, du, f = T.a_transition(b), T.a_duree(b, 3.0), L.a_fatigue(b)
    if not (r and du and f):
        print("Analyse impossible sur ces séances.", file=sys.stderr)
        return 1
    mes = [p for p in du["pts"] if p["mesure"]]
    dv = du["derive"]
    tm = du["tmax"]
    tm_txt = f"{int(tm)} h {round((tm % 1) * 60):02d}" if tm >= 1 else f"{round(tm * 60)} min"
    seances = len({x["seance"] for x in b})

    blocs = [
      panneau("p-trans", "tab-trans", "La transition course-marche",
              f"{fr(r['x50'])} %",
              f"Sous {fr(T.SEUIL, 0)} pas par minute, un bloc de 15 secondes compte "
              f"comme marché. Rangée par point de pente, la part marchée suit une "
              f"courbe en S, et une régression logistique la place à {fr(r['x50'])} % : "
              f"au-dessus, il marche plus souvent qu'il ne court. L'intervalle va de "
              f"{fr(r['lo'])} à {fr(r['hi'])} %.",
              svg_transition(r),
              f"{milliers(r['n'])} blocs sur {r['seances']} séances · la montée vient "
              f"de {r['seances_raides']} sorties de trail : avec davantage de terrain, "
              f"l'intervalle se resserrera · logistique à "
              f"quatre paramètres, écart au plus de {fr(r['ecart_max'] * 100, 0)} points "
              f"aux tranches garnies · intervalle à 95 % par rééchantillonnage de "
              f"blocs de cinq minutes",
              premier=True),
      panneau("p-duree", "tab-duree", "Ce que la durée fait à la transition",
              f"{fr(mes[0]['par_h'])} → {fr(mes[-1]['par_h'])} %",
              f"Sa cadence perd {fr(-dv['par_h'], 1)} pas par minute chaque heure, à "
              f"pente égale. Reportée sur la courbe, cette perte déplace la transition "
              f"de moins d'un dixième de point en {tm_txt} : c'est sous la précision "
              f"de la mesure. Les séances courues à allure tenue s'arrêtent là, et "
              f"au-delà on ne donne pas de chiffre.",
              svg_duree(du, r),
              f"dérive de cadence {fr(dv['par_h'], 2)} pas/min par heure "
              f"[{fr(dv['lo'], 2)} ; {fr(dv['hi'], 2)}] sur {dv['seances']} séances "
              f"à allure tenue, la plus longue de {tm_txt} · la bande est "
              f"l'intervalle de la transition"),
      panneau("p-coeur", "tab-coeur", "La dérive cardiaque",
              f"+{fr(f['bpm_h'])} bpm/h",
              f"À vitesse et pente égales, son cœur monte de {fr(f['bpm_h'])} "
              f"battements par heure, entre {fr(f['lo'])} et {fr(f['hi'])}. Mesurée "
              f"à l'intérieur de chaque séance, elle ne dépend pas de la montre : "
              f"deux appareils qui ne s'accordent pas sur la fréquence s'accordent "
              f"sur sa variation.",
              svg_fatigue(f),
              f"{milliers(f['n'])} blocs sur {f['seances']} séances courues à "
              f"allure tenue, pente entre −3 et 3 %, échauffement écarté · "
              f"intervalle à 95 % par rééchantillonnage des séances"),
    ]

    bloc = DEBUT + "".join(blocs) + "\n  " + FIN
    page = PAGE.read_text(encoding="utf-8")
    if DEBUT not in page or FIN not in page:
        print("Les marqueurs LABO sont absents d'index.html.", file=sys.stderr)
        return 1
    avant, reste = page.split(DEBUT, 1)
    _, apres = reste.split(FIN, 1)
    PAGE.write_text(avant + bloc + apres, encoding="utf-8")
    print(f"  labo écrit · {milliers(len(b))} blocs · {seances} séances")
    print(f"    transition {fr(r['x50'])} % [{fr(r['lo'])} ; {fr(r['hi'])}]")
    print(f"    durée      {fr(mes[0]['par_h'])} → {fr(mes[-1]['par_h'])} % sur {tm_txt}")
    print(f"    coeur      {fr(f['bpm_h'])} bpm/h [{fr(f['lo'])} ; {fr(f['hi'])}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
