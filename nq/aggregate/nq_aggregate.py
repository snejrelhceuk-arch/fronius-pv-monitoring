"""nq.aggregate.nq_aggregate — Kaskade nq_agg_10s/nq_raw_slow → 5min → hourly → daily (Rolle N).

Läuft alle 4h auf Primary (Timer pv-nq-aggregate.timer, Persistent=yes).
- Skalare (Block A+B):  nq_agg_10s → nq_5min → nq_hourly → nq_daily
- Harmonische:          nq_raw_slow → nq_5min → nq_hourly → nq_daily
  (quantity='', meas='U_LN'|'U_LL'|'I', phase 1–3, ord 1,3,5,...,31)

Start: python3 -m nq.aggregate.nq_aggregate {5min|hourly|daily|all}
Doku:  doc/netzqualitaet/NQ_MODUL.md §6.
"""
from __future__ import annotations

import argparse
import math
import os
import time

from nq.nq_common import load_config, open_db, PRIMARY_SCHEMA, BASE_DIR

_SCALAR_FILTER = "meas='' AND phase=0 AND ord=0"   # nur für nq_agg_10s-Lesepfad


def _month_dbs() -> list[str]:
    db_dir = os.path.join(BASE_DIR, "nq", "db")
    if not os.path.isdir(db_dir):
        return []
    return sorted(
        os.path.join(db_dir, f)
        for f in os.listdir(db_dir)
        if f.startswith("nq_") and f.endswith(".db")
    )


def _open_month(db_path: str):
    return open_db(db_path, PRIMARY_SCHEMA)


# ---------------------------------------------------------------------------
# Stufe 1a: nq_agg_10s → nq_5min (Skalare, quantity gefüllt)
# ---------------------------------------------------------------------------
def _run_5min(conn, cfg: dict) -> int:
    rows = conn.execute(
        "SELECT CAST(ts/300 AS INTEGER)*300 tb, quantity, meas, phase, ord, "
        "MIN(vmin), AVG(vavg), MAX(vmax), AVG(vavg*vavg), SUM(n) "
        "FROM nq_agg_10s WHERE " + _SCALAR_FILTER + " "
        "GROUP BY tb, quantity, meas, phase, ord ORDER BY tb"
    ).fetchall()
    if not rows:
        return 0
    upsert = []
    for tb, qty, meas, phase, ord_, vmin, vavg, vmax, vavg2, n in rows:
        vstd = math.sqrt(max(0.0, vavg2 - vavg * vavg)) if n and n > 1 else 0.0
        upsert.append((tb, qty, meas, phase, ord_, vmin, vavg, vmax, vstd, n))
    conn.executemany(
        "INSERT OR REPLACE INTO nq_5min "
        "(ts,quantity,meas,phase,ord,vmin,vavg,vmax,vstd,n) VALUES (?,?,?,?,?,?,?,?,?,?)",
        upsert,
    )
    conn.commit()
    days = cfg.get("retention", {}).get("primary_5min_days", 90)
    conn.execute("DELETE FROM nq_5min WHERE ts < ?", (int(time.time()) - days * 86400,))
    conn.commit()
    return len(upsert)


# ---------------------------------------------------------------------------
# Stufe 1b: nq_raw_slow → nq_5min (Harmonische, quantity='')
# ---------------------------------------------------------------------------
def _run_harm_5min(conn, cfg: dict) -> int:
    """Aggregiert Harmonische aus nq_raw_slow → nq_5min (quantity='', meas/phase/ord gefüllt)."""
    rows = conn.execute(
        "SELECT CAST(ts/300 AS INTEGER)*300 tb, meas, phase, ord, "
        "MIN(value), AVG(value), MAX(value), AVG(value*value), COUNT(*) "
        "FROM nq_raw_slow WHERE meas != '' "
        "GROUP BY tb, meas, phase, ord ORDER BY tb"
    ).fetchall()
    if not rows:
        return 0
    upsert = []
    for tb, meas, phase, ord_, vmin, vavg, vmax, vavg2, n in rows:
        vstd = math.sqrt(max(0.0, vavg2 - vavg * vavg)) if n > 1 else 0.0
        upsert.append((tb, '', meas, phase, ord_, vmin, vavg, vmax, vstd, n))
    conn.executemany(
        "INSERT OR REPLACE INTO nq_5min "
        "(ts,quantity,meas,phase,ord,vmin,vavg,vmax,vstd,n) VALUES (?,?,?,?,?,?,?,?,?,?)",
        upsert,
    )
    conn.commit()
    days = cfg.get("retention", {}).get("primary_5min_days", 90)
    conn.execute("DELETE FROM nq_5min WHERE ts < ?", (int(time.time()) - days * 86400,))
    conn.commit()
    return len(upsert)


