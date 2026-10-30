#!/usr/bin/env python3
"""Hold, l'application de bureau.

    python3 app/hold.py              # ouvre la fenêtre
    python3 app/installer.py         # pose Hold.app sur le bureau

Une fenêtre Mac pour tenir ses coureurs : créer leur espace, y déposer des
documents, fabriquer leur stratégie de course à partir de leurs fichiers de
montre et d'un tracé GPX, et publier — sans terminal.

Ce que la page /admin/ du site ne pouvait pas faire, et qui justifie une
application : faire tourner les outils Python de tools/ (import des montres,
profil du coureur, plan de course) sur des fichiers du Mac, et garder la liste
des coureurs avec leurs codes.

L'architecture, en trois morceaux :

  · un petit serveur HTTP, sur 127.0.0.1 et un port tiré au sort, qui expose
    une API JSON. Chaque requête doit porter un jeton de session généré au
    lancement : une page web ouverte ailleurs ne peut donc pas s'en servir ;
  · une interface HTML (app/ui/), affichée dans une fenêtre native par
    pywebview, ou à défaut dans le navigateur ;
  · GitHub comme stockage, exactement comme la page admin : un fichier chiffré
    par coureur dans plan/data/, chiffré ici avant de partir.

Ce qui reste sur le Mac, dans ~/Library/Application Support/Hold/ : la liste
des coureurs, avec leurs codes. C'est un choix : la page admin ne gardait
aucun code, et un code perdu rendait l'espace impossible à rouvrir. Le fichier
n'est lisible que par l'utilisateur du Mac. La clé GitHub, elle, va dans le
trousseau macOS.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import mimetypes
import os
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
OUTILS = RACINE / "tools"
UI = ICI / "ui"
DONNEES = Path.home() / "Library" / "Application Support" / "Hold"
REGISTRE = DONNEES / "coureurs.json"

DEPOT = "lilianmathien49-create/hold-site"
BRANCHE = "main"
SITE = "https://holdrunning.fr"
TROUSSEAU = ("hold-admin", "github")       # service, compte
LIMITE = 10 * 1024 * 1024                  # documents par espace, comme la page admin
JETON = secrets.token_urlsafe(32)          # session : sans lui, l'API répond 403

# Même chiffrement que tools/make-plan.py, chargé tel quel plutôt que recopié :
# il n'y a qu'une définition du format, et elle est là-bas.
_spec = importlib.util.spec_from_file_location("make_plan", OUTILS / "make-plan.py")
make_plan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_plan)

try:
    import certifi
    CONTEXTE = ssl.create_default_context(cafile=certifi.where())
except ImportError:                        # le Python de python.org n'a pas toujours ses certificats
    CONTEXTE = ssl.create_default_context()


class Erreur(Exception):
    """Une erreur à montrer telle quelle : son message est écrit pour Lilian."""


# ---------- Trousseau ----------

def cle_lire() -> str:
    r = subprocess.run(["security", "find-generic-password", "-s", TROUSSEAU[0],
                        "-a", TROUSSEAU[1], "-w"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def cle_ecrire(cle: str) -> None:
    # -U met à jour si elle existe déjà. La clé passe en argument et non par un
    # fichier : elle ne touche jamais le disque en clair.
    r = subprocess.run(["security", "add-generic-password", "-U", "-s", TROUSSEAU[0],
                        "-a", TROUSSEAU[1], "-w", cle], capture_output=True, text=True)
    if r.returncode:
        raise Erreur("Le trousseau macOS a refusé d'enregistrer la clé.")


def cle_effacer() -> None:
    subprocess.run(["security", "delete-generic-password", "-s", TROUSSEAU[0],
                    "-a", TROUSSEAU[1]], capture_output=True)


# ---------- Registre des coureurs ----------

_verrou = threading.Lock()


def registre_lire() -> dict:
    try:
        return json.loads(REGISTRE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def registre_ecrire(r: dict) -> None:
    DONNEES.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRE.with_suffix(".tmp")
    tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)                   # les codes n'appartiennent qu'à l'utilisateur
    tmp.replace(REGISTRE)


# ---------- GitHub ----------

def github(chemin: str, methode="GET", corps=None, brut=False):
    cle = cle_lire()
    if not cle:
        raise Erreur("Aucune clé GitHub : ajoute-la dans Réglages.")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{DEPOT}{chemin}", method=methode,
        data=json.dumps(corps).encode() if corps is not None else None,
        headers={"Authorization": f"Bearer {cle}",
                 "Accept": "application/vnd.github.raw+json" if brut else "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json", "User-Agent": "Hold"})
    try:
        with urllib.request.urlopen(req, context=CONTEXTE, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except urllib.error.URLError:
        raise Erreur("Impossible de joindre GitHub. Vérifie ta connexion.")


def raison(statut: int) -> str:
    return {401: "GitHub refuse la clé : elle a peut-être expiré.",
            403: "La clé n'a pas le droit d'écrire. Vérifie « Contents : Read and write » sur hold-site.",
            409: "L'espace a changé ailleurs entre-temps. Rouvre-le avant de publier.",
            422: "L'espace a changé ailleurs entre-temps. Rouvre-le avant de publier."
            }.get(statut, f"GitHub a répondu {statut}.")


def chemin_de(slug: str) -> str:
    return f"/contents/plan/data/{urllib.parse.quote(slug)}.json"


# ---------- Chiffrement ----------

def dechiffre(pack: dict, mdp: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    cle = hashlib.pbkdf2_hmac("sha256", mdp.encode(), base64.b64decode(pack["salt"]),
                              pack["iter"], 32)
    return json.loads(AESGCM(cle).decrypt(base64.b64decode(pack["iv"]),
                                          base64.b64decode(pack["data"]), None))


def espace_de(c: dict) -> dict:
    """Les plans publiés avant l'enveloppe sont une stratégie à nu."""
    if isinstance(c, dict) and c.get("hold") == 2:
        return {"coureur": c.get("coureur", ""), "titre": c.get("titre", ""),
                "plan": c.get("plan"), "fichiers": c.get("fichiers") or []}
    return {"coureur": (c or {}).get("runner", ""), "titre": (c or {}).get("race", ""),
            "plan": c, "fichiers": []}


