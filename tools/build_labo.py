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


def foulee(p):
    """La longueur de foulée au plat : vitesse divisée par cadence."""
    q = next((x for x in p if x["lo"] == 0), p[len(p) // 2])
    return q["v"] / 3.6 / q["cad"] * 60


def svg_pente(courbes):
    """Deux coureurs, deux pistes, le même axe de pente.

    Une seule courbe disait que la cadence ne bouge pas. Deux courbes disent
    la même chose et une autre en plus : à cadence presque identique, les deux
    coureurs n'avancent pas à la même vitesse, parce que leur foulée n'a pas
    la même longueur. C'est l'argument du site en un dessin — une table
    générique donne un chiffre, la mesure donne le tien.
    """
    h1, h2, ecart = 132, 104, 50
    H = HAUT + h1 + ecart + h2 + 34
    tout = [q for _, p in courbes for q in p]
    x0 = min(q["lo"] for q in tout)
    x1 = max(q["hi"] for q in tout)

    def x(v):
        return G + (v - x0) / (x1 - x0) * (W - G - DR)

    vlo, vhi, tv = echelle([q["v"] for q in tout], 6)
    clo, chi, tc = echelle([q["cad"] for q in tout], 25)

    def y1(v):
        return HAUT + h1 - (v - vlo) / (vhi - vlo) * h1

    def y2(v):
        return HAUT + h1 + ecart + h2 - (v - clo) / (chi - clo) * h2

    vit, cad, noms = [], [], []
    for i, (nom, p) in enumerate(courbes):
        cl = f"lb-r{i}"
        vit.append(courbe([(q["x"], q["v"]) for q in p], x, y1, HAUT + h1, cl, aire=i == 0))
        cad.append(courbe([(q["x"], q["cad"]) for q in p], x, y2, None, cl))
        dernier = p[-1]
        vit.append(etiquette(x(dernier["x"]), y1(dernier["v"]), fr(dernier["v"]), cl))
        cad.append(etiquette(x(dernier["x"]), y2(dernier["cad"]), fr(dernier["cad"], 0), cl))
        noms.append(f'<text class="lb-nom {cl}" x="{G + i * 108}" y="{H - 10}">'
                    f'{html.escape(nom)}</text>')
    return f'''<svg viewBox="0 0 {W} {H}" class="lb" role="img" aria-label="\
Vitesse et cadence selon la pente, pour deux coureurs. Leurs cadences se \
superposent, leurs vitesses non.">
  {axe_y(y1, tv)}{"".join(vit)}
  <text class="lb-t" x="{G}" y="{HAUT - 6}">vitesse · km/h</text>
  {axe_y(y2, tc)}{"".join(cad)}
  <text class="lb-t" x="{G}" y="{HAUT + h1 + ecart - 14}">cadence · pas/min</text>
  <line class="lb-zero" x1="{x(0):.1f}" x2="{x(0):.1f}" y1="{HAUT}" y2="{HAUT + h1 + ecart + h2:.1f}"/>
  {axe_x(x, [-8, -4, 0, 4, 8], H - 34, " %")}
  {"".join(noms)}
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
    # Un dossier par coureur. Le premier porte toutes les analyses ; les
    # suivants ne servent qu'à la comparaison des pentes.
    args = [Path(a).expanduser() for a in sys.argv[1:]]
    b = L.charger(args[0] if args else None)
    p, f, c = L.a_pente(b), L.a_fatigue(b), L.a_chaleur(b)
    courbes = [(args[0].name.split("_")[0].title() if args else "Toi", p)]
    for autre in args[1:]:
        courbes.append((autre.name.title(), L.a_pente(L.charger(autre))))
    if not (p and f and c):
        print("Analyse impossible sur ces fichiers.", file=sys.stderr)
        return 1
    heures = len(b) * L.PAS / 3600
    seances = len({x["seance"] for x in b})

    vmax = max(q["v"] for q in p)
    perte = (1 - p[-1]["v"] / vmax) * 100
    cmin, cmax = min(q["cad"] for q in p), max(q["cad"] for q in p)
    foulees = [(nom, foulee(q)) for nom, q in courbes]

    blocs = [
      panneau("p-pente", "tab-pente",
              "Deux coureurs, la même pente" if len(courbes) > 1 else "Ce que la pente prend",
              " contre ".join(f"{fr(fo, 2)} m" for _, fo in foulees),
              ("Leurs cadences se superposent, à un ou deux pas par minute près, et "
               "ne bougent presque pas avec la pente. Leurs vitesses, elles, ne se "
               "touchent jamais : "
               + ", ".join(f"{html.escape(nom)} avance de {fr(fo, 2)} m à chaque pas"
                           for nom, fo in foulees)
               + ". Une table d'allures ne peut pas répondre à leur place : la pente "
                 "ne se paie pas en fréquence de pas, elle se paie en longueur de "
                 "foulée, et celle-là n'appartient qu'à soi."
               if len(foulees) > 1 else
               f"De plat à {fr(p[-1]['lo'], 0)} %, ta vitesse perd {fr(perte, 0)} %. "
               f"Ta cadence, elle, ne bouge pas : elle reste entre {fr(cmin, 0)} et "
               f"{fr(cmax, 0)} pas par minute sur toute la plage."),
              svg_pente(courbes),
              " · ".join(f"{html.escape(nom)} {milliers(sum(q['n'] for q in pts))} blocs"
                          for nom, pts in courbes)
              + f" de {L.PAS} s · pente lissée sur 50 m",
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
