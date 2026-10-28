#!/usr/bin/env python3
"""Valide le modèle sur des éditions qu'il n'a jamais vues.

    python3 tools/backtest.py tools/utmb-28h-large.json --out tools/backtest.json

Protocole : on retire une édition, on apprend la courbe de référence sur les
onze autres, puis on prédit les temps de passage des coureurs de l'édition
retirée. On recommence pour chaque année.

Deux questions, et deux seulement :

  1. L'ERREUR. De combien se trompe-t-on à chaque point de contrôle ?
     Comparée à quoi ? À l'allure constante, la stratégie du coureur qui ne
     réfléchit pas. Si on ne fait pas mieux qu'elle, tout le reste est du
     décor.

  2. LA CALIBRATION. Quand on annonce un intervalle à 80 %, est-ce que
     80 % des passages réels y tombent ? Un modèle qui se trompe peu mais
     dont les intervalles mentent est dangereux : il donne confiance au
     mauvais moment.

Le chrono final du coureur testé est fourni au modèle : on valide la FORME de
la course, pas la prédiction du chrono. C'est bien ce que vend le produit —
« tu vises 28 h, voici tes temps de passage ».
"""
from __future__ import annotations

import argparse, json, re, statistics as st, unicodedata
from collections import defaultdict
from pathlib import Path

DROP = r"\b(sortie|entree|arrivee|depart|ravito|sport center|montjoie|lac)\b"


def canon(n: str) -> str:
    s = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", re.sub(DROP, " ", s)).strip()


def quant(v, q):
    s = sorted(v)
    if not s:
        return None
    i = max(0, min(len(s) - 1, round(q * (len(s) - 1))))
    return s[i]


def learn(runners, min_obs=30):
    """Part du temps total dépensée en arrivant à chaque lieu, apprise sur les
    éditions d'entraînement uniquement."""
    share = defaultdict(list)
    for r in runners:
        sp = sorted((s for s in r["splits"] if s.get("km")), key=lambda s: s["km"])
        if not sp or not r.get("time"):
            continue
        for s in sp:
            if s["km"] < 1.0:          # le départ porte le nom de l'arrivée
                continue
            share[canon(s["name"])].append(s["elapsed"] / r["time"])
    out = {}
    for k, v in share.items():
        if len(v) >= min_obs:
            out[k] = {"med": st.median(v), "p10": quant(v, .10), "p25": quant(v, .25),
                      "p75": quant(v, .75), "p90": quant(v, .90), "n": len(v)}
    return out


def bias_curve(train, model, bins=10):
    """Le modèle se trompe-t-il systématiquement selon l'avancement ?
    On mesure ça sur les éditions d'entraînement, jamais sur celle qu'on teste :
    sinon on corrige avec la réponse et on se ment à soi-même."""
    acc = defaultdict(list)
    for r in train:
        sp = sorted((s for s in r["splits"] if s.get("km")), key=lambda s: s["km"])
        if len(sp) < 5 or not r.get("time"):
            continue
        total_km = sp[-1]["km"]
        for s in sp:
            if s["km"] < 1.0 or s["km"] >= total_km - 0.5:
                continue
            m = model.get(canon(s["name"]))
            if not m:
                continue
            frac = s["km"] / total_km
            # Erreur en part de temps, pas en minutes : transposable à tout objectif.
            acc[min(bins - 1, int(frac * bins))].append(m["med"] - s["elapsed"] / r["time"])
    return {k: st.median(v) for k, v in acc.items() if len(v) >= 40}


