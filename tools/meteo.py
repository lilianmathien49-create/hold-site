#!/usr/bin/env python3
"""La température des séances, quand la montre ne l'écrit pas.

    python3 tools/meteo.py ~/Documents/HOLD/Gatien

Beaucoup de montres n'enregistrent aucune température, et celles qui le font
mesurent surtout la chaleur du poignet. Chaque bloc porte sa position et son
heure : il suffit d'aller demander le temps qu'il faisait.

La source est l'archive ERA5 d'Open-Meteo, qui ne demande pas de clé. Les
requêtes passent par curl : urllib n'a pas de magasin de certificats sur cette
machine, et curl en a un. Une
requête par séance et par jour, au point médian du parcours ; le résultat est
mis en cache, donc la deuxième exécution ne redemande rien.

Ce n'est pas la température du coureur, c'est celle de l'air à deux mètres.
C'est précisément ce qu'on veut : une mesure qui ne dépend ni du poignet, ni
du vent apparent, ni de l'exposition du capteur.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labo_calc as L

API = "https://archive-api.open-meteo.com/v1/archive"
CACHE = Path(__file__).resolve().parent / ".cache-meteo.json"
CHAMPS = "temperature_2m,relative_humidity_2m,wind_speed_10m"


def _cache() -> dict:
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.is_file() else {}


def releve(lat: float, lon: float, jour: str, memoire: dict) -> dict:
    """Les vingt-quatre heures d'un jour, à un dixième de degré près.

    Arrondir la position évite de redemander la même journée pour deux
    séances parties du même quartier.
    """
    cle = f"{lat:.1f},{lon:.1f},{jour}"
    if cle in memoire:
        return memoire[cle]
    q = urllib.parse.urlencode({"latitude": f"{lat:.2f}", "longitude": f"{lon:.2f}",
                                "start_date": jour, "end_date": jour,
                                "hourly": CHAMPS, "timezone": "UTC"})
    r = subprocess.run(["curl", "-sS", "--max-time", "30", f"{API}?{q}"],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:120])
    d = json.loads(r.stdout)
    h = d.get("hourly") or {}
    memoire[cle] = {t[:13] + ":00": {"temp": tm, "hum": hu, "vent": ve}
                    for t, tm, hu, ve in zip(h.get("time", []),
                                             h.get("temperature_2m", []),
                                             h.get("relative_humidity_2m", []),
                                             h.get("wind_speed_10m", []))}
    return memoire[cle]


def enrichis(blocs: list[dict], verbeux=True) -> int:
    """Pose la température de l'air sur chaque bloc qui n'en a pas."""
    memoire = _cache()
    avant = len(memoire)
    # Une requête par séance : toutes ses heures viennent d'un coup.
    seances = {}
    for b in blocs:
        if b.get("lat") and b.get("heure"):
            seances.setdefault(b["seance"], b)
    echecs = 0
    for i, (nom, b) in enumerate(sorted(seances.items()), 1):
        try:
            releve(b["lat"], b["lon"], b["heure"][:10], memoire)
        except Exception as e:
            echecs += 1
            if verbeux and echecs <= 3:
                print(f"    {nom[:40]} : {e}", file=sys.stderr)
        if verbeux and i % 25 == 0:
            print(f"    {i}/{len(seances)} séances")
    if len(memoire) != avant:
        CACHE.write_text(json.dumps(memoire), encoding="utf-8")

    pose = 0
    for b in blocs:
        if b.get("temp") is not None or not b.get("lat") or not b.get("heure"):
            continue
        j = memoire.get(f"{b['lat']:.1f},{b['lon']:.1f},{b['heure'][:10]}")
        v = (j or {}).get(b["heure"])
        if v and v.get("temp") is not None:
            b["temp"] = v["temp"]
            b["hum"] = v.get("hum")
            b["vent"] = v.get("vent")
            pose += 1
    return pose


def main() -> int:
    src = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    b = L.charger(src, refaire="--refaire" in sys.argv)
    manque = sum(1 for x in b if x.get("temp") is None)
    print(f"  {len(b)} blocs, {manque} sans température")
    pose = enrichis(b)
    print(f"  {pose} températures posées depuis l'archive")
    L.cache_de(src).write_text(json.dumps(b), encoding="utf-8")
    t = [x["temp"] for x in b if x.get("temp") is not None]
    if t:
        print(f"  de {min(t):.1f} à {max(t):.1f} °C")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
