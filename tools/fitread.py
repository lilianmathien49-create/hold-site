#!/usr/bin/env python3
"""Lecteur minimal de fichiers FIT — juste ce qu'il faut pour une analyse de course.

Strava exporte les activités dans leur format d'origine. Tout ce qui vient d'une
montre arrive en .fit, un format binaire. Aucune bibliothèque n'étant disponible
ici, on le décode à la main.

On ne décode pas tout : seuls les messages « record », qui portent un point de
mesure par seconde. Le reste du fichier — tours, séances, réglages de l'appareil —
est sauté proprement en suivant les définitions.

Utilisable en ligne de commande pour inspecter un fichier :

    python3 tools/fitread.py une-sortie.fit
"""
from __future__ import annotations

import gzip, struct, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Le temps FIT compte les secondes depuis cette date, pas depuis 1970.
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
SEMI = 180.0 / (2 ** 31)          # semicercles vers degrés

# (taille en octets, format struct, valeur signifiant « absent »)
BASE = {
    0x00: (1, "B", 0xFF), 0x01: (1, "b", 0x7F), 0x02: (1, "B", 0xFF),
    0x83: (2, "h", 0x7FFF), 0x84: (2, "H", 0xFFFF),
    0x85: (4, "i", 0x7FFFFFFF), 0x86: (4, "I", 0xFFFFFFFF),
    0x07: (1, "s", 0x00), 0x88: (4, "f", None), 0x89: (8, "d", None),
    0x0A: (1, "B", 0x00), 0x8B: (2, "H", 0x00), 0x8C: (4, "I", 0x00),
    0x0D: (1, "B", 0xFF), 0x8E: (8, "q", 0x7FFFFFFFFFFFFFFF),
    0x8F: (8, "Q", 0xFFFFFFFFFFFFFFFF), 0x90: (8, "Q", 0x00),
}

RECORD_MSG = 20
# Champs utiles d'un message « record », avec leur conversion.
FIELDS = {
    253: ("t", lambda v: FIT_EPOCH + timedelta(seconds=v)),
    0: ("lat", lambda v: v * SEMI),
    1: ("lon", lambda v: v * SEMI),
    2: ("alt", lambda v: v / 5.0 - 500),
    3: ("hr", float),
    4: ("cad", float),
    5: ("dist", lambda v: v / 100.0),
    6: ("speed", lambda v: v / 1000.0),
    13: ("temp", float),
    73: ("speed", lambda v: v / 1000.0),      # version étendue, même sens
    78: ("alt", lambda v: v / 5.0 - 500),     # altitude étendue
    # Dynamique de course. Ces montres n'écrivent pas la cadence (champ 4),
    # mais elles écrivent la longueur de foulée : la cadence s'en déduit,
    # vitesse divisée par foulée. Vérifié sur une séance où la médiane tombe
    # à 154 pas/min, contre 156 affichés par la montre.
    39: ("oscillation", lambda v: v / 10.0),  # oscillation verticale, mm
    41: ("contact", lambda v: v / 10.0),      # temps de contact au sol, ms
    83: ("ratio_vert", lambda v: v / 100.0),  # ratio vertical, %
    85: ("foulee", lambda v: v / 10000.0),    # longueur de foulée, m
}

LAP_MSG = 19
# Les tours tels que la montre les a enregistrés. C'est la découpe du coureur,
# pas une reconstruction : une séance de 4 × 2 km a quatre tours de 2 km.
LAP_FIELDS = {
    253: ("fin", lambda v: FIT_EPOCH + timedelta(seconds=v)),
    2: ("debut", lambda v: FIT_EPOCH + timedelta(seconds=v)),
    7: ("duree", lambda v: v / 1000.0),
    9: ("dist", lambda v: v / 100.0),
    13: ("speed", lambda v: v / 1000.0),
    14: ("speed_max", lambda v: v / 1000.0),
    15: ("hr", float),
    16: ("hr_max", float),
    21: ("montee", float),
}


def _open(path: Path) -> bytes:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":                 # gzip : Strava compresse ses exports
        return gzip.decompress(raw)
    return raw


def read_laps(path: Path) -> list[dict]:
    """Les tours enregistrés par la montre, dans l'ordre."""
    return _lire(path, LAP_MSG, LAP_FIELDS)


def read_fit(path: Path) -> list[dict]:
    """Renvoie la liste des points de mesure, dans l'ordre du fichier."""
    return _lire(path, RECORD_MSG, FIELDS)


