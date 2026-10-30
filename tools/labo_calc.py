#!/usr/bin/env python3
"""Les statistiques du laboratoire, calculées sur de vrais fichiers de montre.

    python3 tools/labo_calc.py ~/Documents/HOLD/i252597_fit_files-3

Trois questions, trois réponses, et rien d'inventé entre les deux :

1. Ce que la pente prend. On range chaque bloc de 15 s par pourcentage et on
   regarde la vitesse et la cadence. Le résultat n'est pas celui qu'on attend.
2. Ce que les heures prennent. Dérive cardiaque à vitesse égale, mesurée à
   l'intérieur de chaque séance pour que les écarts de forme entre sorties
   n'entrent pas dans le compte.
3. Ce que la chaleur prend. Celle-là ne se mesure PAS à l'intérieur d'une
   séance : la sonde d'une montre chauffe au poignet puis refroidit dans le
   vent, et cette variation-là n'a rien de météorologique — en intra-séance
   l'estimation ressort à −1,2 bpm/°C, c'est-à-dire que plus il ferait chaud
   moins le cœur monterait. Le signal utile est entre séances, une sortie
   fraîche contre une sortie chaude, avec une tendance pour la forme.

Les intervalles viennent d'un rééchantillonnage des séances entières, jamais
des blocs : deux blocs consécutifs de la même sortie ne sont pas deux mesures
indépendantes.
"""
from __future__ import annotations

import json
import random
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fitread

PAS = 15                 # secondes par bloc
FENETRE = 25.0           # demi-fenêtre de pente, en mètres parcourus
CACHE = Path(__file__).resolve().parent / ".cache-labo.json"
# Un dossier d'athlète mélange les sports. On ne peut pas trier sur la
# dynamique de course : la moitié des montres ne l'écrit pas. On trie donc sur
# le nom que l'export donne à la séance, et on vérifie derrière que l'allure
# ressemble à de la course à pied.
APIED = ("course__pied", "course_a_pied", "trail", "running", "run")
V_MIN, V_MAX = 4.0, 22.0        # km/h médians plausibles à pied
# Les montres sans baromètre tirent l'altitude du GPS, qui saute. Au-delà de
# 45 % sur cinquante mètres on ne lit plus un terrain mais une erreur.
PENTE_MAX = 45.0
V0 = 12.5                # allure de référence pour ramener les FC, km/h