def mot_de_passe() -> str:
    return make_plan.make_password()


# ---------- Stratégie de course ----------

def premier_point(gpx: Path) -> tuple[float, float, float]:
    """Où et à quelle altitude la course part : le soleil se lève pour tout
    le monde, mais pas à la même heure à Chamonix et à Paris."""
    for _, el in ET.iterparse(gpx, events=("end",)):
        if el.tag.endswith("trkpt") or el.tag.endswith("rtept"):
            ele = next((c.text for c in el if c.tag.endswith("ele")), None)
            return float(el.get("lat")), float(el.get("lon")), float(ele or 0)
    raise Erreur("Ce GPX ne contient aucun point.")


def fuseau(jour: date) -> float:
    """Heure de Paris : +2 du dernier dimanche de mars au dernier d'octobre."""
    def dernier_dimanche(m):
        d = date(jour.year, m, 31)
        return d.replace(day=31 - (d.weekday() + 1) % 7)
    return 2.0 if dernier_dimanche(3) <= jour < dernier_dimanche(10) else 1.0


def lance(args: list[str]) -> str:
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=RACINE)
    if r.returncode:
        derniere = (r.stderr or r.stdout).strip().splitlines()
        raise Erreur(derniere[-1] if derniere else "L'outil de calcul a échoué.")
    return r.stdout


