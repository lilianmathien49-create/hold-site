#!/usr/bin/env python3
"""Récupère les temps de passage des finishers UTMB proches d'un objectif.

    python3 tools/collect_utmb.py --target 28:00 --window 40 --out tools/utmb-28h.json

Pour chaque édition : un appel au classement (tous les finishers d'un coup), puis
un appel par coureur retenu. Tout est mis en cache sur disque, donc relancer la
commande ne retélécharge rien.

Les données viennent des archives publiques LiveTrail, le chronométreur officiel.
Le script se limite volontairement à une requête par seconde et ne récupère que
les coureurs dans la fenêtre demandée : on ne copie pas la base, on échantillonne.
"""
from __future__ import annotations

import argparse, json, ssl, sys, time
import urllib.error, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# Le trousseau système de macOS n'est pas celui de Python : sans certifi, la
# vérification du certificat échoue alors que curl passe sans broncher.
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CTX = None

BASE = "https://livetrail.net/histo/utmb_{year}"
CACHE = Path(__file__).resolve().parent / ".cache-utmb"
UA = "Hold/1.0 (analyse de pacing pour coaching; lilian.mathien49@gmail.com)"
PAUSE = 1.0           # une requête par seconde, pas plus
YEARS = [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025]


def fetch(url: str, key: str, pause: float = PAUSE) -> str | None:
    """Télécharge une fois, puis sert le cache. Renvoie None si la page manque."""
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{key}.xml"
    if f.is_file():
        return f.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
            body = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"    ! {key} : {e}", file=sys.stderr)
        return None
    time.sleep(pause)
    if "<?xml" not in body[:200]:
        return None
    f.write_text(body, encoding="utf-8")
    return body


def secs(t: str | None) -> int | None:
    try:
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + int(s)
    except (AttributeError, ValueError):
        return None


def ranking(year: int) -> list[dict]:
    body = fetch(f"{BASE.format(year=year)}/classement.php?course=utmb&cat=scratch&from=1&to=5",
                 f"{year}-classement")
    if not body:
        return []
    root = ET.fromstring(body)
    cl = root.find("classement")
    if cl is None:
        return []
    out = []
    for c in cl:
        t = secs(c.get("tps"))
        if t:
            out.append({"bib": c.get("doss"), "rank": int(c.get("class") or 0), "time": t})
    return out


def runner(year: int, bib: str) -> dict | None:
    """Points de contrôle et passages d'un coureur, normalisés."""
    body = fetch(f"{BASE.format(year=year)}/coureur.php?rech={bib}", f"{year}-{bib}")
    if not body:
        return None
    fiche = ET.fromstring(body).find("fiche")
    if fiche is None:
        return None
    pts = {}
    for p in fiche.findall("./pts/pt"):
        try:
            pts[p.get("idpt")] = {"name": p.get("n"), "km": float(p.get("km") or 0),
                                  "climb": float(p.get("d") or 0), "alt": float(p.get("a") or 0)}
        except ValueError:
            continue
    legs = []
    for e in fiche.findall("./pass/e"):
        t = secs(e.get("tps"))
        pt = pts.get(e.get("idpt"))
        if t is None or pt is None:
            continue
        # ha est l'heure d'arrivée au point, hd l'heure de départ : l'écart est le temps d'arrêt.
        stop = None
        arrive, leave = secs(e.get("ha")), secs(e.get("hd"))
        if arrive is not None and leave is not None:
            stop = (leave - arrive) % 86400
        legs.append({"idpt": e.get("idpt"), "name": pt["name"], "km": pt["km"],
                     "climb": pt["climb"], "alt": pt["alt"], "elapsed": t,
                     "rank": e.get("clt"), "stop": stop})
    legs.sort(key=lambda x: x["km"])
    return {"bib": bib, "splits": legs} if len(legs) > 3 else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", default="28:00", help="chrono visé, h:mm")
    p.add_argument("--window", type=int, default=40, help="fenêtre autour de l'objectif, en minutes")
    p.add_argument("--years", default="", help="ex. 2019-2025 ; toutes par défaut")
    p.add_argument("--max-per-year", type=int, default=25, help="plafond de coureurs par édition")
    p.add_argument("--out", required=True)
    a = p.parse_args()

    try:
        hh, mm = a.target.split(":")
        target = int(hh) * 3600 + int(mm) * 60
    except ValueError:
        print("--target attend h:mm, par exemple 28:00", file=sys.stderr)
        return 1

    years = YEARS
    if a.years:
        lo, _, hi = a.years.partition("-")
        years = [y for y in YEARS if int(lo) <= y <= int(hi or lo)]

    window = a.window * 60
    collected, per_year = [], {}
    for y in years:
        board = ranking(y)
        if not board:
            print(f"  {y} : pas de classement")
            continue
        near = sorted((r for r in board if abs(r["time"] - target) <= window),
                      key=lambda r: abs(r["time"] - target))[:a.max_per_year]
        got = 0
        for r in near:
            d = runner(y, r["bib"])
            if d:
                d.update(year=y, time=r["time"], rank=r["rank"])
                collected.append(d)
                got += 1
        per_year[y] = {"finishers": len(board), "retained": got}
        print(f"  {y} : {len(board):>5} finishers · {got} retenus autour de {a.target}")

    if not collected:
        print("Rien à analyser.", file=sys.stderr)
        return 1

    out = {"target": a.target, "targetSec": target, "windowMin": a.window,
           "source": "Archives publiques LiveTrail (chronométreur officiel UTMB)",
           "collected": sum(1 for _ in collected), "perYear": per_year, "runners": collected}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"\n  {len(collected)} coureurs sur {len(per_year)} éditions → {a.out}")
    print(f"  Cache : {CACHE} (supprime-le pour forcer un rafraîchissement)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
