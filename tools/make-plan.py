#!/usr/bin/env python3
"""Chiffre un plan de course pour le dashboard Hold.

    python3 tools/make-plan.py mon-plan.json thomas-utmb

Écrit plan/data/thomas-utmb.json et affiche le lien + le mot de passe à transmettre.
Le mot de passe est tiré au sort si on ne le donne pas (--password pour le choisir).

Le fichier produit ne contient que du chiffré : publié sur GitHub, il reste illisible
sans le mot de passe. Celui-ci n'est jamais stocké nulle part — note-le à sa sortie.
"""
import argparse, base64, hashlib, json, os, secrets, sys
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 310_000           # recommandation OWASP pour PBKDF2-SHA256
ROOT = Path(__file__).resolve().parent.parent
WORDS = ("cime arete col ravito foulee cadence seuil tempo bitume sentier "
         "aurore crete denivele allure").split()


def make_password() -> str:
    """Trois mots et un nombre : dictable au téléphone, assez long pour résister."""
    return "-".join(secrets.choice(WORDS) for _ in range(3)) + "-" + str(secrets.randbelow(900) + 100)


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
    ap.add_argument("slug", nargs="?", help="identifiant dans l'URL ; tiré au sort si omis. "
                                            "Évite le nom du coureur : le dépôt est public.")
    ap.add_argument("--password", help="mot de passe imposé (sinon tiré au sort)")
    ap.add_argument("--base-url", default="https://lilianmathien49-create.github.io/hold-site",
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

    # Sans slug imposé, on en tire un opaque : le nom du fichier est visible
    # sur le dépôt public, il ne doit donc rien dire du coureur.
    slug = (a.slug or secrets.token_hex(5)).strip().lower()
    if not slug.isalnum():
        # Le code unique se coupe au premier tiret : un identifiant qui en
        # contient rendrait la séparation ambiguë.
        print("L'identifiant ne doit contenir que des lettres et des chiffres, "
              "sans tiret.", file=sys.stderr)
        return 1

    password = a.password or make_password()
    out = ROOT / "plan" / "data" / f"{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and input(f"{out.name} existe déjà. L'écraser ? [o/N] ").strip().lower() not in ("o", "oui"):
        print("Abandonné.")
        return 1
    out.write_text(json.dumps(encrypt(plan, password)), encoding="utf-8")

    print(f"\n  Écrit        {out.relative_to(ROOT)}  ({out.stat().st_size // 1024} Ko)")
    print(f"  Coureur      {plan.get('runner', '—')} · {plan.get('race', '—')}")
    code = f"{slug}-{password}"
    print("\n  À TRANSMETTRE AU COUREUR — une seule chose à retenir :")
    print(f"\n    Son espace   {a.base_url}/plan/")
    print(f"    Son code     {code}")
    print("\n  Il peut aussi ouvrir directement, sans rien taper :")
    print(f"    {a.base_url}/plan/#{code}")
    print("\n  Le code n'est stocké nulle part : note-le maintenant.")
    print("  Puis : git add plan/data && git commit && git push\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