def _lire(path: Path, msg: int, champs: dict) -> list[dict]:
    """Décode un type de message et lui seul ; le reste du fichier est sauté."""
    buf = _open(Path(path))
    if len(buf) < 14 or buf[8:12] != b".FIT":
        return []
    hdr = buf[0]
    data_size = struct.unpack_from("<I", buf, 4)[0]
    pos, end = hdr, min(len(buf), hdr + data_size)

    defs: dict[int, tuple] = {}
    out: list[dict] = []
    last_ts = None

    while pos < end:
        h = buf[pos]
        pos += 1

        if h & 0x80:                           # en-tête à horodatage compressé
            local = (h >> 5) & 0x03
            offset = h & 0x1F
            d = defs.get(local)
            if not d:
                break                          # sans définition on ne sait plus avancer
            rec, pos, ts = _read_data(buf, pos, d, last_ts, offset, msg, champs)
            if ts is not None:
                last_ts = ts
            if rec is not None:
                out.append(rec)
            continue

        local = h & 0x0F
        if h & 0x40:                           # message de définition
            pos += 1                           # octet réservé
            endian = "<" if buf[pos] == 0 else ">"
            pos += 1
            gnum = struct.unpack_from(endian + "H", buf, pos)[0]
            pos += 2
            nfields = buf[pos]
            pos += 1
            fields = []
            for _ in range(nfields):
                fnum, size, base = buf[pos], buf[pos + 1], buf[pos + 2]
                pos += 3
                fields.append((fnum, size, base))
            if h & 0x20:                       # champs développeur : on note leur taille
                ndev = buf[pos]
                pos += 1
                for _ in range(ndev):
                    fields.append((-1, buf[pos + 1], 0x0D))
                    pos += 3
            defs[local] = (gnum, endian, fields)
            continue

        d = defs.get(local)
        if not d:
            break
        rec, pos, ts = _read_data(buf, pos, d, last_ts, None, msg, champs)
        if ts is not None:
            last_ts = ts
        if rec is not None:
            out.append(rec)

    return out


def _read_data(buf, pos, d, last_ts, offset, msg=RECORD_MSG, champs=None):
    """Lit un message de données. Renvoie (point ou None, position, horodatage)."""
    champs = FIELDS if champs is None else champs
    gnum, endian, fields = d
    rec = {} if gnum == msg else None
    ts = None
    for fnum, size, base in fields:
        spec = BASE.get(base)
        if spec is None or size <= 0:
            pos += size
            continue
        width, fmt, invalid = spec
        if rec is None or fnum not in champs or size != width:
            pos += size                        # champ inutile, ou tableau : on saute
            continue
        try:
            raw = struct.unpack_from(endian + fmt, buf, pos)[0]
        except struct.error:
            pos += size
            continue
        pos += size
        if invalid is not None and raw == invalid:
            continue
        name, conv = champs[fnum]
        try:
            val = conv(raw)
        except (ValueError, OverflowError, OSError):
            continue
        if name == "t":
            ts = val
        rec[name] = val

    if rec is not None and offset is not None and last_ts is not None and "t" not in rec:
        # Horodatage compressé : cinq bits de décalage sur le dernier connu.
        prev = int((last_ts - FIT_EPOCH).total_seconds())
        rolled = (prev & ~0x1F) | offset
        if rolled < prev:
            rolled += 0x20
        rec["t"] = ts = FIT_EPOCH + timedelta(seconds=rolled)
    return (rec if rec else None), pos, ts


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    pts = read_fit(Path(sys.argv[1]))
    if not pts:
        print("Aucun point lisible — ce n'est peut-être pas un fichier FIT.")
        return 1
    have = lambda k: sum(1 for p in pts if k in p)
    print(f"  {len(pts)} points de mesure")
    for k, label in (("t", "horodatage"), ("lat", "position"), ("alt", "altitude"),
                     ("hr", "fréquence cardiaque"), ("cad", "cadence"),
                     ("temp", "température"), ("dist", "distance")):
        n = have(k)
        print(f"    {label:22s} {n:6d}  ({n/len(pts)*100:5.1f} %)")
    withpos = [p for p in pts if "lat" in p and "t" in p]
    if withpos:
        a, b = withpos[0], withpos[-1]
        print(f"\n  du {a['t']:%d/%m/%Y %H:%M} au {b['t']:%H:%M}  "
              f"({(b['t']-a['t']).total_seconds()/60:.0f} min)")
        alts = [p["alt"] for p in pts if "alt" in p]
        if alts:
            print(f"  altitude de {min(alts):.0f} à {max(alts):.0f} m")
        hrs = [p["hr"] for p in pts if "hr" in p]
        if hrs:
            print(f"  FC de {min(hrs):.0f} à {max(hrs):.0f} bpm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
