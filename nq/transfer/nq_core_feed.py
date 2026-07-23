"""nq.transfer.nq_core_feed - Fuellt NQ-DB mit passenden Kern-DB-Groessen.

Ziel:
- Kein Anzeige-Fallback, sondern echte Daten in NQ-Primary-DBs.
- Fuellt nur Luecken (INSERT OR IGNORE), ueberschreibt keine PAC-Werte.
- Quelle: data.db:data_1min (read-only)
- Ziel:   nq/db/nq_YYYY-MM.db (nq_5min + Rollup nq_hourly/nq_daily)

Gemappte Groessen:
- FREQ  <- f_Netz_*  (identische Groesse)
- U_L12 <- U_L1_N_Netz_* * sqrt(3)
- U_L23 <- U_L2_N_Netz_* * sqrt(3)
- U_L31 <- U_L3_N_Netz_* * sqrt(3)

Hinweis:
Die L-L-Spannungen werden aus L-N der Kern-DB abgeleitet, weil die Kern-DB
ueblicherweise nur L-N fuehrt.
"""
from __future__ import annotations

import argparse
import math
import os
import sqlite3
import time
from collections import defaultdict

from nq.nq_common import BASE_DIR, open_db, PRIMARY_SCHEMA


SQRT3 = 1.7320508075688772


def _core_db_path() -> str:
    return os.path.join(BASE_DIR, "data.db")


def _nq_db_path(ts: int) -> str:
    m = time.localtime(ts)
    return os.path.join(BASE_DIR, "nq", "db", f"nq_{m.tm_year:04d}-{m.tm_mon:02d}.db")


def _aggregate_core_5min(start_ts: int, end_ts: int) -> list[tuple]:
    """Liest Kern-DB 1min und aggregiert auf 5min-Buckets."""
    core = sqlite3.connect(f"file:{_core_db_path()}?mode=ro", uri=True, timeout=10.0)
    try:
        rows = core.execute(
            "SELECT CAST(ts/300 AS INTEGER)*300 tb, "
            "MIN(U_L1_N_Netz_min), AVG(U_L1_N_Netz_avg), MAX(U_L1_N_Netz_max), "
            "MIN(U_L2_N_Netz_min), AVG(U_L2_N_Netz_avg), MAX(U_L2_N_Netz_max), "
            "MIN(U_L3_N_Netz_min), AVG(U_L3_N_Netz_avg), MAX(U_L3_N_Netz_max), "
            "MIN(f_Netz_min), AVG(f_Netz_avg), MAX(f_Netz_max), "
            "COUNT(*) n "
            "FROM data_1min "
            "WHERE ts >= ? AND ts < ? "
            "GROUP BY tb ORDER BY tb",
            (start_ts, end_ts),
        ).fetchall()
    finally:
        core.close()
    return rows


def _rows_for_bucket(tb: int, row: tuple) -> list[tuple]:
    """Baut nq_5min-Zeilen (quantity, vmin/vavg/vmax, n) fuer einen Bucket."""
    (
        _tb,
        u1min, u1avg, u1max,
        u2min, u2avg, u2max,
        u3min, u3avg, u3max,
        fmin, favg, fmax,
        n,
    ) = row

    out = []

    def add(q: str, vmin, vavg, vmax):
        if vavg is None:
            return
        out.append((tb, q, "", 0, 0, vmin, vavg, vmax, 0.0, int(n or 0)))

    add("FREQ", fmin, favg, fmax)

    # L-N -> L-L via sqrt(3)
    if u1avg is not None:
        add("U_L12",
            (u1min * SQRT3) if u1min is not None else None,
            u1avg * SQRT3,
            (u1max * SQRT3) if u1max is not None else None)
    if u2avg is not None:
        add("U_L23",
            (u2min * SQRT3) if u2min is not None else None,
            u2avg * SQRT3,
            (u2max * SQRT3) if u2max is not None else None)
    if u3avg is not None:
        add("U_L31",
            (u3min * SQRT3) if u3min is not None else None,
            u3avg * SQRT3,
            (u3max * SQRT3) if u3max is not None else None)

    return out


