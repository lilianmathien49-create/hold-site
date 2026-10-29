#!/usr/bin/env python3
"""Fabrique les pages de La revue à partir de fichiers texte.

    python3 tools/build_revue.py

Lit revue/_articles/*.md, écrit revue/<slug>/index.html pour chacun, refait
revue/index.html et met sitemap.xml à jour.

Un article commence par quelques lignes d'en-tête, puis un trait, puis le
texte :

    titre: Les plaques carbone tiennent-elles leurs promesses ?
    date: 2026-11-04
    resume: Ce que disent les mesures, et ce qu'elles ne disent pas.
    sources: https://doi.org/10.1234/exemple | Hoogkamer et coll., 2018
    ---
    Le texte de l'article, en markdown.

Le markdown reconnu est volontairement réduit à ce qu'on écrit vraiment :
titres (## et ###), paragraphes, **gras**, *italique*, [liens](url), listes
à puces, listes numérotées, citations (>), traits (---) et `code`. Le reste
est écrit tel quel plutôt que silencieusement avalé.
"""
from __future__ import annotations

import html
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SOURCES = RACINE / "revue" / "_articles"
SORTIE = RACINE / "revue"
BASE = "https://holdrunning.fr"

MOIS = ("janvier février mars avril mai juin juillet août septembre octobre "
        "novembre décembre").split()


def slug(texte: str) -> str:
    """Un titre réduit à ce qui tient dans une adresse."""
    sans = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", sans.lower())).strip("-")[:70]


def en_francais(iso: str) -> str:
    """2026-11-04 devient « 4 novembre 2026 »."""
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def lire(fichier: Path) -> dict:
    """Sépare l'en-tête du corps, sans dépendre d'une bibliothèque YAML."""
    brut = fichier.read_text(encoding="utf-8")
    if "\n---" not in brut:
        raise ValueError(f"{fichier.name} : il manque la ligne --- entre l'en-tête et le texte")
    tete, corps = brut.split("\n---", 1)
    meta = {}
    for ligne in tete.splitlines():
        if not ligne.strip() or ligne.lstrip().startswith("#"):
            continue
        if ":" not in ligne:
            raise ValueError(f"{fichier.name} : ligne d'en-tête sans deux-points → {ligne!r}")
        cle, val = ligne.split(":", 1)
        meta[cle.strip().lower()] = val.strip()
    for requis in ("titre", "date"):
        if not meta.get(requis):
            raise ValueError(f"{fichier.name} : l'en-tête doit porter « {requis} »")
    meta["corps"] = corps.lstrip("\n")
    meta["slug"] = meta.get("slug") or slug(meta["titre"])
    meta["fichier"] = fichier
    return meta


def en_ligne(texte: str) -> str:
    """Gras, italique, liens et code, sur du texte déjà échappé."""
    texte = html.escape(texte, quote=False)
    texte = re.sub(r"`([^`]+)`", r"<code>\1</code>", texte)
    texte = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                   r'<a href="\2" target="_blank" rel="noopener">\1</a>', texte)
    texte = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", texte)
    texte = re.sub(r"(?<![*\w])\*([^*]+)\*(?![*\w])", r"<em>\1</em>", texte)
    return texte


