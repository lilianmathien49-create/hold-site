"""Le rapport d'analyse d'un coureur, à partir de son dossier de fichiers de montre.

Appelé par app/hold.py. Ce module ne calcule rien lui-même : il enchaîne les
outils de tools/, dans l'ordre, et met leurs résultats en forme. Une analyse
corrigée là-bas l'est ici aussi.

Une règle tient pour chaque section : si les données ne permettent pas de
conclure, la section le dit et ne donne pas de chiffre. Un chiffre faux sur
lequel on bâtit un plan coûte plus cher que pas de chiffre du tout.
"""
from __future__ import annotations

import hashlib
import json
import statistics as st
import subprocess
import sys
import tempfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
OUTILS = ICI.parent / "tools"
sys.path.insert(0, str(OUTILS))

import build_labo as B          # noqa: E402  — les dessins
import labo_calc as L           # noqa: E402  — lecture des montres, pente, dérive, chaleur
import meteo                    # noqa: E402  — la température quand la montre ne l'a pas
import transition as T          # noqa: E402  — la transition course-marche

fr, milliers = B.fr, B.milliers


def empreinte(dossier: Path) -> str:
    """Change dès qu'un fichier est ajouté, retiré ou modifié dans le dossier."""
    h = hashlib.sha1(str(dossier).encode())
    for f in sorted(dossier.rglob("*")):
        if f.is_file() and f.suffix.lower() in (".fit", ".gz", ".gpx", ".tcx"):
            s = f.stat()
            h.update(f"{f.name}{s.st_size}{int(s.st_mtime)}".encode())
    return h.hexdigest()[:16]


def blocs(dossier: Path, cache: Path, progres) -> list[dict]:
    """Les blocs de 15 s, avec la température de l'air. Mis en cache par
    empreinte du dossier : deux coureurs dont le dossier s'appelle pareil ne
    se mélangent pas, et un fichier ajouté relance la lecture."""
    cache.mkdir(parents=True, exist_ok=True)
    f = cache / f"blocs-{empreinte(dossier)}.json"
    if f.is_file():
        return json.loads(f.read_text(encoding="utf-8"))
    progres("Lecture des fichiers de montre")
    b = L.blocs(dossier)
    if not b:
        raise ValueError("Aucune séance à pied lisible dans ce dossier.")
    progres("Température de l'air, séance par séance")
    meteo.CACHE = cache / "meteo.json"
    try:
        meteo.enrichis(b, verbeux=False)
    except Exception:
        pass                    # sans réseau, on garde ce que la montre a écrit
    f.write_text(json.dumps(b), encoding="utf-8")
    return b


def apercu(b: list[dict]) -> dict:
    seances = {x["seance"] for x in b}
    dt = lambda x: x.get("dt", L.PAS)
    heures = sum(dt(x) for x in b) / 3600
    km = sum(x["v"] * dt(x) / 3600 for x in b)
    dplus = sum(x["pente"] / 100 * x["v"] / 3.6 * dt(x) for x in b if x["pente"] > 0)
    jours = sorted(x["heure"][:10] for x in b if x.get("heure"))
    part = lambda cle: round(100 * sum(1 for x in b if x.get(cle) is not None) / len(b))
    return {"seances": len(seances), "heures": round(heures, 1), "km": round(km),
            "dplus": round(dplus), "debut": jours[0] if jours else "", "fin": jours[-1] if jours else "",
            "cadence": part("cad"), "cardio": part("hr"), "temperature": part("temp"),
            "raides": sum(1 for x in b if x["pente"] > 10)}


