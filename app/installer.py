#!/usr/bin/env python3
"""Pose Hold.app sur le bureau.

    python3 app/installer.py

L'application n'est qu'un lanceur : un petit paquet .app dont l'exécutable
appelle ce Python-ci sur app/hold.py, dans ce dossier-ci. Tout le code reste
dans le dépôt, si bien qu'une mise à jour du dépôt met l'application à jour
sans rien réinstaller.

Si le dossier du dépôt change de place, il suffit de relancer ce script.
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ICI = Path(__file__).resolve().parent
CIBLE = Path.home() / "Desktop" / "Hold.app"
JOURNAL = Path.home() / "Library" / "Logs" / "Hold.log"


def main() -> int:
    try:
        import webview  # noqa: F401
    except ImportError:
        print("  pywebview manque : python3 -m pip install --user pywebview")
        print("  Sans lui, Hold s'ouvrira dans le navigateur plutôt que dans sa fenêtre.")

    if CIBLE.exists():
        shutil.rmtree(CIBLE)
    macos = CIBLE / "Contents" / "MacOS"
    ressources = CIBLE / "Contents" / "Resources"
    macos.mkdir(parents=True)
    ressources.mkdir(parents=True)

    with open(CIBLE / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({
            "CFBundleName": "Hold",
            "CFBundleDisplayName": "Hold",
            "CFBundleIdentifier": "fr.holdrunning.bureau",
            "CFBundleExecutable": "Hold",
            "CFBundleIconFile": "Hold",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        }, f)

    # Un lancement depuis le Finder n'hérite d'aucun PATH : chemins absolus,
    # et les erreurs vont dans un journal plutôt que nulle part.
    lanceur = macos / "Hold"
    lanceur.write_text(
        "#!/bin/bash\n"
        f'exec "{sys.executable}" "{ICI / "hold.py"}" >>"{JOURNAL}" 2>&1\n',
        encoding="utf-8")
    lanceur.chmod(0o755)

    icone = ICI / "Hold.icns"
    if icone.is_file():
        shutil.copy(icone, ressources / "Hold.icns")
    # Le Finder garde les icônes en cache : on lui signale le changement.
    os.utime(CIBLE, None)
    subprocess.run(["touch", str(CIBLE)])

    print(f"\n  Hold.app posée sur le bureau : {CIBLE}")
    print("  Double-clique pour l'ouvrir. Tu peux la glisser dans le Dock.")
    print(f"  En cas de souci, le journal est dans {JOURNAL}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
