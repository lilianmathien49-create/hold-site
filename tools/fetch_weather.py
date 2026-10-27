#!/usr/bin/env python3
"""Météo réellement observée à Chamonix pendant chaque édition de l'UTMB.

    python3 tools/fetch_weather.py --out tools/utmb-weather.json

Source : archives Open-Meteo (gratuites, sans clé). L'UTMB part le vendredi
soir et les coureurs visés arrivent le samedi : on prend donc la fenêtre du
vendredi au dimanche matin.

Sans ces données, impossible de dire si une édition a été lente à cause de la
chaleur ou pour une autre raison.
"""
from __future__ import annotations

import argparse, json, ssl, time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = None

API = ("https://archive-api.open-meteo.com/v1/archive"
       "?latitude=45.9237&longitude=6.8694&start_date={a}&end_date={b}"
       "&hourly=temperature_2m,precipitation&timezone=Europe%2FParis")

# Départ de l'UTMB, vendredi de fin août (2020 annulée).
STARTS = {2013: date(2013, 8, 30), 2014: date(2014, 8, 29), 2015: date(2015, 8, 28),
          2016: date(2016, 8, 26), 2017: date(2017, 9, 1),  2018: date(2018, 8, 31),
          2019: date(2019, 8, 30), 2021: date(2021, 8, 27), 2022: date(2022, 8, 26),
          2023: date(2023, 9, 1),  2024: date(2024, 8, 30), 2025: date(2025, 8, 29)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    out = {}
    for year, start in STARTS.items():
        url = API.format(a=start.isoformat(), b=(start + timedelta(days=2)).isoformat())
        try:
            with urllib.request.urlopen(url, timeout=30, context=CTX) as r:
                h = json.load(r)["hourly"]
        except Exception as e:                      # réseau, quota, format
            print(f"  {year} : indisponible ({type(e).__name__})")
            continue
        temps = [t for t in h["temperature_2m"] if t is not None]
        rain = [p for p in h["precipitation"] if p is not None]
        if not temps:
            continue
        out[year] = {"date": start.isoformat(),
                     "tmax": round(max(temps), 1), "tmin": round(min(temps), 1),
                     "tmean": round(sum(temps) / len(temps), 1),
                     "rain": round(sum(rain), 1)}
        print(f"  {year} ({start:%d/%m}) : {out[year]['tmin']:5.1f} à {out[year]['tmax']:5.1f} °C"
              f" · {out[year]['rain']:5.1f} mm de pluie")
        time.sleep(0.4)

    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if out:
        hot = max(out.items(), key=lambda kv: kv[1]["tmax"])
        cold = min(out.items(), key=lambda kv: kv[1]["tmax"])
        wet = max(out.items(), key=lambda kv: kv[1]["rain"])
        print(f"\n  La plus chaude : {hot[0]} ({hot[1]['tmax']} °C)"
              f" · la plus fraîche : {cold[0]} ({cold[1]['tmax']} °C)"
              f" · la plus humide : {wet[0]} ({wet[1]['rain']} mm)")
    print(f"  Écrit : {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