def svg_pente(p: list[dict]) -> str:
    """La vitesse et la cadence selon la pente, sur le même axe."""
    W, G, DR, HAUT = B.W, B.G, B.DR, B.HAUT
    avec_cad = [q for q in p if q.get("cad")]
    h1, h2, ecart = 132, (96 if avec_cad else 0), (48 if avec_cad else 0)
    H = HAUT + h1 + ecart + h2 + 34
    x0, x1 = p[0]["lo"], p[-1]["hi"]

    def x(v):
        return G + (v - x0) / (x1 - x0) * (W - G - DR)

    vlo, vhi, tv = B.echelle([q["v"] for q in p], 6)

    def y1(v):
        return HAUT + h1 - (v - vlo) / (vhi - vlo) * h1

    dessin = [B.axe_y(y1, tv), B.courbe([(q["x"], q["v"]) for q in p], x, y1, HAUT + h1, "lb-v"),
              B.etiquette(x(p[-1]["x"]), y1(p[-1]["v"]), fr(p[-1]["v"]), "lb-v"),
              f'<text class="lb-t" x="{G}" y="{HAUT - 6}">vitesse · km/h</text>']
    if avec_cad:
        clo, chi, tc = B.echelle([q["cad"] for q in avec_cad], 25)

        def y2(v):
            return HAUT + h1 + ecart + h2 - (v - clo) / (chi - clo) * h2

        dessin += [B.axe_y(y2, tc),
                   B.courbe([(q["x"], q["cad"]) for q in avec_cad], x, y2, HAUT + h1 + ecart + h2, "lb-c"),
                   B.etiquette(x(avec_cad[-1]["x"]), y2(avec_cad[-1]["cad"]), fr(avec_cad[-1]["cad"], 0), "lb-c"),
                   f'<text class="lb-t" x="{G}" y="{HAUT + h1 + ecart - 14}">cadence · pas/min</text>']
    graduations = [v for v in (-20, -10, 0, 10, 20, 30, 40) if x0 <= v <= x1]
    dessin += [f'<line class="lb-zero" x1="{x(0):.1f}" x2="{x(0):.1f}" y1="{HAUT}" '
               f'y2="{HAUT + h1 + ecart + h2:.1f}"/>' if x0 < 0 < x1 else "",
               B.axe_x(x, graduations, H - 10, " %")]
    return (f'<svg viewBox="0 0 {W} {H}" class="lb" role="img" '
            f'aria-label="Vitesse et cadence selon la pente">{"".join(dessin)}</svg>')


def deux_montres(b: list[dict]) -> str:
    """Deux appareils qui ne s'accordent pas sur la fréquence cardiaque
    faussent toute comparaison entre séances. On le détecte à allure égale."""
    par = {}
    for x in b:
        par.setdefault(x["seance"], []).append(x)
    avec = {s for s, g in par.items() if sum(1 for x in g if x.get("cad")) > .5 * len(g)}
    pris = [x for x in b if -3 <= x["pente"] <= 3 and x.get("hr") and 11 <= x["v"] < 13]
    a = [x["hr"] for x in pris if x["seance"] in avec]
    s = [x["hr"] for x in pris if x["seance"] not in avec]
    if len(a) >= 100 and len(s) >= 100 and abs(st.median(a) - st.median(s)) > 8:
        return (f"Ses séances viennent de deux montres qui ne mesurent pas le cœur de la même façon : "
                f"{fr(st.median(a), 0)} battements contre {fr(st.median(s), 0)} à la même allure. "
                "Comparer une sortie à l'autre mélange la chaleur et l'appareil.")
    return ""


def section(ident, titre, chiffre="", phrase="", svg="", source="", raison=""):
    return {"id": ident, "titre": titre, "mesure": not raison, "chiffre": chiffre,
            "phrase": phrase, "svg": svg, "source": source, "raison": raison}


