#!/usr/bin/env python3
"""nq.transfer.nq_sm_backfill — Einmaliger SM-Netzqualitaets-Backfill (Rolle N).

Vor PAC-Start (< 2026-07) lief die Netzkriterien-Ansicht auf dem primaeren
Smart-Meter. Diese SM-Werte liegen als 15-min-Aggregate in ``data_15min`` — dort
aber nur mit 90-Tage-Retention (``config.DATA_15MIN_RETENTION_DAYS``). Dieses
Skript sammelt die historischen ``data_15min``-Zeilen aus mehreren Backup-DBs +
der Live-DB und schreibt sie **permanent** in ``nq/db/nq_YYYY-MM.db`` →
``nq_sm_15min`` (retention-frei, nicht Teil der PAC-Kaskade).

Spannungen werden Leiter-Neutral → Leiter-Leiter umgerechnet (x sqrt(3), wie der
Netzkriterien-Fallback ``routes/pac4200.py:_core_fallback_rows``).

Eigenschaften:
- **Read-only** auf alle Quell-DBs; schreibt nur in ``nq/db/nq_YYYY-MM.db``.
- **Idempotent** (``INSERT OR REPLACE`` auf ts-PK); mehrfacher Lauf = gleiches Ergebnis.
- **Dry-Run per Default**; tatsaechliche Schreibvorgaenge nur mit ``--commit``.
- Quellen werden in Prioritaetsreihenfolge gemerged (erste gewinnt je ts).

Start:  python3 -m nq.transfer.nq_sm_backfill [--from YYYY-MM-DD] [--to YYYY-MM-DD]
                                             [--source PFAD ...] [--commit]
Doku:   doc/llm/cards/netzqualitaet-nq-aggregation.card.md
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time

from nq.nq_common import open_db, PRIMARY_SCHEMA

try:
    import config as _pvconfig
except Exception:  # pragma: no cover
    _pvconfig = None

RT3 = 1.7320508075688772  # sqrt(3): L-N -> L-L
DEFAULT_FROM = "2026-01-01"
DEFAULT_TO = "2026-07-01"  # PAC-Start; davor = SM-Territorium


def _base_dir() -> str:
    if _pvconfig is not None:
        return _pvconfig.BASE_DIR
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _db_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db")


def _day_ts(day: str) -> int:
    t = time.strptime(day, "%Y-%m-%d")
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))


def _default_sources() -> list[str]:
    """Live-DB + Archiv + Monats-Backups (nur existierende), Prioritaet: Live zuerst.

    Host-spezifische Voll-Archive werden **nicht** hart kodiert, sondern optional
    ueber ``PV_NQ_SM_SOURCES`` (``:``-getrennt) oder ``--source`` eingespeist.
    """
    base = _base_dir()
    candidates = [os.path.join(base, "data.db")]              # Live (persistent SD)
    env_src = os.environ.get("PV_NQ_SM_SOURCES", "")
    candidates += [p for p in env_src.split(":") if p.strip()]  # externe Voll-Archive
    candidates += [
        os.path.join(base, "tmp", "backup_restore", "data_2026-06.db"),
        os.path.join(base, "tmp", "backup_restore", "data_2026-05.db"),
        os.path.join(base, "tmp", "backup_restore", "data_2026-04.db"),
        os.path.join(base, "tmp", "backup_restore", "data_2026-03.db"),
    ]
    return [p for p in candidates if os.path.exists(p)]


def _read_source(path: str, ts_from: int, ts_to: int) -> dict[int, tuple]:
    """Liest data_15min (SM) aus einer Quelle. Gibt {ts: (u12,u12mn,u12mx, ...,
    freq,freqmn,freqmx)} zurueck (bereits L-L umgerechnet)."""
    out: dict[int, tuple] = {}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
    except Exception:
        return out
    try:
        rows = conn.execute(
            "SELECT ts, "
            "U_L1_N_Netz_avg, U_L1_N_Netz_min, U_L1_N_Netz_max, "
            "U_L2_N_Netz_avg, U_L2_N_Netz_min, U_L2_N_Netz_max, "
            "U_L3_N_Netz_avg, U_L3_N_Netz_min, U_L3_N_Netz_max, "
            "f_Netz_avg, f_Netz_min, f_Netz_max "
            "FROM data_15min WHERE ts >= ? AND ts < ? AND f_Netz_avg IS NOT NULL "
            "ORDER BY ts",
            (ts_from, ts_to),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()

    def _ll(v):
        return (v * RT3) if v is not None else None

    for (ts, u1a, u1n, u1x, u2a, u2n, u2x, u3a, u3n, u3x,
         fa, fn, fx) in rows:
        out[int(ts)] = (
            _ll(u1a), _ll(u1n), _ll(u1x),
            _ll(u2a), _ll(u2n), _ll(u2x),
            _ll(u3a), _ll(u3n), _ll(u3x),
            fa, fn, fx,
        )
    return out


def backfill(day_from: str, day_to: str, sources: list[str], commit: bool) -> dict:
    ts_from, ts_to = _day_ts(day_from), _day_ts(day_to)
    merged: dict[int, tuple] = {}
    per_source: list[tuple[str, int]] = []
    for src in sources:
        rows = _read_source(src, ts_from, ts_to)
        added = 0
        for ts, tup in rows.items():
            if ts not in merged:
                merged[ts] = tup
                added += 1
        per_source.append((src, added))

    # Nach Monat (localtime) gruppieren.
    by_month: dict[str, list[tuple]] = {}
    for ts, tup in merged.items():
        key = time.strftime("%Y-%m", time.localtime(ts))
        by_month.setdefault(key, []).append((ts, *tup))

    written: dict[str, int] = {}
    for month, recs in sorted(by_month.items()):
        db_path = os.path.join(_db_dir(), f"nq_{month}.db")
        if commit:
            conn = open_db(db_path, PRIMARY_SCHEMA)
            try:
                conn.executemany(
                    "INSERT OR REPLACE INTO nq_sm_15min "
                    "(ts, u_l12,u_l12_min,u_l12_max, u_l23,u_l23_min,u_l23_max, "
                    "u_l31,u_l31_min,u_l31_max, freq,freq_min,freq_max, origin) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'sm_15min')",
                    sorted(recs),
                )
                conn.commit()
            finally:
                conn.close()
        written[month] = len(recs)

    return {
        "range": (day_from, day_to),
        "sources": per_source,
        "total_ts": len(merged),
        "by_month": written,
        "committed": commit,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="SM-Netzqualitaets-Backfill in nq_sm_15min (Rolle N).")
    ap.add_argument("--from", dest="day_from", default=DEFAULT_FROM)
    ap.add_argument("--to", dest="day_to", default=DEFAULT_TO)
    ap.add_argument("--source", dest="sources", action="append", default=None,
                    help="Quell-DB (mehrfach). Default: Live + Archiv + Backups.")
    ap.add_argument("--commit", action="store_true", help="Tatsaechlich schreiben (sonst Dry-Run).")
    args = ap.parse_args()

    sources = args.sources if args.sources else _default_sources()
    if not sources:
        print("FEHLER: keine Quell-DBs gefunden.")
        return 2

    res = backfill(args.day_from, args.day_to, sources, args.commit)
    mode = "COMMIT" if res["committed"] else "DRY-RUN"
    print(f"[{mode}] SM-Backfill {res['range'][0]} .. {res['range'][1]}")
    print("Quellen (neu beigetragene ts):")
    for src, n in res["sources"]:
        print(f"  + {n:6d}  {src}")
    print(f"Gesamt eindeutige 15-min-Buckets: {res['total_ts']}")
    print("Pro Monat -> nq_sm_15min:")
    for month, n in sorted(res["by_month"].items()):
        print(f"  {month}: {n}")
    if not res["committed"]:
        print("\nHinweis: Dry-Run. Mit --commit tatsaechlich schreiben.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
