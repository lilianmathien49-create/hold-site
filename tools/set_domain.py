#!/usr/bin/env python3
"""Change l'adresse du site partout d'un seul coup.

    python3 tools/set_domain.py https://holdrunning.fr
    python3 tools/set_domain.py --retour          # revient à l'adresse github.io

L'adresse du site est écrite en dur à une quinzaine d'endroits — liens
canoniques, balises de partage, données structurées, sitemap, robots.txt, et
le lien affiché par make-plan.py quand il remet un code à un coureur. La
changer à la main, c'est en oublier un ; et un lien canonique qui pointe vers
un domaine mort est pire que pas de lien canonique du tout.

Écrit aussi le fichier CNAME, que GitHub Pages lit pour servir le site sur le
domaine. Sans lui, le domaine pointe vers GitHub et GitHub ne sait pas quoi
en faire.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

RACINE = Path(__file__).resolve().parent.parent
GITHUB = "https://lilianmathien49-create.github.io/hold-site"

# Les fichiers qui portent l'adresse. Les pages d'articles sont refaites par
# build_revue.py, donc inutile de les toucher ici.
FICHIERS = ("index.html", "robots.txt", "sitemap.xml", "revue/index.html",
            "tools/build_revue.py", "tools/make-plan.py")


def adresse_actuelle() -> str:
    """Ce que les fichiers disent aujourd'hui, pour savoir quoi remplacer."""
    texte = (RACINE / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<link rel="canonical" href="(https?://[^"]+?)/?"', texte)
    if not m:
        raise SystemExit("Pas de lien canonique dans index.html : impossible de savoir "
                         "quelle adresse remplacer.")
    return m.group(1).rstrip("/")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1

    nouvelle = GITHUB if argv[1] == "--retour" else argv[1].rstrip("/")
    if not nouvelle.startswith("https://"):
        print("L'adresse doit commencer par https:// — GitHub Pages sert le site en "
              "HTTPS, et un lien canonique en http enverrait les moteurs sur une "
              "redirection.", file=sys.stderr)
        return 1

    ancienne = adresse_actuelle()
    if ancienne == nouvelle:
        print(f"  Le site annonce déjà {nouvelle} — rien à faire.")
        return 0

    total = 0
    for nom in FICHIERS:
        f = RACINE / nom
        if not f.is_file():
            continue
        avant = f.read_text(encoding="utf-8")
        apres = avant.replace(ancienne, nouvelle)
        n = avant.count(ancienne)
        if n:
            f.write_text(apres, encoding="utf-8")
            total += n
            print(f"  {nom:<26} {n} remplacement(s)")

    # Le CNAME porte le domaine nu, sans protocole ni barre finale : c'est ce
    # que GitHub attend, et une barre en trop suffit à le faire échouer.
    cname = RACINE / "CNAME"
    if nouvelle == GITHUB:
        if cname.exists():
            cname.unlink()
            print("  CNAME                      supprimé")
    else:
        hote = urlparse(nouvelle).netloc
        cname.write_text(hote + "\n", encoding="utf-8")
        print(f"  CNAME                      {hote}")

    print(f"\n  {total} adresse(s) mise(s) à jour : {ancienne} → {nouvelle}")
    if (RACINE / "revue" / "_articles").is_dir():
        print("  Pense à relancer : python3 tools/build_revue.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