def strategie(p: dict) -> dict:
    gpx = Path(p.get("gpx") or "")
    if not gpx.is_file():
        raise Erreur("Choisis le tracé GPX de la course.")
    try:
        depart = datetime.strptime(p.get("depart", ""), "%Y-%m-%dT%H:%M")
    except ValueError:
        raise Erreur("La date et l'heure de départ sont incomplètes.")
    objectif = (p.get("objectif") or "").strip()
    if not objectif or ":" not in objectif:
        raise Erreur("L'objectif s'écrit en heures et minutes, par exemple 28:00 ou 3:15.")
    lat, lon, alt = premier_point(gpx)
    with tempfile.TemporaryDirectory(prefix="hold-") as tmp:
        tmp = Path(tmp)
        args = ["tools/build_plan.py", "--gpx", str(gpx), "--race", p.get("course") or gpx.stem,
                "--runner", p.get("coureur") or "", "--target", objectif,
                "--start", depart.strftime("%Y-%m-%d %H:%M"),
                "--tz", str(fuseau(depart.date())), "--lat", f"{lat:.5f}", "--lon", f"{lon:.5f}",
                "--ref-alt", f"{alt:.0f}",
                "--tmin", str(float(p.get("tmin", 6))), "--tmax", str(float(p.get("tmax", 22))),
                "--out", str(tmp / "plan.json")]
        journal = []
        dossier = Path(p["dossier"]) if p.get("dossier") else None
        if dossier:
            if not dossier.is_dir():
                raise Erreur("Le dossier de séances n'existe plus.")
            journal.append(lance(["tools/import_watch.py", str(dossier), "--out", str(tmp / "blocs.csv")]))
            journal.append(lance(["tools/fit_gam.py", str(tmp / "blocs.csv"), "--out", str(tmp / "profil.json")]))
            args += ["--profile", str(tmp / "profil.json")]
        journal.append(lance(args))
        plan = json.loads((tmp / "plan.json").read_text(encoding="utf-8"))
    # Le journal des outils dit d'où vient chaque paramètre, mesuré ou par
    # défaut : c'est ce que Lilian doit relire avant de publier.
    return {"plan": plan, "journal": "\n".join(j.strip() for j in journal if j.strip()),
            "resume": resume_plan(plan)}


def resume_plan(plan: dict | None) -> dict | None:
    if not plan:
        return None
    m = plan.get("model") or {}
    return {"course": plan.get("race", ""), "date": plan.get("date", ""),
            "objectif": plan.get("goal", ""), "km": plan.get("distanceKm"),
            "dplus": plan.get("elevationM"), "marche": m.get("walkKm"),
            "nuit": round(sum(w["km1"] - w["km0"] for w in plan.get("windows", [])
                              if w.get("light") == "nuit"), 1)}


# ---------- Fichiers du Mac ----------

def choisir(genre: str) -> list[str]:
    """Les dialogues natifs du Mac, par AppleScript : ils marchent dans la
    fenêtre comme dans un navigateur, et rendent un vrai chemin de fichier."""
    script = {
        "gpx": 'POSIX path of (choose file with prompt "Tracé GPX de la course" of type {"gpx", "public.xml", "public.data"})',
        "dossier": 'POSIX path of (choose folder with prompt "Dossier des fichiers de montre du coureur")',
        "documents": 'set l to choose file with prompt "Documents à déposer dans son espace" with multiple selections allowed\n'
                     'set s to ""\nrepeat with f in l\nset s to s & POSIX path of f & linefeed\nend repeat\nreturn s',
        "plan": 'POSIX path of (choose file with prompt "Stratégie de course (.json)" of type {"json", "public.json"})',
    }[genre]
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if r.returncode:                       # annulé
        return []
    return [l for l in r.stdout.strip().splitlines() if l]


def lis_document(chemin: str) -> dict:
    f = Path(chemin)
    octets = f.read_bytes()
    return {"nom": f.name, "type": mimetypes.guess_type(f.name)[0] or "application/octet-stream",
            "taille": len(octets), "data": base64.b64encode(octets).decode()}


# ---------- Actions ----------

def etat() -> dict:
    reg = registre_lire()
    return {"cle": bool(cle_lire()), "depot": DEPOT, "site": SITE,
            "coureurs": sorted(({"slug": s, **{k: v for k, v in c.items() if k != "mdp"}}
                                for s, c in reg.items()),
                               key=lambda c: c.get("modifie_iso", ""), reverse=True)}


def ouvrir(slug: str) -> dict:
    reg = registre_lire()
    if slug not in reg:
        raise Erreur("Ce coureur n'est pas dans ta liste.")
    statut, corps = github(chemin_de(slug), brut=True)
    if statut == 404:
        raise Erreur("Cet espace n'existe plus sur le site.")
    if statut != 200:
        raise Erreur(raison(statut))
    es = espace_de(dechiffre(json.loads(corps), reg[slug]["mdp"]))
    code = f"{slug}-{reg[slug]['mdp']}"
    return {**es, "slug": slug, "code": code, "lien": f"{SITE}/plan/#{code}",
            "resume": resume_plan(es["plan"])}


