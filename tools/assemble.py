#!/usr/bin/env python3
"""Réunit les quatre briques en un seul compte-rendu, prêt à être chiffré.

    python3 tools/assemble.py --plan tools/plan-thomas.json \
        --athlete tools/athlete-fit.json \
        --reference tools/utmb-reference.json \
        --montecarlo tools/mc.json \
        --out tools/rapport.json

Chaque brique est facultative : le tableau de bord n'affiche que ce qu'il reçoit.
"""
from __future__ import annotations

import argparse, json
from pathlib import Path


def load(p: str | None):
    if not p:
        return None
    f = Path(p)
    if not f.is_file():
        print(f"  (absent, ignoré : {p})")
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--athlete")
    ap.add_argument("--reference")
    ap.add_argument("--montecarlo")
    ap.add_argument("--lessons")
    ap.add_argument("--notes")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    plan = load(a.plan)
    if plan is None:
        print(f"Plan introuvable : {a.plan}")
        return 1

    fit = load(a.athlete)
    if fit:
        # On met à plat ce dont le tableau de bord a besoin.
        plan["athlete"] = {"sessions": fit.get("sessions"), "blocks": fit.get("blocks"),
                           "walk": fit.get("walk"), "hr": fit.get("hr"), "speed": fit.get("speed"),
                           "r2": (fit.get("hr") or {}).get("r2")}
    ref = load(a.reference)
    if ref:
        plan["reference"] = ref
    mc = load(a.montecarlo)
    if mc:
        plan["montecarlo"] = mc
    les = load(a.lessons)
    if les:
        les["fieldFinishers"] = sum(r.get("finishers", 0) for r in (les.get("byYear") or []))
        plan["lessons"] = les
    if a.notes:
        plan["notes"] = a.notes

    Path(a.out).write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    have = [n for n, v in (("plan", plan), ("profil coureur", fit),
                           ("référence historique", ref), ("leçons des autres", les),
                           ("Monte-Carlo", mc)) if v]
    size = Path(a.out).stat().st_size // 1024
    print(f"  Assemblé : {', '.join(have)}")
    print(f"  Écrit : {a.out} ({size} Ko)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