def blocs(src: Path) -> list[dict]:
    out = []
    for f in sorted(src.glob("*.fit")):
        try:
            tous = fitread.read_fit(f)
        except Exception:
            continue
        pts = [p for p in tous if p.get("dist") is not None]
        if len(pts) < 60:
            continue
        if not any(m in f.stem.lower() for m in APIED):
            continue
        vm = sorted((pts[i]["dist"] - pts[i - 1]["dist"])
                    / max(0.5, (pts[i]["t"] - pts[i - 1]["t"]).total_seconds()) * 3.6
                    for i in range(1, len(pts)))
        if not V_MIN <= vm[len(vm) * 3 // 4] <= V_MAX:   # trop lent ou trop rapide
            continue
        t0, d = pts[0]["t"], [p["dist"] for p in pts]
        a = [p.get("alt") for p in pts]

        # La pente barométrique est bruyante entre deux points : on la prend
        # sur ±25 m de distance parcourue, par deux curseurs qui avancent.
        pente, i, j = [None] * len(pts), 0, 0
        for k in range(len(pts)):
            while i < k and d[k] - d[i] > FENETRE:
                i += 1
            while j < len(pts) - 1 and d[j] - d[k] < FENETRE:
                j += 1
            if d[j] - d[i] >= 20 and a[i] is not None and a[j] is not None:
                pente[k] = (a[j] - a[i]) / (d[j] - d[i]) * 100

        for s in range(0, len(pts) - PAS, PAS):
            b = pts[s:s + PAS]
            dt = (b[-1]["t"] - b[0]["t"]).total_seconds()
            dd = b[-1]["dist"] - b[0]["dist"]
            if dt <= 0 or dd < 3:                 # à l'arrêt, rien à mesurer
                continue
            pp = sorted(x for x in pente[s:s + PAS] if x is not None)
            fo = sorted(p["foulee"] for p in b if p.get("foulee"))
            hr = sorted(p["hr"] for p in b if p.get("hr"))
            tp = sorted(p["temp"] for p in b if p.get("temp") is not None)
            if not pp:
                continue
            v = dd / dt * 3.6
            cad = (v / 3.6) / fo[len(fo) // 2] * 60 \
                if fo and fo[len(fo) // 2] > 0.2 else None
            out.append({"pente": pp[len(pp) // 2], "v": v, "cad": cad,
                        "hr": hr[len(hr) // 2] if hr else None,
                        "temp": tp[len(tp) // 2] if tp else None,
                        "ecoule": (b[0]["t"] - t0).total_seconds() / 60,
                        "lat": b[0].get("lat"), "lon": b[0].get("lon"),
                        "heure": b[0]["t"].strftime("%Y-%m-%dT%H:00"),
                        "seance": f.stem})
    return out


def cache_de(src: Path | None) -> Path:
    if src is None:
        return CACHE
    return CACHE.with_name(f".cache-labo-{src.name.lower()[:40]}.json")


def charger(src: Path | None, refaire=False) -> list[dict]:
    c = cache_de(src)
    if not refaire and c.is_file():
        return json.loads(c.read_text(encoding="utf-8"))
    if src is None:
        raise SystemExit("Aucun cache : passe le dossier des .fit en argument.")
    b = blocs(src)
    c.write_text(json.dumps(b), encoding="utf-8")
    return b


def mco(X, y):
    """Moindres carrés par élimination de Gauss, sans dépendance."""
    k = len(X[0])
    A = [[sum(X[i][a] * X[i][c] for i in range(len(X))) for c in range(k)]
         + [sum(X[i][a] * y[i] for i in range(len(X)))] for a in range(k)]
    for c in range(k):
        p = max(range(c, k), key=lambda r: abs(A[r][c]))
        A[c], A[p] = A[p], A[c]
        if abs(A[c][c]) < 1e-12:
            return None
        for r in range(k):
            if r == c:
                continue
            f = A[r][c] / A[c][c]
            for j in range(c, k + 1):
                A[r][j] -= f * A[c][j]
    return [A[i][k] / A[i][i] for i in range(k)]


def centre(gr, champs, mini=40):
    """Effets fixes de séance : chaque bloc perd la moyenne de sa sortie.

    Sans ça, un écart de forme entre deux sorties se lirait comme un effet du
    temps écoulé ou de la température.
    """
    out = []
    for s in {x["seance"] for x in gr}:
        g = [x for x in gr if x["seance"] == s]
        if len(g) < mini:
            continue
        m = {c: st.fmean(x[c] for x in g) for c in champs}
        out += [{c: x[c] - m[c] for c in champs} for x in g]
    return out


def intervalle(valeurs, p=0.95):
    v = sorted(valeurs)
    lo = v[int((1 - p) / 2 * len(v))]
    hi = v[min(len(v) - 1, int((1 - (1 - p) / 2) * len(v)))]
    return lo, hi


def propres(b):
    return [x for x in b if abs(x["pente"]) <= PENTE_MAX]


def a_pente(b):
    """Vitesse et cadence par tranche de pente.

    On s'attend à voir la cadence s'effondrer dans le raide. Elle ne le fait
    pas : c'est la vitesse qui encaisse, par la longueur de foulée.
    """
    bornes = [-20, -14, -10, -6, -3, 0, 3, 6, 10, 14, 18, 24, 32, 45]
    out = []
    for lo, hi in zip(bornes, bornes[1:]):
        g = [x for x in propres(b) if lo <= x["pente"] < hi]
        if len(g) < 60:
            continue
        c = [x["cad"] for x in g if x["cad"]]
        out.append({"x": (lo + hi) / 2, "lo": lo, "hi": hi, "n": len(g),
                    "v": st.median([x["v"] for x in g]),
                    "nc": len(c), "cad": st.median(c) if len(c) >= 40 else None})
    return out


REGULIER = 0.15          # dispersion d'allure au-delà de laquelle c'est du fractionné
ECHAUFFEMENT = 10.0      # minutes écartées en début de séance


def regulieres(b):
    """Les séances courues à allure tenue, et elles seules.

    Un fractionné part vite et finit au calme : à vitesse égale, ses blocs
    tardifs sont des blocs de récupération, et la dérive cardiaque y ressort
    négative. Mesurée sur les seules séances régulières, elle retrouve son
    signe. Le seuil de dispersion ne change pas le résultat : de 0,12 à 0,20,
    la dérive reste entre +4,9 et +6,1 battements par heure.
    """
    garde = set()
    for s in {x["seance"] for x in b}:
        v = [x["v"] for x in b if x["seance"] == s and x["v"]]
        if len(v) >= 40 and st.fmean(v) > 0 and st.pstdev(v) / st.fmean(v) <= REGULIER:
            garde.add(s)
    return [x for x in b if x["seance"] in garde]


def a_fatigue(b, tirages=400):
    """Dérive cardiaque à vitesse égale, à l'intérieur de chaque séance.

    Mesurée à l'intérieur d'une séance, elle est insensible à la montre : deux
    appareils qui ne s'accordent pas sur la fréquence cardiaque s'accordent
    quand même sur sa variation, et l'écart constant disparaît au centrage.
    """
    plat = [x for x in regulieres(propres(b))
            if -3 <= x["pente"] <= 3 and x["hr"] and x["ecoule"] >= ECHAUFFEMENT]
    ch = ["v", "v2", "pente", "ecoule"]
    for x in plat:
        x["v2"] = x["v"] ** 2
    c = centre(plat, ch + ["hr"])
    r = mco([[x[k] for k in ch] for x in c], [x["hr"] for x in c])
    if not r:
        return None

    random.seed(11)
    seances = sorted({x["seance"] for x in plat})
    coefs = []
    for _ in range(tirages):
        ech = []
        for i, s in enumerate(random.choice(seances) for _ in seances):
            ech += [x | {"seance": f"{s}#{i}"} for x in plat if x["seance"] == s]
        cc = centre(ech, ch + ["hr"])
        rr = mco([[x[k] for k in ch] for x in cc], [x["hr"] for x in cc]) if len(cc) > 200 else None
        if rr:
            coefs.append(rr[-1] * 60)
    lo, hi = intervalle(coefs)

    # Pour le dessin : l'écart de FC à la moyenne de sa séance, la vitesse
    # retirée. Le centrage est refait ici parce qu'on garde le temps écoulé
    # d'origine en abscisse, et non sa version centrée.
    res = []
    for s in {x["seance"] for x in plat}:
        g = [x for x in plat if x["seance"] == s]
        if len(g) < 40:
            continue
        m = {c: st.fmean(x[c] for x in g) for c in ch[:-1] + ["hr"]}
        res += [{"t": x["ecoule"],
                 "e": x["hr"] - m["hr"] - sum(r[i] * (x[c] - m[c])
                                              for i, c in enumerate(ch[:-1]))} for x in g]
    pts = []
    for a, z in [(10, 20), (20, 30), (30, 40), (40, 55), (55, 70), (70, 90),
                 (90, 120), (120, 185)]:
        g = [x["e"] for x in res if a <= x["t"] < z]
        if len(g) >= 40:
            pts.append({"x": (a + z) / 2, "y": st.fmean(g), "n": len(g)})
    return {"bpm_h": r[-1] * 60, "lo": lo, "hi": hi, "pts": pts,
            "n": len(c), "seances": len(seances), "par_kmh": r[0],
            # La droite est ajustée sur des écarts : elle passe par le temps
            # moyen des blocs, et nulle part ailleurs.
            "t_moy": st.fmean(x["ecoule"] for x in plat),
            # Au-delà, il ne reste qu'une poignée de séances : la droite
            # s'arrête là où les données cessent d'être nombreuses.
            "t_dense": max((p["x"] for p in pts if p["n"] >= 400), default=90)}


def a_chaleur(b, tirages=600):
    """Ce que la chaleur coûte au cœur, d'une sortie à l'autre.

    Surtout pas à l'intérieur d'une sortie : la sonde d'une montre chauffe au
    poignet à l'arrêt puis refroidit dans le vent, et cette variation-là donne
    un effet négatif, physiologiquement absurde.
    """
    plat = [x for x in propres(b)
            if -3 <= x["pente"] <= 3 and x["hr"] and x["temp"] is not None]
    c = centre(plat, ["v", "hr"])
    pente_v = mco([[x["v"]] for x in c], [x["hr"] for x in c])
    if not pente_v:
        return None
    pente_v = pente_v[0]

    lignes = []
    for i, s in enumerate(sorted({x["seance"] for x in plat})):
        g = [x for x in plat if x["seance"] == s]
        if len(g) < 60:
            continue
        lignes.append({"i": i, "n": len(g),
                       "temp": st.fmean(x["temp"] for x in g),
                       "hr": st.fmean(x["hr"] - pente_v * (x["v"] - V0) for x in g)})
    if len(lignes) < 12:
        return None

    # La tendance « i » absorbe la forme qui change au fil des semaines : sans
    # elle, un été chaud en fin de préparation se lirait comme un effet de la
    # chaleur.
    X = [[1.0, l["temp"], l["i"]] for l in lignes]
    r = mco(X, [l["hr"] for l in lignes])
    random.seed(3)
    coefs = []
    for _ in range(tirages):
        e = [random.choice(lignes) for _ in lignes]
        rr = mco([[1.0, l["temp"], l["i"]] for l in e], [l["hr"] for l in e])
        if rr:
            coefs.append(rr[1])
    lo, hi = intervalle(coefs)
    moy_i = st.fmean(l["i"] for l in lignes)
    return {"bpm_c": r[1], "lo": lo, "hi": hi, "seances": len(lignes),
            "par_kmh": pente_v,
            # Les points sont ramenés à une forme moyenne pour être comparables.
            "pts": [{"x": l["temp"], "y": l["hr"] - r[2] * (l["i"] - moy_i),
                     "n": l["n"]} for l in lignes],
            "droite": (r[0] + r[2] * moy_i, r[1])}


def a_seuil(b):
    """Le seuil de marche, et la part marchée par tranche de pente.

    Le mélange ne s'ajuste pas sur l'ensemble des blocs : six mille blocs de
    plat à 155 pas/min y noient les quelques centaines de blocs marchés, et
    les deux composantes se confondent. Il s'ajuste donc là où la marche est
    possible — au-dessus d'une pente plancher, choisie comme la plus basse qui
    passe les cinq contrôles de tools/seuil_marche.py.

    Une fois le mélange tenu, chaque bloc reçoit sa probabilité de marche, et
    la part marchée par tranche de pente en découle sans qu'on ait jamais eu à
    trancher bloc par bloc.
    """
    import seuil_marche as S

    cad = [x for x in propres(b) if x.get("cad")]
    cad = S.nettoie(cad)
    for plancher in (0, 2, 3, 4, 5, 6, 8):
        g = [x for x in cad if x["pente"] > plancher]
        if len(g) < 200:
            break
        r = S.mesure([x["cad"] for x in g])
        if not r["ok"]:
            continue
        p, s = r["p"], r["seuil"]
        bandes = []
        for lo, hi in [(-3, 0), (0, 3), (3, 6), (6, 10), (10, 14), (14, 20), (20, 32)]:
            q = [x for x in cad if lo <= x["pente"] < hi]
            if len(q) < 40:
                continue
            bandes.append({"x": (lo + hi) / 2, "lo": lo, "hi": hi, "n": len(q),
                           "part": st.fmean(S.proba(x["cad"], p) for x in q),
                           "cad": st.median([x["cad"] for x in q])})
        return {"seuil": s, "plancher": plancher, "p": p, "bandes": bandes,
                "n": len(g), "sep": r["sep"], "ambigus": r["ambigus"],
                "seances": len({x["seance"] for x in cad})}
    return None


def a_derive_cadence(b, tirages=300):
    """Ce que les heures prennent à la cadence, à pente égale.

    Mesurée à l'intérieur de chaque séance, et sur les seules séances courues
    à allure tenue : un fractionné finit au calme, et sa fin de séance se
    lirait comme de la fatigue.
    """
    g = regulieres([x for x in propres(b)
                    if x.get("cad") and 60 <= x["cad"] <= 220
                    and x["ecoule"] >= ECHAUFFEMENT])
    ch = ["pente", "ecoule"]
    c = centre(g, ch + ["cad"])
    r = mco([[x[k] for k in ch] for x in c], [x["cad"] for x in c])
    if not r:
        return None
    random.seed(9)
    seances = sorted({x["seance"] for x in g})
    coefs = []
    for _ in range(tirages):
        e = []
        for i, s in enumerate(random.choice(seances) for _ in seances):
            e += [x | {"seance": f"{s}#{i}"} for x in g if x["seance"] == s]
        cc = centre(e, ch + ["cad"])
        rr = mco([[x[k] for k in ch] for x in cc], [x["cad"] for x in cc]) \
            if len(cc) > 200 else None
        if rr:
            coefs.append(rr[1] * 60)
    lo, hi = intervalle(coefs)
    return {"par_h": r[1] * 60, "lo": lo, "hi": hi,
            "n": len(c), "seances": len(seances)}


def croisement_pente(bandes, seuil):
    """La pente où la cadence passe sous le seuil, par interpolation.

    Entre deux tranches la cadence est supposée descendre en ligne droite :
    c'est la seule hypothèse que les données permettent, et elle ne porte que
    sur quelques points de pourcentage.
    """
    pts = [(q["x"], q["cad"]) for q in bandes if q.get("cad")]
    for (a, ca), (z, cz) in zip(pts, pts[1:]):
        if ca >= seuil > cz:
            return a + (ca - seuil) / (ca - cz) * (z - a), (ca - cz) / (z - a)
    return None, None
