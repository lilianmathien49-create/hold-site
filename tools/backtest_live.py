#!/usr/bin/env python3
"""Un coureur observé en course devient-il plus prévisible ?

    python3 tools/backtest_live.py tools/utmb-28h-large.json --out tools/backtest-live.json

Le backtest statique l'a montré : l'erreur ne vient pas d'un biais du modèle
mais de la variabilité entre coureurs. Deux coureurs qui finissent au même
chrono n'ont pas réparti leur course pareil, et aucune courbe médiane ne peut
deviner lequel on a en face.

Sauf qu'en course, on n'a plus à deviner : on le voit passer.

On mesure donc, à chaque point de contrôle, combien l'observation de ce qui
précède améliore la prédiction de ce qui suit. Trois prédicteurs :

  MÉDIANE    on ignore ce qu'on a vu, on applique la courbe de référence
  REPORT     on reporte l'écart constaté tel quel sur la suite
  RÉGRESSÉ   on reporte une fraction de l'écart, apprise sur les éditions
             d'entraînement — parce qu'un coureur parti trop vite ne reste
             pas toujours en avance

Le chrono final n'est jamais donné : c'est lui qu'on prédit.
"""
from __future__ import annotations

import argparse, json, re, statistics as st, unicodedata
from collections import defaultdict
from pathlib import Path

DROP = r"\b(sortie|entree|arrivee|depart|ravito|sport center|montjoie|lac)\b"


def canon(n: str) -> str:
    s = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", re.sub(DROP, " ", s)).strip()


def tidy(runners):
    """Un coureur devient une suite (fraction de distance, part du temps, nom)."""
    out = []
    for r in runners:
        sp = sorted((s for s in r["splits"] if s.get("km")), key=lambda s: s["km"])
        if len(sp) < 8 or not r.get("time"):
            continue
        tot_km = sp[-1]["km"]
        pts = [(s["km"] / tot_km, s["elapsed"], canon(s["name"]))
               for s in sp if 1.0 <= s["km"] <= tot_km]
        if len(pts) >= 8:
            out.append({"year": r["year"], "time": r["time"], "pts": pts})
    return out


def shares(train):
    """Part du temps total dépensée à chaque lieu, apprise sur l'entraînement."""
    acc = defaultdict(list)
    for r in train:
        for _, el, name in r["pts"]:
            acc[name].append(el / r["time"])
    return {k: st.median(v) for k, v in acc.items() if len(v) >= 30}


def shrinkage(train, sh, grid):
    """Quelle part de l'avance prise à un point se retrouve-t-elle à l'arrivée ?

    Un coefficient de 1 voudrait dire que l'avance se conserve intégralement ;
    un coefficient de 0, qu'elle s'évapore. La vérité est entre les deux, et
    c'est elle qui dit s'il faut s'inquiéter d'un départ rapide."""
    out = {}
    for g in grid:
        xs, ys = [], []
        for r in train:
            obs = [(f, el, n) for f, el, n in r["pts"] if f <= g and n in sh]
            if not obs:
                continue
            f, el, name = obs[-1]
            # Chrono qu'on prédirait en extrapolant naïvement ce passage.
            implied = el / sh[name]
            if implied <= 0:
                continue
            xs.append(implied)
            ys.append(r["time"])
        if len(xs) < 40:
            continue
        mx, my = st.mean(xs), st.mean(ys)
        var = sum((x - mx) ** 2 for x in xs)
        if var <= 0:
            continue
        beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
        out[g] = {"beta": beta, "alpha": my - beta * mx, "n": len(xs)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = json.loads(Path(a.source).read_text(encoding="utf-8"))
    runners = tidy([r for r in data["runners"] if r.get("time")])
    years = sorted({r["year"] for r in runners})
    grid = [i / 20 for i in range(2, 20)]          # tous les 5 % du parcours

    err = defaultdict(lambda: defaultdict(list))
    for y in years:
        train = [r for r in runners if r["year"] != y]
        test = [r for r in runners if r["year"] == y]
        sh = shares(train)
        shr = shrinkage(train, sh, grid)
        if not sh or not shr:
            continue
        # Chrono médian des éditions d'entraînement : la prédiction sans rien savoir.
        base = st.median([r["time"] for r in train])
        for r in test:
            for g in grid:
                obs = [(f, el, n) for f, el, n in r["pts"] if f <= g and n in sh]
                if not obs or g not in shr:
                    continue
                f, el, name = obs[-1]
                implied = el / sh[name]
                k = shr[g]
                err["mediane"][g].append(abs(base - r["time"]))
                err["report"][g].append(abs(implied - r["time"]))
                err["regresse"][g].append(abs(k["alpha"] + k["beta"] * implied - r["time"]))

    rows = []
    for g in grid:
        if len(err["report"][g]) < 100:
            continue
        rows.append({
            "seen": round(g, 2), "n": len(err["report"][g]),
            "mediane": round(st.mean(err["mediane"][g]) / 60, 1),
            "report": round(st.mean(err["report"][g]) / 60, 1),
            "regresse": round(st.mean(err["regresse"][g]) / 60, 1),
        })

    # Coefficient de report moyen, toutes éditions confondues.
    allshr = shrinkage(runners, shares(runners), grid)
    betas = [{"seen": round(g, 2), "beta": round(v["beta"], 3)} for g, v in sorted(allshr.items())]

    Path(a.out).write_text(json.dumps({"rows": rows, "betas": betas}, ensure_ascii=False), encoding="utf-8")

    print(f"  {len(runners)} coureurs · {len(years)} éditions\n")
    print("  Erreur sur le CHRONO FINAL, selon ce qu'on a déjà vu de la course")
    print("  (en minutes ; le chrono n'est jamais donné au modèle)\n")
    print("   vu jusqu'à   sans rien savoir   en reportant l'écart   en le régressant")
    for r in rows:
        if round(r["seen"] * 100) % 10:
            continue
        print(f"     {r['seen']*100:3.0f} %          {r['mediane']:6.1f}              {r['report']:6.1f}"
              f"              {r['regresse']:6.1f}")
    if rows:
        best = min(rows, key=lambda r: r["regresse"])
        first = rows[0]
        print(f"\n  Dès {first['seen']*100:.0f} % de course observés, l'erreur passe de "
              f"{first['mediane']:.0f} à {first['regresse']:.0f} minutes.")
        print(f"  Au mieux : {best['regresse']:.0f} minutes à {best['seen']*100:.0f} % du parcours.")

    print("\n  Part de l'avance qui se conserve jusqu'à l'arrivée :")
    for b in betas:
        if round(b["seen"] * 100) % 15:
            continue
        kind = ("elle s'amplifie" if b["beta"] > 1.05 else
                "elle se conserve" if b["beta"] > 0.9 else
                "elle s'érode" if b["beta"] > 0.6 else "elle s'évapore")
        print(f"    vu {b['seen']*100:3.0f} %   coefficient {b['beta']:5.2f}   {kind}")
    print(f"\n  Écrit : {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