def en_html(corps: str) -> str:
    """Le sous-ensemble markdown décrit en tête de fichier."""
    out, liste, numerotee, citation = [], [], False, []

    def vider_liste():
        nonlocal liste, numerotee
        if liste:
            balise = "ol" if numerotee else "ul"
            out.append(f"<{balise}>" + "".join(f"<li>{en_ligne(x)}</li>" for x in liste)
                       + f"</{balise}>")
            liste, numerotee = [], False

    def vider_citation():
        nonlocal citation
        if citation:
            out.append("<blockquote><p>" + en_ligne(" ".join(citation)) + "</p></blockquote>")
            citation = []

    paragraphe: list[str] = []

    def vider_paragraphe():
        nonlocal paragraphe
        if paragraphe:
            out.append("<p>" + en_ligne(" ".join(paragraphe)) + "</p>")
            paragraphe = []

    for ligne in corps.splitlines():
        nue = ligne.strip()
        if not nue:
            vider_paragraphe(); vider_liste(); vider_citation()
            continue
        if nue in ("---", "***", "___"):
            vider_paragraphe(); vider_liste(); vider_citation()
            out.append('<hr class="rv-sep">')
            continue
        if nue.startswith("### "):
            vider_paragraphe(); vider_liste(); vider_citation()
            out.append(f"<h3>{en_ligne(nue[4:])}</h3>")
            continue
        if nue.startswith("## "):
            vider_paragraphe(); vider_liste(); vider_citation()
            out.append(f"<h2>{en_ligne(nue[3:])}</h2>")
            continue
        if nue.startswith("> "):
            vider_paragraphe(); vider_liste()
            citation.append(nue[2:])
            continue
        m = re.match(r"^(\d+)[.)]\s+(.*)", nue)
        if m:
            vider_paragraphe(); vider_citation()
            if liste and not numerotee:
                vider_liste()
            numerotee = True
            liste.append(m.group(2))
            continue
        if nue.startswith(("- ", "* ", "• ")):
            vider_paragraphe(); vider_citation()
            if liste and numerotee:
                vider_liste()
            liste.append(nue[2:])
            continue
        vider_liste(); vider_citation()
        paragraphe.append(nue)

    vider_paragraphe(); vider_liste(); vider_citation()
    return "\n".join(out)


def mots(corps: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ÿ'’-]+", corps))


def tete_html(titre: str, description: str, url: str, profondeur: int, extra: str = "") -> str:
    """L'en-tête commune : même typographie et même feuille que le reste.

    `profondeur` est le nombre de dossiers qui séparent la page de la racine du
    site : 1 pour revue/index.html, 2 pour revue/<slug>/index.html. Déduire ce
    nombre de l'URL marchait tant qu'on n'y regardait pas de près ; le passer
    explicitement évite d'avoir à y regarder.
    """
    racine = "../" * profondeur
    revue = "../" * (profondeur - 1)
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titre)}</title>
<meta name="description" content="{html.escape(description, quote=True)}">
<meta name="theme-color" content="#F2F3F4">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Hold">
<meta property="og:locale" content="fr_FR">
<meta property="og:title" content="{html.escape(titre, quote=True)}">
<meta property="og:description" content="{html.escape(description, quote=True)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{BASE}/media/hold-film-poster.jpg">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@400..700&family=Fraunces:opsz,wght@9..144,400..700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{racine}css/styles.css">
<link rel="stylesheet" href="{racine}revue/revue.css">
{extra}</head>
<body>

<header class="nav" id="nav">
  <a href="{racine}" class="logo" aria-label="Hold, retour au site">Hold<span class="logo-dot" aria-hidden="true"></span></a>
  <div class="nav-r">
    <a href="{revue}" class="link-btn">La revue</a>
    <a href="{racine}#offres" class="link-btn">Nos offres</a>
  </div>
</header>
"""


def page_article(a: dict) -> str:
    url = f"{BASE}/revue/{a['slug']}/"
    resume = a.get("resume", "")
    minutes = max(1, round(mots(a["corps"]) / 220))
    sources = [s.strip() for s in (a.get("sources") or "").split("|") if s.strip()]
    liste_src = ""
    if sources:
        items = []
        for s in sources:
            if s.startswith("http"):
                items.append(f'<li><a href="{html.escape(s, quote=True)}" target="_blank" '
                             f'rel="noopener">{html.escape(s)}</a></li>')
            else:
                items.append(f"<li>{en_ligne(s)}</li>")
        liste_src = ("<section class=\"rv-src\"><h2>Les sources</h2><ul>"
                     + "".join(items) + "</ul></section>")

    schema = f"""<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Article",
 "headline":{_j(a['titre'])},
 "description":{_j(resume)},
 "datePublished":"{a['date']}",
 "author":{{"@type":"Person","name":"Lilian Mathien"}},
 "publisher":{{"@type":"Organization","name":"Hold"}},
 "mainEntityOfPage":"{url}"}}
</script>
"""
    return tete_html(f"{a['titre']} — La revue · Hold", resume or a["titre"], url, 2, schema) + f"""
