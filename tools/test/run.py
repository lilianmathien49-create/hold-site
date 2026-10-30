#!/usr/bin/env python3
"""Exécute les tests du tableau de bord avec JavaScriptCore (pas de Node ici).

    python3 tools/test/run.py                            # fixtures versionnés
    python3 tools/test/run.py tools/test/profil-long.json
    python3 tools/test/run.py tools/mon-profil.json tools/mon-plan.json

Le contrat vérifié est celui entre fit_gam.py et plan/plan.js : un champ que le
profil met à null doit disparaître de l'écran, pas y laisser un trou. Les deux
profils d'essai couvrent les deux côtés — l'un où tout est mesurable, l'autre
où la chaleur et la durabilité ne le sont pas.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

JSC = Path("/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def main(argv):
    if not JSC.exists():
        print("JavaScriptCore introuvable : impossible d'exécuter les tests ici.", file=sys.stderr)
        return 2
    profile = Path(argv[1]) if len(argv) > 1 else HERE / "profil-court.json"
    if not profile.exists():
        print(f"profil absent : {profile}", file=sys.stderr)
        return 2
    # Par défaut un fixture versionné et sans coureur réel : le dépôt est
    # public, et les plans en clair n'y entrent pas.
    plan = Path(argv[2]) if len(argv) > 2 else HERE / "plan-fixture.json"
    if len(argv) > 2 and not plan.exists():
        plan = ROOT / "tools" / argv[2]
    suites = [HERE / "gam.js"]
    if plan.exists():
        suites += [HERE / "cockpit.js", HERE / "layout.js"]
    parts = [
        "const PROFIL = " + json.dumps(profile.read_text(encoding="utf-8")) + ";",
        "const PLAN = " + json.dumps(plan.read_text(encoding="utf-8") if plan.exists() else "{}") + ";\n",
        (HERE / "dom.js").read_text(encoding="utf-8"),
        (ROOT / "plan" / "plan.js").read_text(encoding="utf-8"),
    ] + [f"(function () {{\n{p.read_text(encoding='utf-8')}\n}})();\n" for p in suites]
    print(f"  profil : {profile.name} · plan : {plan.name if plan.exists() else 'aucun'}")
    code = lancer(parts)

    # Le carrousel des avis tourne dans son propre bac : il installe son faux
    # DOM, et celui de dom.js ne doit pas s'y mélanger.
    module = (ROOT / "js" / "avis.js").read_text(encoding="utf-8")
    code |= lancer([module.replace("export function", "function"),
                    (HERE / "avis.js").read_text(encoding="utf-8")])
    return code


def lancer(parts):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write("\n".join(parts))
        tmp = f.name
    r = subprocess.run([str(JSC), tmp], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.stderr.strip():
        sys.stderr.write(r.stderr)
    Path(tmp).unlink(missing_ok=True)
    return 1 if ("KO" in r.stdout or r.returncode != 0) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
