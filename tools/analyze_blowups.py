#!/usr/bin/env python3
"""Ce que coûte vraiment un départ rapide — sur tout le peloton.

    python3 tools/analyze_blowups.py tools/utmb-field.json --out tools/blowups.json

L'analyse précédente portait sur des coureurs arrivés autour de 28 h. Celui qui
passait sur des bases de 27 h et terminait en 35 h en était donc absent : on ne
mesurait la pénalité d'un départ rapide que chez ceux qui l'avaient absorbée.

Ici on prend le peloton entier. Pour chaque coureur et chaque point de contrôle,
on calcule le chrono qu'il « annonce » : son temps écoulé rapporté à la part de
course habituellement faite à cet endroit. Puis on regarde ce qu'il a réellement
couru.

Un coureur qui annonce 27 h au tiers du parcours finit-il en 27 h ? La réponse
décide de ce qu'on écrit dans un plan de course.
"""
from __future__ import annotations

import argparse, json, re, statistics as st, unicodedata
from collections import defaultdict
from pathlib import Path

DROP = r"\b(sortie|entree|arrivee|depart|ravito|sport center|montjoie|lac)\b"


def canon(n: str) -> str:
    s = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", re.sub(DROP, " ", s)).strip()


def hm(sec: float) -> str:
    sec = int(round(sec))
    return f"{sec//3600}h{sec%3600//60:02d}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--target", default="28:00")
    ap.add_argument("--reference", required=True,
                    help="échantillon des coureurs arrivés à l'objectif : c'est LEUR courbe qui "
                         "définit ce que veut dire « être sur les bases de 28 h »")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    hh, mm = a.target.split(":")
    target = int(hh) * 3600 + int(mm) * 60

    data = json.loads(Path(a.source).read_text(encoding="utf-8"))
    runners = []
    for r in data["runners"]:
        sp = sorted((s for s in r["splits"] if (s.get("km") or 0) >= 1.0), key=lambda s: s["km"])
        if len(sp) >= 8 and r.get("time"):
            tot = sp[-1]["km"]
            runners.append({"time": r["time"], "year": r["year"],
                            "pts": [(s["km"] / tot, s["elapsed"], canon(s["name"])) for s in sp]})
    if len(runners) < 200:
        print("Pas assez de coureurs.")
        return 1

    # La référence vient des coureurs qui ONT réussi l'objectif. Prise sur tout
    # le peloton, elle décrirait un chrono médian de quarante heures et « être
    # sur les bases de 28 h » n'aurait plus de sens.
    ref = json.loads(Path(a.reference).read_text(encoding="utf-8"))
    sh = defaultdict(list)
    for r in ref["runners"]:
        if not r.get("time"):
            continue
        for s_ in r["splits"]:
            if (s_.get("km") or 0) >= 1.0:
                sh[canon(s_["name"])].append(s_["elapsed"] / r["time"])
    share = {k: st.median(v) for k, v in sh.items() if len(v) >= 40}
    print(f"  Référence : {len(ref['runners'])} coureurs arrivés autour de {a.target}, "
          f"{len(share)} lieux\n")

    grid = [0.15, 0.25, 0.35, 0.5, 0.65, 0.8]
    out = {"runners": len(runners), "years": sorted({r["year"] for r in runners}),
           "target": a.target, "points": []}

    print(f"  {len(runners)} coureurs · {len(out['years'])} éditions")
    print(f"  Chronos de {hm(min(r['time'] for r in runners))} à {hm(max(r['time'] for r in runners))}\n")
    print("  Parmi ceux qui ANNONCENT l'objectif à ce stade, qu'ont-ils vraiment couru ?\n")
    print("   stade    n     médiane    1 sur 4 au-delà   1 sur 10 au-delà   tiennent l'objectif")

    for g in grid:
        finals = []
        for r in runners:
            obs = [(f, el, n) for f, el, n in r["pts"] if f <= g and n in share]
            if not obs:
                continue
            f, el, n = obs[-1]
            implied = el / share[n]
            # On ne garde que ceux qui, à ce stade, sont sur les bases de l'objectif.
            if abs(implied - target) <= 1800:          # une demi-heure de marge
                finals.append(r["time"])
        if len(finals) < 25:
            continue
        finals.sort()
        q = lambda p: finals[max(0, min(len(finals) - 1, int(p * (len(finals) - 1))))]
        med, p75, p90 = st.median(finals), q(.75), q(.90)
        hold = sum(1 for t in finals if t <= target + 1800) / len(finals) * 100
        out["points"].append({"stage": round(g, 2), "n": len(finals),
                              "median": int(med), "p75": int(p75), "p90": int(p90),
                              "holdPct": round(hold, 1),
                              "slipMedian": round((med - target) / 60, 1),
                              "slipP90": round((p90 - target) / 60, 1)})
        print(f"    {g*100:3.0f} %  {len(finals):4d}   {hm(med):>7s}      {hm(p75):>7s}"
              f"           {hm(p90):>7s}         {hold:5.1f} %")

    if out["points"]:
        first = out["points"][0]
        print(f"\n  À {first['stage']*100:.0f} % de course, annoncer {a.target} ne veut pas dire grand-chose :")
        print(f"    la moitié finit au-delà de {hm(first['median'])}, "
              f"et un sur dix au-delà de {hm(first['p90'])}.")
        print(f"    Seuls {first['holdPct']:.0f} % tiennent réellement l'objectif.")

    # Combien de l'écart initial se conserve, sur tout le peloton cette fois.
    betas = []
    for g in [i / 20 for i in range(3, 20)]:
        xs, ys = [], []
        for r in runners:
            obs = [(f, el, n) for f, el, n in r["pts"] if f <= g and n in share]
            if not obs:
                continue
            f, el, n = obs[-1]
            xs.append(el / share[n])
            ys.append(r["time"])
        if len(xs) < 150:
            continue
        mx, my = st.mean(xs), st.mean(ys)
        var = sum((x - mx) ** 2 for x in xs)
        if var <= 0:
            continue
        betas.append({"seen": round(g, 2), "beta": round(sum((x - mx) * (y - my)
                      for x, y in zip(xs, ys)) / var, 3), "n": len(xs)})
    out["betas"] = betas

    print("\n  Part de l'avance qui se conserve, peloton entier :")
    for b in betas:
        if round(b["seen"] * 100) % 15:
            continue
        print(f"    vu {b['seen']*100:3.0f} %   coefficient {b['beta']:5.2f}")

    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Écrit : {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
