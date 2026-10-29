#!/usr/bin/env python3
"""Fabrique l'aperçu du parcours affiché sur la page d'accueil.

    python3 tools/build_apercu.py

Quatre versions ont été nécessaires, et chaque reproche était juste.

1. Un graphique avec grille, axes et huit cases de chiffres : un rapport de
   laboratoire sur une page de vente.
2. Tout dépouillé, un seul instant montré : « on perd trop en précision ».
   En enlevant le bruit j'avais enlevé le produit.
3. La table de marche revenue et le relief peint par la pente — mais le SVG
   portait `preserveAspectRatio="none"`, qui étire le dessin à la largeur du
   conteneur. Le relief était écrasé, les libellés déformés. C'est ce bug qui
   rendait l'ensemble illisible.
4. Celle-ci : proportions respectées, les vingt-cinq ravitaillements nommés
   sans chevauchement, une échelle d'altitude lisible, une légende explicite,
   et la géométrie dont le curseur a besoin.

La source est le plan de démonstration (trace UTMB publique, coureur inventé),
jamais le plan d'un client.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PLAN = RACINE / "tools" / "test" / "plan-fixture.json"
PAGE = RACINE / "index.html"
DEBUT = "<!-- APERCU:DEBUT (écrit par tools/build_apercu.py) -->"
FIN = "<!-- APERCU:FIN -->"

# Le cadre. Les libellés de ravitaillement sont inclinés : c'est ce qui permet
# d'en nommer vingt-cinq sur mille unités sans en tronquer un seul.
W = 1000
G, D, HAUT = 46, 12, 12          # marges : gauche (altitudes), droite, haut
PH = 186                          # hauteur du relief
LABELS = 104                      # place réservée aux noms inclinés
H = HAUT + PH + 18 + LABELS
INCLINAISON = -38


def fr(v, d=1):
    """Un nombre à la française : virgule décimale et vrai signe moins."""
    return f"{v:.{d}f}".replace(".", ",").replace("-", "−")


def milliers(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def classe_pente(pente: float) -> str:
    """La pente rangée dans l'échelle de couleurs.

    Les seuils ne sont pas décoratifs : 10 % est la pente où l'allure
    s'effondre, 15 % celle où presque tout le monde marche.
    """
    if pente < -4:
        return "descente"
    if pente < 4:
        return "plat"
    if pente < 10:
        return "doux"
    if pente < 15:
        return "raide"
    return "mur"


LIBELLE = {"descente": "descente", "plat": "plat", "doux": "montée",
           "raide": "raide", "mur": "très raide"}
BORNES = {"descente": "sous −4 %", "plat": "−4 à 4 %", "doux": "4 à 10 %",
          "raide": "10 à 15 %", "mur": "au-delà de 15 %"}


def pente_au_km(plan: dict, km: float, sur_km: float = 1.0) -> float:
    """La pente du dernier kilomètre parcouru avant ce point.

    Prendre la portion qui *contient* le kilomètre donne un contresens aux
    cols, posés sur la frontière entre montée et descente. Et les portions
    agrégées mentent parfois — le plan en contient une à « 0,0 % » qui monte
    pourtant de 77 m en 500 m. On repart donc des tronçons, mesure brute.
    """
    avant = [sg for sg in plan.get("segments", [])
             if km - sur_km < sg.get("km1", 0) <= km + 0.01 and sg.get("slope") is not None]
    if not avant:
        avant = [sg for sg in plan.get("segments", [])
                 if sg.get("km1", 0) <= km + 0.01 and sg.get("slope") is not None][-2:]
    pentes = [sg["slope"] for sg in avant]
    return sum(pentes) / len(pentes) if pentes else 0.0


def moment(plan: dict) -> dict:
    """Le point montré au repos : de nuit, en montée raide, tout renseigné."""
    segs = plan["segments"]
    bons = [s for s in segs
            if s.get("light") == "nuit" and (s.get("slope") or 0) > 10
            and s.get("temp") is not None]
    return bons[len(bons) // 2] if bons else segs[len(segs) // 3]


def ticks_altitude(lo: float, hi: float) -> list[int]:
    """Des altitudes rondes, quatre au plus, jamais collées aux bords."""
    for pas in (200, 250, 500, 1000):
        marques = [a for a in range(0, 9000, pas) if lo < a < hi]
        if len(marques) <= 4:
            return marques
    return []


def donnees(plan: dict) -> str:
    """Les tronçons, au format le plus compact possible.

    Un objet par tronçon pèserait quatre fois plus. Chaque tronçon est donc un
    tableau, dans un ordre que le script de la page connaît :
    [km, altitude, pente, marche, allure, heure, température]
    """
    lignes = [[round(sg.get("km1", 0), 2), sg.get("alt"),
               round(sg.get("slope") or 0, 1),
               0 if sg.get("mode") == "course" else 1,
               sg.get("pace") or "", sg.get("clock") or "",
               round(sg["temp"], 1) if sg.get("temp") is not None else None]
              for sg in plan.get("segments", [])]
    return json.dumps(lignes, ensure_ascii=False, separators=(",", ":"))


def dessin(plan: dict, pt: dict) -> str:
    pts = plan["profile"]
    total = pts[-1][0]
    alts = [a for _, a in pts]
    lo, hi = min(alts), max(alts)
    marge = (hi - lo) * 0.10
    y0, y1 = lo - marge, hi + marge
    sol = HAUT + PH

    def x(km):
        return G + km / total * (W - G - D)

    def y(alt):
        return HAUT + PH - (alt - y0) / (y1 - y0) * PH

    # Le relief, peint par bandes de même pente. On regroupe les intervalles
    # voisins de même classe : 337 formes seraient illisibles et lourdes.
    bandes, debut, courante = [], 0, None
    for i in range(1, len(pts)):
        dkm = pts[i][0] - pts[i - 1][0]
        p = (pts[i][1] - pts[i - 1][1]) / (dkm * 1000) * 100 if dkm > 0 else 0.0
        c = classe_pente(p)
        if courante is None:
            courante = c
        elif c != courante:
            bandes.append((debut, i - 1, courante))
            debut, courante = i - 1, c
    bandes.append((debut, len(pts) - 1, courante or "plat"))

    aire = "".join(
        f'<path class="ap-f ap-f-{c}" d="M{x(pts[a][0]):.1f} {sol:.1f} '
        + " ".join(f"L{x(pts[k][0]):.1f} {y(pts[k][1]):.1f}" for k in range(a, b + 1))
        + f' L{x(pts[b][0]):.1f} {sol:.1f} Z"/>'
        for a, b, c in bandes)

    trace = " ".join(f"{'M' if i == 0 else 'L'}{x(km):.1f} {y(a):.1f}"
                     for i, (km, a) in enumerate(pts))

    nuit = "".join(
        f'<rect x="{x(w["km0"]):.1f}" y="{HAUT}" width="{x(w["km1"]) - x(w["km0"]):.1f}" '
        f'height="{PH}" class="ap-nuit"/>'
        for w in plan.get("windows", []) if w.get("light") == "nuit")

    # L'échelle d'altitude : des valeurs rondes, à gauche, hors du relief.
    axe = "".join(
        f'<line x1="{G}" x2="{W - D}" y1="{y(a):.1f}" y2="{y(a):.1f}" class="ap-grille"/>'
        f'<text x="{G - 8}" y="{y(a) + 3.5:.1f}" text-anchor="end" class="ap-alt">{milliers(a)}</text>'
        for a in ticks_altitude(y0, y1))

    # Tous les ravitaillements, nommés. Les libellés sont inclinés : à plat,
    # vingt-cinq noms sur cette largeur se chevaucheraient forcément.
    marques = []
    for a in plan.get("aid", []):
        px = x(a["km"])
        py = y(a.get("alt") or y0)
        marques.append(
            f'<line x1="{px:.1f}" x2="{px:.1f}" y1="{py:.1f}" y2="{sol:.1f}" class="ap-ravito"/>'
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" class="ap-ravito-pt"/>'
            f'<text transform="translate({px:.1f} {sol + 15}) rotate({INCLINAISON})" '
            f'text-anchor="end" class="ap-nom">{html.escape(a.get("name") or "")}</text>')

    # Repères de distance, posés dans la bande de sol.
    pas = 20 if total > 120 else 10
    kms = "".join(
        f'<text x="{x(k):.1f}" y="{sol + 11:.1f}" text-anchor="middle" class="ap-km">{k}</text>'
        for k in range(0, int(total) + 1, pas))

    px, py = x(pt["km1"]), y(pt["alt"])
    curseur = (f'<line id="apTige" x1="{px:.1f}" x2="{px:.1f}" y1="{HAUT}" y2="{sol:.1f}" class="ap-tige"/>'
               f'<circle id="apPoint" cx="{px:.1f}" cy="{py:.1f}" r="6.5" class="ap-point"/>')

    geo = json.dumps({"w": W, "g": G, "d": D, "haut": HAUT, "ph": PH,
                      "total": round(total, 3), "y0": round(y0, 1), "y1": round(y1, 1)})

    return f'''<svg viewBox="0 0 {W} {H}" class="ap-svg" id="apSvg" data-geo='{geo}'
     role="img" tabindex="0"
     aria-label="Profil de l'UTMB : {fr(total)} kilomètres, {milliers(plan["elevationM"])} mètres de dénivelé positif, {len(plan.get("aid", []))} ravitaillements">
  {nuit}{axe}{aire}<path d="{trace}" class="ap-trait"/>
  <line x1="{G}" x2="{W - D}" y1="{sol}" y2="{sol}" class="ap-sol"/>
  {"".join(marques)}{kms}{curseur}
</svg>'''


def table(plan: dict) -> str:
    """La table de marche : ce qu'un coureur épingle sur son frigo."""
    aid = [a for a in plan.get("aid", []) if 0.5 < a["km"] < plan["distanceKm"] - 0.5]
    froid = min(aid, key=lambda a: a.get("temp", 99)) if aid else None
    pas = max(1, len(aid) // 6)
    choix = {id(a) for a in aid[::pas][:6]}
    if froid:
        choix.add(id(froid))
    lignes = []
    for a in [x for x in aid if id(x) in choix]:
        gear = "".join(f'<span class="ap-g">{html.escape(g)}</span>'
                       for g in (a.get("gear") or []))
        pente = pente_au_km(plan, a["km"])
        lignes.append(f'''
        <tr class="ap-r{' ap-l-nuit' if a.get("light") == "nuit" else ''}">
          <th scope="row"><span class="ap-nom-r">{html.escape(a["name"])}</span>
            <span class="ap-km-r mono">km {fr(a["km"])}</span></th>
          <td><span class="ap-cum">{html.escape(a.get("cumul") or "")}</span>
            <span class="ap-horloge mono">{html.escape((a.get("eta") or "").split(" ")[-1])}</span></td>
          <td><span class="ap-p ap-p-{classe_pente(pente)}">{fr(pente)} %</span></td>
          <td class="ap-t{' ap-t-froid' if (a.get("temp") or 0) < 0 else ''} mono">{fr(a.get("temp", 0))} °C</td>
          <td class="ap-gear">{gear or '<span class="ap-g-none">—</span>'}</td>
        </tr>''')
    return f'''<table class="ap-table">
      <caption class="ap-table-cap">Ta table de marche, ravitaillement par ravitaillement</caption>
      <thead><tr><th scope="col">Ravitaillement</th><th scope="col">Passage</th>
        <th scope="col">Pente avant</th><th scope="col">Température</th>
        <th scope="col">À sortir du sac</th></tr></thead>
      <tbody>{"".join(lignes)}
      </tbody></table>'''


def main() -> int:
    if not PLAN.is_file():
        print(f"Plan de démonstration introuvable : {PLAN}", file=sys.stderr)
        return 1
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    page = PAGE.read_text(encoding="utf-8")
    if DEBUT not in page or FIN not in page:
        print("Les marqueurs sont absents d'index.html.", file=sys.stderr)
        return 1

    pt = moment(plan)
    mode = "Marche" if pt.get("mode") != "course" else "Course"
    nuit_km = sum(w["km1"] - w["km0"] for w in plan.get("windows", [])
                  if w.get("light") == "nuit")
    legende = "".join(
        f'<span class="ap-e"><i class="ap-sw ap-f-{c}"></i>{LIBELLE[c]}'
        f'<small>{BORNES[c]}</small></span>'
        for c in ("descente", "plat", "doux", "raide", "mur"))

    bloc = f"""{DEBUT}
      <figure class="ap">
        <figcaption class="ap-tete">
          <span class="ap-course mono">{plan['race']} · {fr(plan['distanceKm'])} km · {milliers(plan['elevationM'])} m D+ · objectif {html.escape(plan.get('goal') or '')}</span>
          <span class="ap-aide mono" id="apAide">Balaye le profil</span>
        </figcaption>
        {dessin(plan, pt)}
        <div class="ap-lect" id="apLect" role="group" aria-label="Valeurs au point sélectionné">
          <div class="ap-l"><span class="ap-l-l mono">kilomètre</span><span class="ap-l-v" id="apKm">{fr(pt['km1'])}</span></div>
          <div class="ap-l"><span class="ap-l-l mono">altitude</span><span class="ap-l-v" id="apAlt">{milliers(pt['alt'])}<small> m</small></span></div>
          <div class="ap-l"><span class="ap-l-l mono">pente</span><span class="ap-p ap-p-{classe_pente(pt['slope'])}" id="apPente">{fr(pt['slope'])} %</span></div>
          <div class="ap-l"><span class="ap-l-l mono">consigne</span><span class="ap-l-v ap-l-mode" id="apMode">{mode}</span></div>
          <div class="ap-l"><span class="ap-l-l mono">allure</span><span class="ap-l-v" id="apAllure">{html.escape(pt.get('pace') or '')}</span></div>
          <div class="ap-l"><span class="ap-l-l mono">heure</span><span class="ap-l-v" id="apHeure">{html.escape(pt.get('clock') or '')}</span></div>
          <div class="ap-l"><span class="ap-l-l mono">température</span><span class="ap-l-v" id="apTemp">{fr(pt['temp'])}<small> °C</small></span></div>
        </div>
        <figcaption class="ap-legendes">
          <div class="ap-echelle">{legende}</div>
          <div class="ap-reperes">
            <span class="ap-e"><i class="ap-sw-nuit"></i>nuit<small>{nuit_km:.0f} km</small></span>
            <span class="ap-e"><i class="ap-sw-ravito"></i>ravitaillement<small>{len(plan.get('aid', []))} au total</small></span>
          </div>
        </figcaption>
      </figure>
      <script type="application/json" id="apData">{donnees(plan)}</script>

      <div class="ap-tw">{table(plan)}</div>
      {FIN}"""

    avant, reste = page.split(DEBUT, 1)
    _, apres = reste.split(FIN, 1)
    PAGE.write_text(avant + bloc + apres, encoding="utf-8")
    print(f"  aperçu écrit · {len(plan.get('aid', []))} ravitaillements nommés · "
          f"cadre {W}×{H} · point au repos km {fr(pt['km1'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
