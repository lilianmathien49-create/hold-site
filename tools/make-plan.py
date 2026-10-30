#!/usr/bin/env python3
"""Chiffre un plan de course pour le dashboard Hold.

    python3 tools/make-plan.py mon-plan.json "Clément Dupont"

Écrit plan/data/<empreinte>.json et affiche le code à transmettre :

    clement-dupont-chamois-aurore-482

Le code commence par le prénom et le nom du coureur, qu'il n'a pas à
retenir, et finit par deux mots et un nombre tirés au sort. Majuscules,
accents, espaces et tirets ne comptent pas : « Clément Dupont Chamois Aurore
482 » ouvre le même espace.

Le nom du fichier publié n'est pas dans le code : c'est une empreinte du
code, calculée lentement. Le dépôt est public ; il ne voit ni nom, ni code,
seulement du chiffré sous un nom opaque. Le code n'est stocké nulle part
par cet outil — note-le à sa sortie.

Les anciens codes, « a7f3c921-arete-allure-105 », dont la première partie
était le nom du fichier, s'ouvrent toujours.
"""
import argparse, base64, hashlib, json, os, re, secrets, sys, unicodedata
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 310_000           # recommandation OWASP pour PBKDF2-SHA256
ROOT = Path(__file__).resolve().parent.parent
# L'empreinte qui nomme le fichier publié. Sel fixe et public : le coureur
# n'a que son code pour retrouver son fichier. Le coût, lui, est le même que
# celui de la clé, si bien que deviner un code ne va pas plus vite par ici.
SEL_FICHIER = b"hold-espace-v2"
MOTS = [m for m in (ROOT / "tools" / "mots.txt").read_text(encoding="utf-8").split()
        if m and not m.startswith("#")]


def normalise(code: str) -> str:
    """Ce que le coureur tape, ramené à une seule écriture.

    Minuscules, accents retirés, tout ce qui n'est ni lettre ni chiffre
    devient un tiret. plan/plan.js et admin/admin.js font exactement la même
    chose ; tools/test/codes.js le vérifie.
    """
    t = unicodedata.normalize("NFD", str(code).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def fichier_de(code: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", normalise(code).encode(), SEL_FICHIER, ITERATIONS, 10).hex()


def make_password(coureur: str = "") -> str:
    """Prénom-nom, deux mots, un nombre : clement-dupont-chamois-aurore-482.

    Le nom se devine ; c'est la fin qui protège : 1 016 mots au carré par
    mille nombres, un milliard de suites, chacune au prix d'un calcul lent.
    """
    tete = normalise(coureur)
    fin = f"{secrets.choice(MOTS)}-{secrets.choice(MOTS)}-{secrets.randbelow(900) + 100}"
    return f"{tete}-{fin}" if tete else fin


def force(code: str, coureur: str = "") -> tuple[float, str]:
    """Ce que vaut un code choisi à la main, sans compter le nom du coureur.

    Estimation prudente : un mot de la liste vaut dix bits, un chiffre un peu
    plus de trois, n'importe quel autre morceau deux bits par caractère — un
    mot inventé se devine bien plus vite qu'une suite au hasard.
    """
    connus = set(normalise(coureur).split("-")) if coureur else set()
    liste = set(MOTS)
    bits = 0.0
    for m in normalise(code).split("-"):
        if not m or m in connus:
            continue
        if m.isdigit():
            # Une année se devine : on la compte comme une quinzaine d'essais.
            bits += 4.0 if len(m) == 4 and 1950 <= int(m) <= 2040 else 3.32 * len(m)
        elif m in liste:
            bits += 9.99
        else:
            bits += 2.0 * len(m)
    if bits >= 28:
        return bits, ""
    return bits, ("Code trop facile à deviner. Ajoute par exemple deux mots et un nombre "
                  "après le nom : clement-dupont-chamois-aurore-482.")


def encrypt(plan: dict, password: str) -> dict:
    """Rien d'identifiant ne sort d'ici : le dépôt est public, donc le fichier
    publié ne contient que du chiffré. Pas de nom de coureur en clair."""
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, 32)
    blob = AESGCM(key).encrypt(iv, json.dumps(plan, ensure_ascii=False).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "iter": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "data": b64(blob)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Chiffre un plan de course pour le dashboard Hold.")
    ap.add_argument("source", help="le plan en clair, au format JSON")
    ap.add_argument("coureur", nargs="?", default="",
                    help="prénom et nom du coureur : ils ouvrent son code")
    ap.add_argument("--code", help="code imposé (sinon tiré au sort)")
    ap.add_argument("--base-url", default="https://holdrunning.fr",
                    help="adresse du site, pour afficher le lien complet")
    a = ap.parse_args()

    src = Path(a.source)
    if not src.is_file():
        print(f"Fichier introuvable : {src}", file=sys.stderr)
        return 1
    try:
        plan = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"JSON invalide dans {src} : {e}", file=sys.stderr)
        return 1

    coureur = a.coureur or plan.get("runner", "")
    code = normalise(a.code) if a.code else make_password(coureur)
    _, refus = force(code, coureur)
    if refus:
        print(refus, file=sys.stderr)
        return 1

    out = ROOT / "plan" / "data" / f"{fichier_de(code)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and input(f"{out.name} existe déjà. L'écraser ? [o/N] ").strip().lower() not in ("o", "oui"):
        print("Abandonné.")
        return 1
    out.write_text(json.dumps(encrypt(plan, code)), encoding="utf-8")

    print(f"\n  Écrit        {out.relative_to(ROOT)}  ({out.stat().st_size // 1024} Ko)")
    print(f"  Coureur      {coureur or '—'} · {plan.get('race', '—')}")
    print("\n  À TRANSMETTRE AU COUREUR :")
    print(f"\n    Son espace   {a.base_url}/plan/")
    print(f"    Son code     {code}")
    print("\n  Ou directement, sans rien taper :")
    print(f"    {a.base_url}/plan/#{code}")
    print("\n  Le code n'est stocké nulle part : note-le maintenant.")
    print("  Puis : git add plan/data && git commit && git push\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