def _rollup_hourly_daily(conn: sqlite3.Connection, start_ts: int, end_ts: int) -> tuple[int, int]:
    """Rollup nur fuer die gemappten Kern-Groessen in betroffenem Zeitfenster."""
    touched = ("FREQ", "U_L12", "U_L23", "U_L31")
    t0h = (start_ts // 3600) * 3600
    t1h = ((end_ts + 3599) // 3600) * 3600

    rows_h = conn.execute(
        "SELECT CAST(ts/3600 AS INTEGER)*3600 tb, quantity, "
        "MIN(vmin), AVG(vavg), MAX(vmax), AVG(vavg*vavg), SUM(n) "
        "FROM nq_5min "
        "WHERE ts >= ? AND ts < ? AND quantity IN (?,?,?,?) AND meas='' AND phase=0 AND ord=0 "
        "GROUP BY tb, quantity",
        (t0h, t1h, *touched),
    ).fetchall()

    up_h = []
    for tb, q, vmin, vavg, vmax, vavg2, n in rows_h:
        vstd = math.sqrt(max(0.0, (vavg2 or 0.0) - (vavg or 0.0) * (vavg or 0.0))) if (n or 0) > 1 else 0.0
        up_h.append((tb, q, "", 0, 0, vmin, vavg, vmax, vstd, int(n or 0)))

    if up_h:
        conn.executemany(
            "INSERT OR REPLACE INTO nq_hourly "
            "(ts,quantity,meas,phase,ord,vmin,vavg,vmax,vstd,n) VALUES (?,?,?,?,?,?,?,?,?,?)",
            up_h,
        )

    # daily from hourly for touched quantities
    day_start = time.strftime("%Y-%m-%d", time.localtime(start_ts))
    day_end = time.strftime("%Y-%m-%d", time.localtime(max(start_ts, end_ts - 1)))
    rows_d = conn.execute(
        "SELECT date(ts,'unixepoch','localtime') day, quantity, "
        "MIN(vmin), AVG(vavg), MAX(vmax), AVG(vavg*vavg), SUM(n) "
        "FROM nq_hourly "
        "WHERE date(ts,'unixepoch','localtime') >= ? AND date(ts,'unixepoch','localtime') <= ? "
        "AND quantity IN (?,?,?,?) AND meas='' AND phase=0 AND ord=0 "
        "GROUP BY day, quantity",
        (day_start, day_end, *touched),
    ).fetchall()

    up_d = []
    for day, q, vmin, vavg, vmax, vavg2, n in rows_d:
        vstd = math.sqrt(max(0.0, (vavg2 or 0.0) - (vavg or 0.0) * (vavg or 0.0))) if (n or 0) > 1 else 0.0
        up_d.append((day, q, "", 0, 0, vmin, vavg, vmax, vstd, int(n or 0)))

    if up_d:
        conn.executemany(
            "INSERT OR REPLACE INTO nq_daily "
            "(day,quantity,meas,phase,ord,vmin,vavg,vmax,vstd,n) VALUES (?,?,?,?,?,?,?,?,?,?)",
            up_d,
        )

    conn.commit()
    return len(up_h), len(up_d)


def feed_core_to_nq(start_ts: int, end_ts: int) -> dict:
    rows = _aggregate_core_5min(start_ts, end_ts)
    by_db: dict[str, list[tuple]] = defaultdict(list)
    for r in rows:
        tb = int(r[0])
        payload = _rows_for_bucket(tb, r)
        if payload:
            by_db[_nq_db_path(tb)].extend(payload)

    stats = {
        "buckets": len(rows),
        "inserted_5min": 0,
        "rolled_hourly": 0,
        "rolled_daily": 0,
        "dbs": 0,
    }

    for db_path, payload in by_db.items():
        conn = open_db(db_path, PRIMARY_SCHEMA)
        cur = conn.executemany(
            "INSERT OR IGNORE INTO nq_5min "
            "(ts,quantity,meas,phase,ord,vmin,vavg,vmax,vstd,n) VALUES (?,?,?,?,?,?,?,?,?,?)",
            payload,
        )
        inserted = cur.rowcount if hasattr(cur, "rowcount") else 0
        h, d = _rollup_hourly_daily(conn, start_ts, end_ts)
        conn.close()

        stats["inserted_5min"] += max(0, inserted)
        stats["rolled_hourly"] += h
        stats["rolled_daily"] += d
        stats["dbs"] += 1

    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Fill NQ DB from core DB matching quantities")
    ap.add_argument("--days", type=int, default=7, help="Lookback days from now (default 7)")
    ap.add_argument("--start-ts", type=int, default=None, help="Unix start timestamp (overrides --days)")
    ap.add_argument("--end-ts", type=int, default=None, help="Unix end timestamp (default now)")
    a = ap.parse_args()

    end_ts = int(a.end_ts or time.time())
    start_ts = int(a.start_ts or (end_ts - max(1, a.days) * 86400))
    stats = feed_core_to_nq(start_ts, end_ts)
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