<main class="rv-art">
  <p class="eyebrow">La revue · {en_francais(a['date'])} · {minutes} min de lecture</p>
  <h1>{en_ligne(a['titre'])}</h1>
  {f'<p class="rv-lede">{en_ligne(resume)}</p>' if resume else ''}
  <div class="rv-corps">
{en_html(a['corps'])}
  </div>
  {liste_src}
  <aside class="rv-cta">
    <p>Si tu veux que ces principes servent <strong>ta</strong> course plutôt que
      de rester une lecture, c'est le travail que je fais avec mes coureurs.</p>
    <a class="btn" href="../../#offres">Voir les formules</a>
  </aside>
  <p class="rv-retour"><a href="../">← Tous les articles</a></p>
</main>

</body>
</html>
"""


def _j(s: str) -> str:
    """Une chaîne JSON sûre, sans importer de quoi sérialiser un objet entier."""
    import json
    return json.dumps(s, ensure_ascii=False)


def page_index(articles: list[dict]) -> str:
    url = f"{BASE}/revue/"
    if articles:
        lignes = "".join(f"""
    <li class="rv-item">
      <a href="{a['slug']}/">
        <p class="rv-date mono">{en_francais(a['date'])} · {max(1, round(mots(a['corps']) / 220))} min</p>
        <h2>{en_ligne(a['titre'])}</h2>
        {f"<p>{en_ligne(a.get('resume', ''))}</p>" if a.get('resume') else ''}
      </a>
    </li>""" for a in articles)
        corps = f'<ul class="rv-list">{lignes}</ul>'
    else:
        corps = ('<p class="rv-vide">Le premier article arrive bientôt. En attendant, '
                 '<a href="../#offres">les formules</a> sont là.</p>')
    return tete_html(
        "La revue — Hold",
        "Ce que dit vraiment la recherche sur l'entraînement, la nutrition et le matériel. "
        "Des études lues, résumées, et ce qu'on peut en faire.",
        url, 1,
    ) + f"""
<main class="rv-index">
  <p class="eyebrow">La revue</p>
  <h1>Ce que dit vraiment la recherche.</h1>
  <p class="rv-lede">Je lis les études, je les résume, et je dis ce qu'on peut en faire —
    y compris quand la réponse est « rien pour l'instant ». Pas de promesses,
    les chiffres et leurs limites.</p>
  {corps}
</main>

</body>
</html>
"""


def ecrire_sitemap(articles: list[dict]) -> None:
    urls = [(f"{BASE}/", "1.0", date.today().isoformat()),
            (f"{BASE}/revue/", "0.8", articles[0]["date"] if articles else date.today().isoformat())]
    urls += [(f"{BASE}/revue/{a['slug']}/", "0.7", a["date"]) for a in articles]
    corps = "".join(f"""
  <url>
    <loc>{u}</loc>
    <lastmod>{d}</lastmod>
    <priority>{p}</priority>
  </url>""" for u, p, d in urls)
    (RACINE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- Écrit par tools/build_revue.py : ne pas modifier à la main. -->\n"
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + corps + "\n</urlset>\n", encoding="utf-8")


def main() -> int:
    if not SOURCES.is_dir():
        print(f"Dossier absent : {SOURCES}", file=sys.stderr)
        return 1
    fichiers = [f for f in sorted(SOURCES.glob("*.md")) if not f.name.startswith("_")]
    articles = []
    for f in fichiers:
        try:
            articles.append(lire(f))
        except ValueError as e:
            print(f"  ignoré — {e}", file=sys.stderr)
    articles.sort(key=lambda a: a["date"], reverse=True)

    vus = {}
    for a in articles:
        if a["slug"] in vus:
            print(f"  deux articles portent l'adresse « {a['slug']} » : "
                  f"{vus[a['slug']].name} et {a['fichier'].name}", file=sys.stderr)
            return 1
        vus[a["slug"]] = a["fichier"]

    for a in articles:
        d = SORTIE / a["slug"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(page_article(a), encoding="utf-8")
        print(f"  revue/{a['slug']}/  ·  {mots(a['corps'])} mots  ·  {a['titre']}")

    (SORTIE / "index.html").write_text(page_index(articles), encoding="utf-8")
    ecrire_sitemap(articles)
    print(f"\n  {len(articles)} article(s) · revue/index.html et sitemap.xml à jour")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
