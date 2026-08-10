#!/usr/bin/env python3
"""nq.analysis.nq_pattern — Sauberer Musteranalyse-Datensatz (Rolle N, Primary).

Erzeugt den **permanenten, bereinigten** Netz-Signaldatensatz `nq_pattern_5min`
aus `nq_5min` (PAC4200). Ziel: die für die Musteranalyse (Aufschwingen im Netz,
Reflexionen an Netzgrenzen, LF-Schwingungspakete) störenden **internen** Effekte
(hinter dem Netzanschlusspunkt: Lastsprünge → IR-Spannungsabfall) entfernen und
das **netzseitige (externe)** Signal übrig lassen.

Wissenschaftliche Methode (Residual-/Deconvolution-Filter, Ohmsches Gesetz +
Superposition, Standard-Netzspannungsabfall-Formel):

    ΔU_intern_Lx = I_Lx · (R·cosφ_Lx + X·sinφ_Lx)          [V]
    U_grid_Lx    = U_gemessen_Lx + ΔU_intern_Lx            (interner Abfall zurück-addiert)

mit der am Hausanschluss gemessenen Schleifenimpedanz Z = R + jX aus
`config/nq_impedance.json`. Die **Frequenz f** ist systemweit → keine Korrektur.
PF/φ werden als Kontext mitgeführt. Pro Bucket wird `origin` gesetzt
(`intern`, wenn der interne Abfall den Schwellwert überschreitet, sonst `extern`).

Die Rohwerte (`nq_5min`) bleiben unverändert; `nq_pattern_5min` ist die
saubere, permanent verfügbare Ableitung.

Start:  python3 -m nq.analysis.nq_pattern [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--day YYYY-MM-DD]
Doku:   doc/netzqualitaet/NQ_MODUL.md §8.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sqlite3
import time

from nq.nq_common import open_db, PRIMARY_SCHEMA, BASE_DIR, load_config

# Skalar-Größen (meas='' , phase=0, ord=0), die wir pro Bucket brauchen.
_NEEDED = (
    "U_L1N", "U_L2N", "U_L3N",
    "Is_L1", "Is_L2", "Is_L3",
    "cosphi_L1", "cosphi_L2", "cosphi_L3",
    "PF_L1", "PF_L2", "PF_L3",
    "FREQ", "Q_tot",
)
_DEFAULT_ORIGIN_DU_V = 1.5   # |ΔU_intern| über diesem Wert → Bucket 'intern'


def _db_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")


def _load_impedance() -> tuple[float, float]:
    """R, X der Schleifenimpedanz [Ω] aus config/nq_impedance.json (mΩ → Ω)."""
    path = os.path.join(BASE_DIR, "config", "nq_impedance.json")
    try:
        with open(path, encoding="utf-8") as f:
            z = json.load(f)
        return float(z.get("R_mOhm", 163)) / 1000.0, float(z.get("X_mOhm", 251)) / 1000.0
    except Exception:
        return 0.163, 0.251


def _origin_threshold() -> float:
    try:
        return float(load_config().get("analysis", {}).get("origin_internal_du_v", _DEFAULT_ORIGIN_DU_V))
    except Exception:
        return _DEFAULT_ORIGIN_DU_V


def _pivot_5min(db_path: str, t0: int, t1: int) -> dict[int, dict]:
    """{ts: {quantity: vavg}} aus nq_5min-Skalaren im Fenster [t0,t1)."""
    out: dict[int, dict] = {}
    if not os.path.exists(db_path):
        return out
    try:
        c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    except Exception:
        return out
    try:
        q = ",".join("?" * len(_NEEDED))
        rows = c.execute(
            f"SELECT ts, quantity, vavg, n FROM nq_5min "
            f"WHERE meas='' AND phase=0 AND ord=0 AND quantity IN ({q}) "
            f"AND ts >= ? AND ts < ?",
            (*_NEEDED, t0, t1),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        c.close()
    for ts, qty, vavg, n in rows:
        b = out.setdefault(ts, {"_n": 0})
        b[qty] = vavg
        if n:
            b["_n"] = max(b["_n"], n)
    return out


def _clean_bucket(b: dict, r: float, x: float, origin_thr: float) -> dict | None:
    """Berechnet u_clean/phi/origin für einen 5-min-Bucket. None ohne U-Daten."""
    u = {p: b.get(f"U_L{p}N") for p in (1, 2, 3)}
    if all(v is None for v in u.values()):
        return None
    q_sign = 1.0
    if b.get("Q_tot") is not None:
        q_sign = 1.0 if b["Q_tot"] >= 0 else -1.0

    res = {"u_meas": {}, "u_clean": {}, "pf": {}, "phi": {}, "i": {}, "du_int": {}}
    for p in (1, 2, 3):
        um = u[p]
        i = b.get(f"Is_L{p}")
        cosphi = b.get(f"cosphi_L{p}")
        if cosphi is None:
            cosphi = b.get(f"PF_L{p}")
        res["u_meas"][p] = um
        res["i"][p] = i
        if cosphi is None:
            cosphi = 1.0
        cosphi = max(-1.0, min(1.0, float(cosphi)))
        sinphi = q_sign * math.sqrt(max(0.0, 1.0 - cosphi * cosphi))
        res["pf"][p] = round(cosphi, 4)
        res["phi"][p] = round(math.degrees(math.acos(cosphi)) * (1.0 if sinphi >= 0 else -1.0), 2)
        if um is None or i is None:
            res["u_clean"][p] = um
            res["du_int"][p] = 0.0
        else:
            du_int = i * (r * cosphi + x * sinphi)   # V (R,X in Ω, I in A)
            res["u_clean"][p] = round(um + du_int, 4)
            res["du_int"][p] = du_int
    du_max = max((abs(v) for v in res["du_int"].values()), default=0.0)
    res["du_int_max"] = round(du_max, 4)
    res["origin"] = "intern" if du_max > origin_thr else "extern"
    res["freq"] = b.get("FREQ")
    res["n"] = b.get("_n", 0)
    return res


def build_range(start_ts: int, end_ts: int, commit: bool = True) -> dict:
    """Erzeugt nq_pattern_5min für [start_ts, end_ts). Idempotent (INSERT OR REPLACE)."""
    r, x = _load_impedance()
    thr = _origin_threshold()
    now = int(time.time())
    written = 0
    intern = 0
    conns: dict[str, sqlite3.Connection] = {}

    def _conn(month: str) -> sqlite3.Connection:
        if month not in conns:
            conns[month] = open_db(os.path.join(_db_dir(), f"nq_{month}.db"), PRIMARY_SCHEMA)
        return conns[month]

    try:
        # Monatsweise über die betroffenen Monats-DBs iterieren.
        for db_path in sorted(glob.glob(os.path.join(_db_dir(), "nq_*.db"))):
            month = os.path.basename(db_path)[3:10]  # YYYY-MM
            piv = _pivot_5min(db_path, start_ts, end_ts)
            if not piv:
                continue
            conn = _conn(month)
            for ts in sorted(piv):
                res = _clean_bucket(piv[ts], r, x, thr)
                if res is None:
                    continue
                if res["origin"] == "intern":
                    intern += 1
                if commit:
                    conn.execute(
                        "INSERT OR REPLACE INTO nq_pattern_5min "
                        "(ts, u_clean_l1,u_clean_l2,u_clean_l3, u_meas_l1,u_meas_l2,u_meas_l3, "
                        " freq, pf_l1,pf_l2,pf_l3, phi_l1,phi_l2,phi_l3, i_l1,i_l2,i_l3, "
                        " du_int_max, origin, n_samples, src, created_ts) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ts,
                         res["u_clean"][1], res["u_clean"][2], res["u_clean"][3],
                         res["u_meas"][1], res["u_meas"][2], res["u_meas"][3],
                         res["freq"], res["pf"][1], res["pf"][2], res["pf"][3],
                         res["phi"][1], res["phi"][2], res["phi"][3],
                         res["i"][1], res["i"][2], res["i"][3],
                         res["du_int_max"], res["origin"], res["n"], "pac_residual", now),
                    )
                written += 1
        if commit:
            for conn in conns.values():
                conn.commit()
    finally:
        for conn in conns.values():
            conn.close()
    return {"written": written, "intern": intern, "extern": written - intern,
            "r_ohm": r, "x_ohm": x, "origin_thr_v": thr, "commit": commit}


def _day_bounds(day: str) -> tuple[int, int]:
    t = time.strptime(day, "%Y-%m-%d")
    t0 = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
    return t0, t0 + 86400


def build_day(day: str, commit: bool = True) -> dict:
    t0, t1 = _day_bounds(day)
    res = build_range(t0, t1, commit)
    res["day"] = day
    return res


def main() -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="NQ Musteranalyse-Datensatz (residual-bereinigt)")
    ap.add_argument("--day", default=None, help="YYYY-MM-DD (Default: gestern)")
    ap.add_argument("--from", dest="from_day", default=None, help="Backfill-Start YYYY-MM-DD")
    ap.add_argument("--to", dest="to_day", default=None, help="Backfill-Ende YYYY-MM-DD (inkl.)")
    a = ap.parse_args()
    if a.from_day or a.to_day:
        t0, _ = _day_bounds(a.from_day or "2026-01-01")
        _, t1 = _day_bounds(a.to_day or time.strftime("%Y-%m-%d"))
        print(json.dumps(build_range(t0, t1), ensure_ascii=False, indent=2))
        return 0
    day = a.day or time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    print(json.dumps(build_day(day), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