def importer(code: str) -> dict:
    code = (code or "").strip()
    i = code.find("-")
    if i < 1:
        raise Erreur("Le code ressemble à « a3f9c2e1b7-col-ravito-seuil-482 ».")
    slug, mdp = code[:i].lower(), code[i + 1:]
    statut, corps = github(chemin_de(slug), brut=True)
    if statut == 404:
        raise Erreur("Aucun espace ne correspond à ce code.")
    if statut != 200:
        raise Erreur(raison(statut))
    try:
        es = espace_de(dechiffre(json.loads(corps), mdp))
    except Exception:
        raise Erreur("Code incorrect.")
    with _verrou:
        reg = registre_lire()
        reg[slug] = {"mdp": mdp, "coureur": es["coureur"], "titre": es["titre"],
                     "plan": bool(es["plan"]), "docs": len(es["fichiers"]),
                     "modifie_iso": datetime.now().isoformat(timespec="seconds")}
        registre_ecrire(reg)
    return {"slug": slug}


def publier(p: dict) -> dict:
    coureur = (p.get("coureur") or "").strip()
    if not coureur:
        raise Erreur("Il faut au moins le prénom du coureur.")
    fichiers = p.get("fichiers") or []
    if not p.get("plan") and not fichiers:
        raise Erreur("Ajoute une stratégie ou au moins un document.")
    if sum(f.get("taille", 0) for f in fichiers) > LIMITE:
        raise Erreur("Les documents dépassent 10 Mo : le coureur télécharge tout à l'ouverture.")
    with _verrou:
        reg = registre_lire()
    slug = p.get("slug")
    sha = None
    if slug:
        if slug not in reg:
            raise Erreur("Ce coureur n'est pas dans ta liste.")
        mdp = reg[slug]["mdp"]
        statut, corps = github(chemin_de(slug))
        if statut == 200:
            sha = json.loads(corps)["sha"]
        elif statut != 404:
            raise Erreur(raison(statut))
    else:
        for _ in range(5):
            slug = secrets.token_hex(5)
            statut, _ = github(chemin_de(slug))
            if statut == 404:
                break
            if statut != 200:
                raise Erreur(raison(statut))
        mdp = mot_de_passe()
    jour = date.today()
    contenu = {"hold": 2, "coureur": coureur, "titre": (p.get("titre") or "").strip(),
               "plan": p.get("plan"), "fichiers": fichiers,
               "modifie": f"{jour.day} {MOIS[jour.month - 1]} {jour.year}"}
    pack = make_plan.encrypt(contenu, mdp)
    corps = {"message": f"Espace {slug} : {'mise à jour' if sha else 'création'}",
             "content": base64.b64encode(json.dumps(pack).encode()).decode(), "branch": BRANCHE}
    if sha:
        corps["sha"] = sha
    statut, rep = github(chemin_de(slug), "PUT", corps)
    if statut not in (200, 201):
        raise Erreur(raison(statut))
    with _verrou:
        reg = registre_lire()
        reg[slug] = {"mdp": mdp, "coureur": coureur, "titre": contenu["titre"],
                     "plan": bool(p.get("plan")), "docs": len(fichiers),
                     "modifie_iso": datetime.now().isoformat(timespec="seconds")}
        registre_ecrire(reg)
    code = f"{slug}-{mdp}"
    return {"slug": slug, "code": code, "lien": f"{SITE}/plan/#{code}"}


def supprimer(slug: str) -> dict:
    statut, corps = github(chemin_de(slug))
    if statut == 200:
        sha = json.loads(corps)["sha"]
        statut, _ = github(chemin_de(slug), "DELETE",
                           {"message": f"Espace {slug} : suppression", "sha": sha, "branch": BRANCHE})
        if statut != 200:
            raise Erreur(raison(statut))
    elif statut != 404:
        raise Erreur(raison(statut))
    with _verrou:
        reg = registre_lire()
        reg.pop(slug, None)
        registre_ecrire(reg)
    return {}


def enregistrer_cle(cle: str) -> dict:
    cle = (cle or "").strip()
    if not cle:
        raise Erreur("Colle la clé GitHub.")
    ancienne = cle_lire()
    cle_ecrire(cle)
    try:
        statut, _ = github("/contents/plan/data")
    except Erreur:
        statut = 0
    if statut != 200:
        if ancienne:
            cle_ecrire(ancienne)
        else:
            cle_effacer()
        raise Erreur(raison(statut) if statut else "Impossible de joindre GitHub.")
    return {}


OUVRABLES = (SITE + "/", "https://github.com/settings/personal-access-tokens/")