def corrected(m, frac, bias, bins=10):
    """Applique la correction, en gardant les bornes cohérentes avec la médiane."""
    b = bias.get(min(bins - 1, int(frac * bins)), 0.0)
    return {k: (v - b if k in ("med", "p10", "p25", "p75", "p90") else v) for k, v in m.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    data = json.loads(Path(a.source).read_text(encoding="utf-8"))
    runners = [r for r in data["runners"] if r.get("time")]
    years = sorted({r["year"] for r in runners})

    rows, per_year = [], {}
    for y in years:
        train = [r for r in runners if r["year"] != y]
        test = [r for r in runners if r["year"] == y]
        model = learn(train)
        if not model or not test:
            continue
        bias = bias_curve(train, model)
        errs, raw_errs, naive_errs, eff_errs, hit50, hit80, n = [], [], [], [], 0, 0, 0
        for r in test:
            sp = sorted((s for s in r["splits"] if s.get("km")), key=lambda s: s["km"])
            if len(sp) < 5:
                continue
            total_km, total_t = sp[-1]["km"], r["time"]
            for s in sp:
                if s["km"] < 1.0 or s["km"] >= total_km - 0.5:
                    continue
                m = model.get(canon(s["name"]))
                if not m:
                    continue
                frac_km = s["km"] / total_km
                mc = corrected(m, frac_km, bias)
                pred = mc["med"] * total_t
                raw = m["med"] * total_t
                # Deux références. L'allure constante, qui ignore le relief. Et le
                # kilomètre-effort, règle classique de coach : 100 m de dénivelé
                # coûtent autant qu'un kilomètre. C'est elle qu'il faut battre.
                naive = s["km"] / total_km * total_t
                eff_here = s["km"] + (s.get("climb") or 0) / 100
                eff_tot = total_km + (sp[-1].get("climb") or 0) / 100
                effort = eff_here / eff_tot * total_t if eff_tot else naive
                errs.append(abs(pred - s["elapsed"]))
                raw_errs.append(abs(raw - s["elapsed"]))
                naive_errs.append(abs(naive - s["elapsed"]))
                eff_errs.append(abs(effort - s["elapsed"]))
                frac = s["elapsed"] / total_t
                if mc["p25"] <= frac <= mc["p75"]:
                    hit50 += 1
                if mc["p10"] <= frac <= mc["p90"]:
                    hit80 += 1
                n += 1
                rows.append({"year": y, "dist": s["km"] / total_km,
                             "err": (pred - s["elapsed"]) / 60, "naive": (naive - s["elapsed"]) / 60,
                             "effort": (effort - s["elapsed"]) / 60})
        if n:
            per_year[y] = {"n": n, "mae": st.mean(errs) / 60, "rawMae": st.mean(raw_errs) / 60,
                           "naiveMae": st.mean(naive_errs) / 60,
                           "effortMae": st.mean(eff_errs) / 60,
                           "cover50": hit50 / n * 100, "cover80": hit80 / n * 100,
                           "runners": len(test)}

    if not per_year:
        print("Pas assez de données.")
        return 1

    tot = sum(v["n"] for v in per_year.values())
    mae = sum(v["mae"] * v["n"] for v in per_year.values()) / tot
    nmae = sum(v["naiveMae"] * v["n"] for v in per_year.values()) / tot
    emae = sum(v["effortMae"] * v["n"] for v in per_year.values()) / tot
    rmae = sum(v["rawMae"] * v["n"] for v in per_year.values()) / tot
    c50 = sum(v["cover50"] * v["n"] for v in per_year.values()) / tot
    c80 = sum(v["cover80"] * v["n"] for v in per_year.values()) / tot

    # Où se trompe-t-on ? L'erreur selon l'avancement dans la course.
    by_frac = []
    for lo in [i / 10 for i in range(10)]:
        sel = [r for r in rows if lo <= r["dist"] < lo + .1]
        if len(sel) > 30:
            by_frac.append({"from": round(lo, 1),
                            "mae": round(st.mean(abs(r["err"]) for r in sel), 1),
                            "bias": round(st.mean(r["err"] for r in sel), 1),
                            "naive": round(st.mean(abs(r["naive"]) for r in sel), 1),
                            "effort": round(st.mean(abs(r["effort"]) for r in sel), 1),
                            "n": len(sel)})

    res = {"editions": len(per_year), "observations": tot,
           "mae": round(mae, 2), "rawMae": round(rmae, 2),
           "naiveMae": round(nmae, 2), "effortMae": round(emae, 2),
           "gain": round((1 - mae / nmae) * 100, 1),
           "gainEffort": round((1 - mae / emae) * 100, 1),
           "cover50": round(c50, 1), "cover80": round(c80, 1),
           "perYear": {str(k): {kk: round(vv, 2) if isinstance(vv, float) else vv
                                for kk, vv in v.items()} for k, v in per_year.items()},
           "byFraction": by_frac}
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")

    print(f"  {len(per_year)} éditions testées, chacune apprise sur les {len(per_year)-1} autres")
    print(f"  {tot} temps de passage prédits\n")
    print(f"  Erreur moyenne        {mae:6.1f} min   (avec correction de biais)")
    print(f"  Sans correction       {rmae:6.1f} min")
    print(f"  Kilometre-effort      {emae:6.1f} min   (regle de coach)")
    print(f"  Allure constante      {nmae:6.1f} min   (epouvantail)")
    print(f"  Gain sur le km-effort {(1-mae/emae)*100:6.1f} %\n")
    print(f"  Intervalle à 50 %  couvre {c50:5.1f} %   (attendu 50)")
    print(f"  Intervalle à 80 %  couvre {c80:5.1f} %   (attendu 80)")
    verdict = ("intervalles crédibles" if abs(c80 - 80) < 6 else
               "intervalles TROP ÉTROITS" if c80 < 74 else "intervalles trop larges")
    print(f"  → {verdict}\n")
    print("  Erreur selon l'avancement (minutes) :")
    print("   part de course   modèle   km-effort   biais")
    for b in by_frac:
        flag = "  <- on surestime" if b["bias"] > 3 else ("  <- on sous-estime" if b["bias"] < -3 else "")
        print(f"     {b['from']*100:3.0f}-{(b['from']+.1)*100:3.0f} %     {b['mae']:6.1f}   {b['effort']:9.1f}"
              f"   {b['bias']:+6.1f}{flag}")
    print("\n  Par édition :")
    for y, v in sorted(per_year.items()):
        print(f"    {y}   {v['runners']:3d} coureurs   erreur {v['mae']:5.1f} min   "
              f"couverture 80 % : {v['cover80']:5.1f} %")
    print(f"\n  Écrit : {a.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