def rapport(dossier: Path, cache: Path, progres) -> dict:
    b = blocs(dossier, cache, progres)
    ap = apercu(b)
    out = []

    progres("Transition course-marche")
    tr = T.a_transition(b) if ap["cadence"] >= 5 else None
    if tr:
        out.append(section(
            "transition", "La transition course-marche", f"{fr(tr['x50'])} %",
            f"Sous {fr(T.SEUIL, 0)} pas par minute, un bloc compte comme marché. La part marchée "
            f"franchit 50 % à {fr(tr['x50'])} % de pente, intervalle de {fr(tr['lo'])} à {fr(tr['hi'])} %.",
            B.svg_transition(tr),
            f"{milliers(tr['n'])} blocs avec cadence · {tr['seances']} séances, dont "
            f"{tr['seances_raides']} avec de la montée · logistique à quatre paramètres"))
    else:
        out.append(section("transition", "La transition course-marche", raison=(
            "Pas assez de séances avec la cadence." if ap["cadence"] < 5 else
            "La part marchée ne franchit jamais 50 % : il ne marche pas, ou pas sur des séances "
            "qui portent la cadence. Il faut des sorties en montée enregistrées avec la cadence.")))

    progres("Effet de la durée sur la transition")
    du = T.a_duree(b, 3.0) if tr else None
    if du:
        mes = [q for q in du["pts"] if q["mesure"]]
        dv = du["derive"]
        out.append(section(
            "duree", "Ce que la durée fait à la transition",
            f"{fr(mes[0]['par_h'])} → {fr(mes[-1]['par_h'])} %",
            f"Sa cadence perd {fr(-dv['par_h'], 1)} pas par minute chaque heure, à pente égale. "
            f"Mesuré sur des séances de {fr(du['tmax'] * 60, 0)} minutes au plus : au-delà, pas de chiffre.",
            B.svg_duree(du, tr),
            f"dérive {fr(dv['par_h'], 2)} pas/min par heure [{fr(dv['lo'], 2)} ; {fr(dv['hi'], 2)}] · "
            f"{dv['seances']} séances à allure tenue"))
    else:
        out.append(section("duree", "Ce que la durée fait à la transition",
                           raison="Il faut d'abord une transition mesurée."))

    progres("Dérive cardiaque")
    f = None
    try:
        f = L.a_fatigue(b)
    except Exception:
        pass
    if f and f["lo"] > 0:
        out.append(section(
            "coeur", "La dérive cardiaque", f"+{fr(f['bpm_h'])} bpm/h",
            f"À vitesse et pente égales, son cœur monte de {fr(f['bpm_h'])} battements par heure, "
            f"entre {fr(f['lo'])} et {fr(f['hi'])}.",
            B.svg_fatigue(f),
            f"{milliers(f['n'])} blocs sur {f['seances']} séances à allure tenue · mesurée à "
            f"l'intérieur de chaque séance, insensible à la montre"))
    else:
        out.append(section("coeur", "La dérive cardiaque", raison=(
            "Pas assez de séances courues à allure tenue avec la fréquence cardiaque." if not f else
            "L'intervalle contient zéro ou des valeurs négatives : pas de dérive mesurable sur ces séances.")))

    progres("Vitesse et cadence selon la pente")
    p = L.a_pente(b)
    if len(p) >= 4:
        haut = max(p, key=lambda q: q["v"])
        out.append(section(
            "pente", "Ce que la pente prend", f"{fr(haut['v'])} → {fr(p[-1]['v'])} km/h",
            f"De sa vitesse la plus haute, sur {fr(haut['lo'], 0)} à {fr(haut['hi'], 0)} %, à "
            f"{fr(p[-1]['v'])} km/h sur {fr(p[-1]['lo'], 0)} à {fr(p[-1]['hi'], 0)} %.",
            svg_pente(p),
            f"{milliers(sum(q['n'] for q in p))} blocs · pente lissée sur 50 m · "
            f"{ap['raides']} blocs au-delà de 10 %"))
    else:
        out.append(section("pente", "Ce que la pente prend", raison="Trop peu de pentes variées."))

    progres("Chaleur")
    alerte = deux_montres(b)
    c = None
    try:
        c = L.a_chaleur(b)
    except Exception:
        pass
    if c and c["lo"] > 0 and not alerte:
        out.append(section(
            "chaleur", "Ce que la chaleur prend", f"+{fr(c['bpm_c'], 2)} bpm/°C",
            f"Chaque degré de plus coûte {fr(c['bpm_c'], 2)} battement à allure égale, d'une sortie à "
            f"l'autre. L'intervalle va de {fr(c['lo'], 2)} à {fr(c['hi'], 2)}.",
            B.svg_chaleur(c),
            f"{c['seances']} séances comparées · température de l'air · tendance de forme retirée"))
    else:
        out.append(section("chaleur", "Ce que la chaleur prend", raison=alerte or (
            "Trop peu de séances avec la température." if not c else
            "L'intervalle contient zéro ou une valeur négative : l'effet n'est pas mesurable sur ces séances.")))

    progres("Profil pour le calcul du plan")
    profil = profil_plan(dossier)
    return {"apercu": ap, "sections": out, "profil": profil,
            "transition": tr["x50"] if tr else None}


def profil_plan(dossier: Path) -> str:
    """Ce que l'outil de plan retiendra de ce coureur, tel qu'il le dit lui-même."""
    with tempfile.TemporaryDirectory(prefix="hold-") as tmp:
        tmp = Path(tmp)
        for args in (["tools/import_watch.py", str(dossier), "--out", str(tmp / "blocs.csv")],
                     ["tools/fit_gam.py", str(tmp / "blocs.csv"), "--out", str(tmp / "profil.json")]):
            r = subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=ICI.parent)
            if r.returncode:
                return "Le profil n'a pas pu être calculé : " + ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1]
        return r.stdout.strip()