def ouvre_lien(url: str) -> dict:
    """Ouvre dans le navigateur, et seulement ce qu'on attend : l'espace d'un
    coureur, ou la page de création de clé GitHub."""
    if any(str(url).startswith(o) for o in OUVRABLES):
        subprocess.run(["open", url])
    return {}


MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre")


# ---------- Serveur ----------

ROUTES = {
    ("GET", "/api/etat"): lambda p: etat(),
    ("POST", "/api/cle"): lambda p: enregistrer_cle(p.get("cle")),
    ("DELETE", "/api/cle"): lambda p: (cle_effacer(), {})[1],
    ("POST", "/api/ouvrir"): lambda p: ouvrir(p.get("slug")),
    ("POST", "/api/importer"): lambda p: importer(p.get("code")),
    ("POST", "/api/publier"): publier,
    ("POST", "/api/supprimer"): lambda p: supprimer(p.get("slug")),
    ("POST", "/api/strategie"): strategie,
    ("POST", "/api/choisir"): lambda p: {"chemins": choisir(p.get("genre"))},
    ("POST", "/api/documents"): lambda p: {"fichiers": [lis_document(c) for c in choisir("documents")]},
    ("POST", "/api/plan"): lambda p: (lambda c: {"plan": json.loads(Path(c[0]).read_text(encoding="utf-8"))}
                                      if c else {"plan": None})(choisir("plan")),
    ("POST", "/api/lien"): lambda p: ouvre_lien(p.get("url", "")),
}


class Gestion(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _envoie(self, statut: int, corps: bytes, genre="application/json; charset=utf-8"):
        self.send_response(statut)
        self.send_header("Content-Type", genre)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _api(self, methode):
        if self.headers.get("X-Hold-Jeton") != JETON:
            return self._envoie(403, b'{"erreur":"refus"}')
        route = ROUTES.get((methode, urllib.parse.urlsplit(self.path).path))
        if not route:
            return self._envoie(404, b'{"erreur":"inconnu"}')
        n = int(self.headers.get("Content-Length") or 0)
        try:
            p = json.loads(self.rfile.read(n) or b"{}")
            rep = route(p)
            self._envoie(200, json.dumps(rep, ensure_ascii=False).encode())
        except Erreur as e:
            self._envoie(400, json.dumps({"erreur": str(e)}, ensure_ascii=False).encode())
        except Exception as e:                       # noqa: BLE001 — on veut voir l'imprévu
            traceback.print_exc()
            self._envoie(500, json.dumps({"erreur": f"Erreur inattendue : {e}"},
                                         ensure_ascii=False).encode())

    def do_GET(self):
        chemin = urllib.parse.urlsplit(self.path).path
        if chemin.startswith("/api/"):
            return self._api("GET")
        nom = "index.html" if chemin in ("/", "") else chemin.lstrip("/")
        f = (UI / nom).resolve()
        if UI.resolve() not in f.parents or not f.is_file():
            return self._envoie(404, b"")
        corps = f.read_bytes()
        if f.name == "index.html":           # le jeton de session n'existe qu'en mémoire
            corps = corps.replace(b"__JETON__", JETON.encode())
        self._envoie(200, corps, mimetypes.guess_type(f.name)[0] or "application/octet-stream")

    def do_POST(self):
        self._api("POST")

    def do_DELETE(self):
        self._api("DELETE")


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def habille_le_dock():
    """Sans ça, la barre des menus et le Dock affichent « Python »."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = "Hold"
        icone = ICI / "Hold.icns"
        if icone.is_file():
            NSApplication.sharedApplication().setApplicationIconImage_(
                NSImage.alloc().initWithContentsOfFile_(str(icone)))
    except Exception:
        pass


def main() -> int:
    port = port_libre()
    serveur = ThreadingHTTPServer(("127.0.0.1", port), Gestion)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    adresse = f"http://127.0.0.1:{port}/"
    try:
        import webview
    except ImportError:
        # Sans pywebview, le navigateur fait l'affaire ; l'application reste
        # ouverte tant que ce terminal l'est.
        subprocess.run(["open", adresse])
        print(f"  Hold tourne sur {adresse} — ferme cette fenêtre pour l'arrêter.")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0
    habille_le_dock()
    webview.create_window("Hold", adresse, width=1220, height=820, min_size=(980, 640))
    webview.start(habille_le_dock)
    serveur.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
