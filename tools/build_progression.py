#!/usr/bin/env python3
"""Écrit la progression de Clément sous « Ils nous ont fait confiance ».

    python3 tools/build_progression.py

La démonstration tient dans ses deux publications Strava, dans cet ordre :
un premier 10 km en 46:06, puis le marathon en 2 h 59. Entre les deux, une
flèche dit ce que la table de Riegel — celle de tous les calculateurs
d'allure — prévoyait à partir de ce 10 km. C'est l'écart entre cette
prédiction et la ligne d'arrivée qui se vend, et il n'a pas besoin d'être
redessiné : les deux captures le portent.

Un tableau et un schéma d'axe occupaient cette place avant. Ils redisaient en
chiffres propres ce que les captures disaient déjà, et personne n'a besoin de
lire deux fois le même chrono.

La prédiction n'est pas écrite en dur : elle se recalcule depuis le 10 km,
donc elle ne peut pas se désynchroniser du chrono de la capture.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
PAGE = RACINE / "index.html"
DEBUT = "<!-- PROGRESSION:DEBUT (écrit par tools/build_progression.py) -->"
FIN = "<!-- PROGRESSION:FIN -->"

DIX_S = 46 * 60 + 6          # le 10 km officiel, point de départ de la formule
MAR_MIN = 179.0              # 2 h 59
RIEGEL = 1.06                # l'exposant d'origine, celui des calculateurs

# Une flèche courbe tracée à la main : elle part de la capture et descend vers
# ce qu'on en déduit. Elle désigne, là où une phrase aurait réexpliqué.
FLECHE = ('<svg class="pv-fl" viewBox="0 0 40 38" aria-hidden="true">'
          '<path d="M6 2C6 16 14 28 34 31"/>'
          '<path d="M34 31l-7.1-5.6M34 31l-8.3 3.3"/></svg>')


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

    bloc = f"""{DEBUT}
  <div class="preuve reveal">
    <figure class="pv">
      <img src="media/clement-10km.png" width="1416" height="356" loading="lazy" decoding="async"
           alt="Capture Strava du 14 août 2025 : « Premier 10km officiel — 46'06 », 10 km de La Marinade, 10,05 km en 46 min 6 s à 4:35 par kilomètre.">
      <figcaption class="pv-note">{FLECHE}<span>D'après la table de Riegel, celle de tous
        les calculateurs d'allure, ce 10 km annonce un marathon
        en <b class="pv-n">{hhmm(prevu)}</b>.</span></figcaption>
    </figure>
    <figure class="pv">
      <img src="media/clement-marathon.png" width="1446" height="612" loading="lazy" decoding="async"
           alt="Capture Strava du 12 avril 2026 : Marathon de Paris 2026, 42,55 km en 2 h 59 min à 4:13 par kilomètre, meilleur effort estimé 2:58:10, record personnel sur marathon.">
      <figcaption class="pv-note">{FLECHE}<span>Huit mois plus tard :
        <b class="pv-n">{round(gain)} minutes</b> devant la prédiction.</span></figcaption>
    </figure>
  </div>
  {FIN}"""

    avant, reste = page.split(DEBUT, 1)
    _, apres = reste.split(FIN, 1)
    PAGE.write_text(avant + bloc + apres, encoding="utf-8")
    print(f"  progression écrite · prévu {hhmm(prevu)} · couru 2 h 59 · {round(gain)} min d'écart")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