# ---------------------------------------------------------------------------
# Stufe 2: nq_5min → nq_hourly (Skalare + Harmonische gemeinsam)
# ---------------------------------------------------------------------------
def _run_hourly(conn, cfg: dict) -> int:
    rows = conn.execute(
        "SELECT CAST(ts/3600 AS INTEGER)*3600 tb, quantity, meas, phase, ord, "
        "MIN(vmin), AVG(vavg), MAX(vmax), AVG(vavg*vavg), SUM(n) "
        "FROM nq_5min "
        "GROUP BY tb, quantity, meas, phase, ord ORDER BY tb"
    ).fetchall()
    if not rows:
        return 0
    upsert = []
    for tb, qty, meas, phase, ord_, vmin, vavg, vmax, vavg2, n in rows:
        vstd = math.sqrt(max(0.0, vavg2 - vavg * vavg)) if n and n > 1 else 0.0
        upsert.append((tb, qty, meas, phase, ord_, vmin, vavg, vmax, vstd, n))
    conn.executemany(
        "INSERT OR REPLACE INTO nq_hourly "
        "(ts,quantity,meas,phase,ord,vmin,vavg,vmax,vstd,n) VALUES (?,?,?,?,?,?,?,?,?,?)",
        upsert,
    )
    conn.commit()
    days = cfg.get("retention", {}).get("primary_hourly_days", 365)
    conn.execute("DELETE FROM nq_hourly WHERE ts < ?", (int(time.time()) - days * 86400,))
    conn.commit()
    return len(upsert)


# ---------------------------------------------------------------------------
# Stufe 3: nq_hourly → nq_daily (Skalare + Harmonische gemeinsam)
# ---------------------------------------------------------------------------
def _run_daily(conn, cfg: dict) -> int:
    rows = conn.execute(
        "SELECT date(ts,'unixepoch','localtime') day, quantity, meas, phase, ord, "
        "MIN(vmin), AVG(vavg), MAX(vmax), AVG(vavg*vavg), SUM(n) "
        "FROM nq_hourly "
        "GROUP BY day, quantity, meas, phase, ord ORDER BY day"
    ).fetchall()
    if not rows:
        return 0
    upsert = []
    for day, qty, meas, phase, ord_, vmin, vavg, vmax, vavg2, n in rows:
        vstd = math.sqrt(max(0.0, vavg2 - vavg * vavg)) if n and n > 1 else 0.0
        upsert.append((day, qty, meas, phase, ord_, vmin, vavg, vmax, vstd, n))
    conn.executemany(
        "INSERT OR REPLACE INTO nq_daily "
        "(day,quantity,meas,phase,ord,vmin,vavg,vmax,vstd,n) VALUES (?,?,?,?,?,?,?,?,?,?)",
        upsert,
    )
    conn.commit()
    days = cfg.get("retention", {}).get("primary_daily_days", 3650)
    conn.execute(
        "DELETE FROM nq_daily WHERE day < date('now','-' || ? || ' days','localtime')",
        (days,),
    )
    conn.commit()
    return len(upsert)


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------
def run(stage: str) -> dict:
    """Führt Aggregation für alle Monats-DBs aus.

    stage in {'5min', 'hourly', 'daily', 'all'}.
    '5min' aggregiert SOWOHL Skalare (nq_agg_10s) ALS AUCH Harmonische (nq_raw_slow).
    """
    cfg = load_config()
    dbs = _month_dbs()
    results: dict[str, int] = {}
    stages = ["5min", "hourly", "daily"] if stage == "all" else [stage]
    for db_path in dbs:
        conn = _open_month(db_path)
        total = 0
        for s in stages:
            if s == "5min":
                total += _run_5min(conn, cfg)
                total += _run_harm_5min(conn, cfg)
            elif s == "hourly":
                total += _run_hourly(conn, cfg)
            elif s == "daily":
                total += _run_daily(conn, cfg)
            else:
                raise ValueError(f"Unbekannte Stufe: {s!r} — erlaubt: 5min hourly daily all")
        conn.close()
        results[os.path.basename(db_path)] = total
    return results


def main() -> int:
    ap = argparse.ArgumentParser(
        description="NQ-Aggregationskaskade auf Primary (Rolle N)")
    ap.add_argument("stage", choices=["5min", "hourly", "daily", "all"],
                    help="Aggregationsstufe")
    a = ap.parse_args()
    result = run(a.stage)
    total = sum(result.values())
    print(f"[nq_aggregate] stage={a.stage} buckets={total} dbs={len(result)}")
    for db, n in result.items():
        print(f"  {db}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
