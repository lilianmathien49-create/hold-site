#!/usr/bin/env python3
"""Temps de passage cibles, appris de ceux qui ont réussi le même chrono.

    python3 tools/learn_splits.py tools/utmb-28h-large.json \
        --aid tools/plan-thomas.json --target 28:00 --out tools/learned-splits.json

Le parcours change chaque année : 168 km en 2017, 177 en 2024. Recopier des
kilomètres n'aurait aucun sens. En revanche les ravitaillements gardent leur nom,
et surtout leur **place dans la course**.

Pour chaque ravitaillement, on regarde donc quelle part de son temps total un
finisher avait dépensée en y arrivant. Cette part se transpose à n'importe quel
objectif : 46 % du temps à Courmayeur, c'est 46 % de 28 h comme de 30 h.
"""
from __future__ import annotations

import argparse, json, re, unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np

DROP = r"\b(sortie|entree|arrivee|depart|ravito|sport center|montjoie|lac)\b"


def canon(n: str) -> str:
    s = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", re.sub(DROP, " ", s)).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--aid", required=True, help="plan contenant les ravitaillements de TA course")
    ap.add_argument("--target", required=True, help="objectif h:mm")
    ap.add_argument("--min-editions", type=int, default=6)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    hh, mm = a.target.split(":")
    target = int(hh) * 3600 + int(mm) * 60

    data = json.loads(Path(a.source).read_text(encoding="utf-8"))
    # Part du temps total dépensée en arrivant à chaque lieu, et temps d'arrêt.
    share, stop, years = defaultdict(list), defaultdict(list), defaultdict(set)
    for r in data["runners"]:
        sp = sorted((s for s in r["splits"] if s.get("km")), key=lambda s: s["km"])
        if not sp or not r.get("time"):
            continue
        for s in sp:
            # Le départ porte le même nom que l'arrivée : l'inclure mélangerait
            # des 0 % et des 100 % sous une seule étiquette.
            if s["km"] < 1.0:
                continue
            k = canon(s["name"])
            share[k].append(s["elapsed"] / r["time"])
            years[k].add(r["year"])
            if s.get("stop") and 0 < s["stop"] < 3600:
                stop[k].append(s["stop"])

    mine = json.loads(Path(a.aid).read_text(encoding="utf-8"))
    out, matched = [], 0
    last_km = max(w["km"] for w in mine["aid"])
    for w in mine["aid"]:
        # Départ et arrivée s'appellent tous deux Chamonix : sans ce cas
        # particulier, le départ hériterait des 100 % de l'arrivée.
        if w["km"] < 1.0:
            out.append({"km": w["km"], "name": w["name"], "matched": True, "start": True,
                        "share": 0.0, "eta": 0, "etaLo": 0, "etaHi": 0,
                        "editions": len(data["years"]) if "years" in data else 0, "n": 0})
            continue
        k = canon(w["name"])
        vals, yrs = share.get(k, []), years.get(k, set())
        if len(yrs) < a.min_editions or len(vals) < 40:
            out.append({"km": w["km"], "name": w["name"], "matched": False})
            continue
        matched += 1
        v = np.array(vals)
        med, lo, hi = float(np.median(v)), float(np.percentile(v, 25)), float(np.percentile(v, 75))
        st = stop.get(k, [])
        out.append({
            "km": w["km"], "name": w["name"], "matched": True,
            "editions": len(yrs), "n": len(vals),
            "share": round(med, 4), "shareLo": round(lo, 4), "shareHi": round(hi, 4),
            "eta": int(round(med * target)),
            "etaLo": int(round(lo * target)), "etaHi": int(round(hi * target)),
            "stopMedian": int(np.median(st)) if len(st) >= 20 else None,
        })

    # Les points sans correspondance sont interpolés entre leurs voisins appariés.
    # Le départ (0 km, 0 % du temps) est une ancre connue d'avance.
    known = sorted([(0.0, 0.0)] + [(o["km"], o["share"]) for o in out
                                   if o.get("matched") and not o.get("start")])
    for o in out:
        if o.get("matched") or o.get("start"):
            continue
        km = o["km"]
        before = [p for p in known if p[0] <= km]
        after = [p for p in known if p[0] >= km]
        if before and after:
            (k0, s0), (k1, s1) = before[-1], after[0]
            s = s0 if k1 == k0 else s0 + (s1 - s0) * (km - k0) / (k1 - k0)
        elif before:
            s = before[-1][1]
        else:
            s = after[0][1]          # le plus proche après, jamais le dernier de la liste
        o.update(share=round(s, 4), eta=int(round(s * target)), interpolated=True)

    res = {"target": a.target, "targetSec": target,
           "runners": len(data["runners"]), "years": sorted({r["year"] for r in data["runners"]}),
           "matched": matched, "total": len(out), "points": out}
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")

    hms = lambda s: f"{s//3600}:{s%3600//60:02d}:{s%60:02d}"
    print(f"  {res['runners']} finishers · {matched}/{len(out)} ravitaillements appariés\n")
    print("   km      ravitaillement                 part du temps   passage visé   fourchette")
    for o in out:
        if o.get("eta") is None:
            continue
        tag = "" if o.get("matched") else "  (interpolé)"
        rng = f"{hms(o['etaLo'])} – {hms(o['etaHi'])}" if o.get("etaLo") else ""
        print(f"  {o['km']:6.1f}  {o['name'][:28]:30s} {o['share']*100:6.1f} %    {hms(o['eta']):>9s}   {rng}{tag}")
    print(f"\n  Écrit : {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
