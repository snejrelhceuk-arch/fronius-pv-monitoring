#!/usr/bin/env python3
"""
build_stats_db.py — Permanenter 5-Minuten-Tagesdaten-Speicher (STATS-DB).

Zweck (Task C, 2026-07-02):
  Die Tag-Charts lesen `data_1min` (Retention 90 Tage). Ältere Tage sind daher
  nicht mehr darstellbar. Dieses Werkzeug pflegt eine **permanente** STATS-DB
  auf SD (`data_stats.db`) mit einer 5-Minuten-Downsample-Tabelle
  `data_5min_permanent` (Schema = aktuelles `data_1min`), aus der die Web-API
  ältere Tage bedient (via ATTACH, read-only). Die RAM-DB bleibt klein.

Modi:
  --backfill      Alle via --source angegebenen Quellen komplett verarbeiten
                  (idempotent, INSERT OR REPLACE je 5-min-Bucket).
  --archive-daily Gestrigen Tag aus der Live-RAM-DB nachführen (für Cron) —
                  inkl. per-Gerät-Leistungskurven (Fritz!DECT + Wattpilot).
  --day D         Nur diesen Tag (YYYY-MM-DD) verarbeiten.
  --devices-full  Per-Gerät-5-min-Tabellen aus dem vollen Live-Retention-Fenster
                  rekonstruieren (Fritz ~7 T, Wattpilot ~90 T).

Zieltabellen in data_stats.db:
  data_5min_permanent       (5-min-Downsample, Schema = data_1min)
  fritzdect_5min_permanent  (ts, device_id, power_w_avg/max, energy_total_wh)
  wattpilot_5min_permanent  (ts, power_w_avg/max)

Downsample-Regeln (nach Spalten-Suffix/Präfix):
  *_delta, W_* → SUM   |   *_avg, P_*, I_* → AVG
  *_min, *_start → MIN |   *_max, *_end → MAX   |   sonst AVG

Beispiel Backfill:
  python3 tools/build_stats_db.py --backfill \
      --source /dev/shm/fronius_data.db:data_1min \
      --source /tmp/stage/data_2026-04.db:data_1min \
      --source /tmp/stage/data_2026-02-08.db:data_1min_old

Siehe: doc/system/TAGESDATEN_HALTBARKEIT.md, doc/collector/DB_SCHEMA.md
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
import config  # noqa: E402

STATS_DB_DEFAULT = config.STATS_DB_PATH  # Stufe-2-DB (monitoring.db)
TARGET_TABLE = 'data_5min_permanent'
FRITZ_TABLE = 'fritzdect_5min_permanent'
WATTPILOT_TABLE = 'wattpilot_5min_permanent'
BUCKET_S = 300  # 5 Minuten
LIVE_DB = config.DB_PATH


def _target_columns(live_db: str) -> list[tuple[str, str]]:
    """(name, type) der aktuellen data_1min-Spalten = Ziel-Schema."""
    conn = sqlite3.connect(f'file:{live_db}?mode=ro', uri=True, timeout=10.0)
    try:
        rows = conn.execute("PRAGMA table_info(data_1min)").fetchall()
    finally:
        conn.close()
    return [(r[1], r[2] or 'REAL') for r in rows]


def _agg_for(col: str) -> str | None:
    """SQLite-Aggregat für eine Spalte; None = ts (Bucket-Key)."""
    if col == 'ts':
        return None
    if col.endswith('_delta') or col.startswith('W_'):
        return 'SUM'
    if col.endswith('_min') or col.endswith('_start'):
        return 'MIN'
    if col.endswith('_max') or col.endswith('_end'):
        return 'MAX'
    # _avg, P_*, I_*, PF_*, U_*, f_*, SOC_* … → AVG
    return 'AVG'


def _ensure_target(stats_db: str, cols: list[tuple[str, str]]) -> None:
    conn = sqlite3.connect(stats_db, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        coldefs = ',\n  '.join(
            f'"{n}" {t}' + (' PRIMARY KEY' if n == 'ts' else '') for n, t in cols
        )
        conn.execute(f'CREATE TABLE IF NOT EXISTS {TARGET_TABLE} (\n  {coldefs}\n)')
        # Falls Ziel bereits existiert: fehlende Spalten additiv ergänzen.
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({TARGET_TABLE})")}
        for n, t in cols:
            if n not in have:
                conn.execute(f'ALTER TABLE {TARGET_TABLE} ADD COLUMN "{n}" {t}')
        conn.execute(f'CREATE INDEX IF NOT EXISTS idx_5min_ts ON {TARGET_TABLE}(ts)')
        conn.commit()
    finally:
        conn.close()


def _source_columns(src_db: str, table: str) -> set[str]:
    conn = sqlite3.connect(f'file:{src_db}?mode=ro', uri=True, timeout=10.0)
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def process_source(stats_db: str, src_db: str, table: str,
                   target_cols: list[tuple[str, str]],
                   ts_from: float | None = None, ts_to: float | None = None) -> int:
    """Downsample einer Quelle → data_5min_permanent (INSERT OR REPLACE)."""
    src_cols = _source_columns(src_db, table)
    if 'ts' not in src_cols:
        print(f"  [skip] {src_db}:{table} — keine ts-Spalte")
        return 0
    # Nur Spalten verarbeiten, die in Quelle UND Ziel vorhanden sind.
    use = [(n, _agg_for(n)) for (n, _t) in target_cols if n in src_cols and n != 'ts']
    select_parts = ["CAST(ts / %d AS INTEGER) * %d AS ts" % (BUCKET_S, BUCKET_S)]
    for n, agg in use:
        select_parts.append(f'{agg}("{n}") AS "{n}"')
    where = []
    params: list = []
    if ts_from is not None:
        where.append("ts >= ?"); params.append(ts_from)
    if ts_to is not None:
        where.append("ts < ?"); params.append(ts_to)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    query = (f"SELECT {', '.join(select_parts)} FROM {table} {where_sql} "
             f"GROUP BY CAST(ts / {BUCKET_S} AS INTEGER)")

    src = sqlite3.connect(f'file:{src_db}?mode=ro', uri=True, timeout=30.0)
    dst = sqlite3.connect(stats_db, timeout=60.0)
    try:
        rows = src.execute(query, params).fetchall()
        if not rows:
            print(f"  [empty] {os.path.basename(src_db)}:{table}")
            return 0
        colnames = ['ts'] + [n for n, _a in use]
        placeholders = ','.join('?' * len(colnames))
        collist = ','.join(f'"{c}"' for c in colnames)
        dst.executemany(
            f"INSERT OR REPLACE INTO {TARGET_TABLE} ({collist}) VALUES ({placeholders})",
            rows,
        )
        dst.commit()
        print(f"  [ok]   {os.path.basename(src_db)}:{table} → {len(rows)} 5-min-Buckets "
              f"({len(use)} Spalten)")
        return len(rows)
    finally:
        src.close()
        dst.close()


def _ensure_device_targets(stats_db: str) -> None:
    """Permanente per-Gerät-5-min-Tabellen anlegen (Lasten-Leistungsverlauf).

    Die Tag-Leistungskurven je Last (Fritz!DECT: Klima/Gefrier/Lüftung/
    Heizpatrone; Wattpilot) liegen sonst nur in den Roh-Tabellen mit kurzer
    Retention (fritzdect_readings 7 T, wattpilot_readings 90 T). Hier permanent
    im 5-min-Raster, damit ältere Tage nicht in „Haushalt" zusammenfallen.
    """
    conn = sqlite3.connect(stats_db, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {FRITZ_TABLE} (
                ts INTEGER NOT NULL,
                device_id TEXT NOT NULL,
                power_w_avg REAL,
                power_w_max REAL,
                energy_total_wh REAL,
                PRIMARY KEY (ts, device_id)
            )
        """)
        conn.execute(f'CREATE INDEX IF NOT EXISTS idx_fritz5_ts ON {FRITZ_TABLE}(ts)')
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {WATTPILOT_TABLE} (
                ts INTEGER PRIMARY KEY,
                power_w_avg REAL,
                power_w_max REAL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def process_fritz(stats_db: str, src_db: str,
                  ts_from: float | None = None, ts_to: float | None = None) -> int:
    """Downsample fritzdect_readings → fritzdect_5min_permanent (per Gerät)."""
    where = []
    params: list = []
    if ts_from is not None:
        where.append("ts >= ?"); params.append(ts_from)
    if ts_to is not None:
        where.append("ts < ?"); params.append(ts_to)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    query = (
        f"SELECT CAST(ts/{BUCKET_S} AS INTEGER)*{BUCKET_S} AS ts, device_id, "
        f"AVG(power_w), MAX(power_w), MAX(energy_total_wh) "
        f"FROM fritzdect_readings {where_sql} "
        f"GROUP BY CAST(ts/{BUCKET_S} AS INTEGER), device_id"
    )
    src = sqlite3.connect(f'file:{src_db}?mode=ro', uri=True, timeout=30.0)
    dst = sqlite3.connect(stats_db, timeout=60.0)
    try:
        try:
            rows = src.execute(query, params).fetchall()
        except sqlite3.OperationalError:
            print("  [skip] fritzdect_readings nicht vorhanden")
            return 0
        if not rows:
            print("  [empty] fritzdect_readings")
            return 0
        dst.executemany(
            f"INSERT OR REPLACE INTO {FRITZ_TABLE} "
            f"(ts, device_id, power_w_avg, power_w_max, energy_total_wh) "
            f"VALUES (?,?,?,?,?)", rows)
        dst.commit()
        print(f"  [ok]   fritzdect_readings → {len(rows)} 5-min-Zeilen")
        return len(rows)
    finally:
        src.close()
        dst.close()


def process_wattpilot(stats_db: str, src_db: str,
                      ts_from: float | None = None, ts_to: float | None = None) -> int:
    """Downsample wattpilot_readings → wattpilot_5min_permanent."""
    where = []
    params: list = []
    if ts_from is not None:
        where.append("ts >= ?"); params.append(ts_from)
    if ts_to is not None:
        where.append("ts < ?"); params.append(ts_to)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    query = (
        f"SELECT CAST(ts/{BUCKET_S} AS INTEGER)*{BUCKET_S} AS ts, "
        f"AVG(power_w), MAX(power_w) "
        f"FROM wattpilot_readings {where_sql} "
        f"GROUP BY CAST(ts/{BUCKET_S} AS INTEGER)"
    )
    src = sqlite3.connect(f'file:{src_db}?mode=ro', uri=True, timeout=30.0)
    dst = sqlite3.connect(stats_db, timeout=60.0)
    try:
        try:
            rows = src.execute(query, params).fetchall()
        except sqlite3.OperationalError:
            print("  [skip] wattpilot_readings nicht vorhanden")
            return 0
        if not rows:
            print("  [empty] wattpilot_readings")
            return 0
        dst.executemany(
            f"INSERT OR REPLACE INTO {WATTPILOT_TABLE} "
            f"(ts, power_w_avg, power_w_max) VALUES (?,?,?)", rows)
        dst.commit()
        print(f"  [ok]   wattpilot_readings → {len(rows)} 5-min-Zeilen")
        return len(rows)
    finally:
        src.close()
        dst.close()


def coverage(stats_db: str) -> None:
    conn = sqlite3.connect(f'file:{stats_db}?mode=ro', uri=True, timeout=10.0)
    try:
        row = conn.execute(
            f"SELECT datetime(MIN(ts),'unixepoch','localtime'), "
            f"datetime(MAX(ts),'unixepoch','localtime'), COUNT(*) FROM {TARGET_TABLE}"
        ).fetchone()
        print(f"STATS-DB {TARGET_TABLE}: {row[0]} .. {row[1]}  ({row[2]} Zeilen)")
        # Tage mit Datenlücken (< 200 von ~288 möglichen 5-min-Buckets)
        gaps = conn.execute(
            f"SELECT date(ts,'unixepoch','localtime') d, COUNT(*) n FROM {TARGET_TABLE} "
            f"GROUP BY d HAVING n < 200 ORDER BY d"
        ).fetchall()
        if gaps:
            print(f"  Tage mit <200 Buckets (Lücken): {len(gaps)} — "
                  f"z.B. {', '.join(f'{d}={n}' for d, n in gaps[:6])}")
        for tbl, label in ((FRITZ_TABLE, 'Fritz!DECT'), (WATTPILOT_TABLE, 'Wattpilot')):
            try:
                r = conn.execute(
                    f"SELECT datetime(MIN(ts),'unixepoch','localtime'), "
                    f"datetime(MAX(ts),'unixepoch','localtime'), COUNT(*) FROM {tbl}"
                ).fetchone()
                if r and r[2]:
                    print(f"STATS-DB {tbl} ({label}): {r[0]} .. {r[1]}  ({r[2]} Zeilen)")
            except sqlite3.OperationalError:
                pass
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="STATS-DB 5-min permanent")
    ap.add_argument('--stats-db', default=STATS_DB_DEFAULT)
    ap.add_argument('--backfill', action='store_true')
    ap.add_argument('--archive-daily', action='store_true',
                    help='Gestrigen Tag aus Live-RAM-DB nachführen (Cron)')
    ap.add_argument('--day', help='Nur diesen Tag YYYY-MM-DD (Live-Quelle)')
    ap.add_argument('--source', action='append', default=[],
                    help='QUELLE.db[:tabelle] (Standard-Tabelle data_1min), wiederholbar')
    ap.add_argument('--devices-full', action='store_true',
                    help='Per-Gerät-5-min-Tabellen aus dem vollen Live-Retention-Fenster '
                         'rekonstruieren (Fritz ~7 T, Wattpilot ~90 T)')
    args = ap.parse_args()

    target_cols = _target_columns(LIVE_DB)
    _ensure_target(args.stats_db, target_cols)
    _ensure_device_targets(args.stats_db)
    total = 0

    if args.archive_daily or args.day:
        if args.day:
            d0 = datetime.strptime(args.day, '%Y-%m-%d')
        else:
            d0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        ts_from = d0.timestamp()
        ts_to = (d0 + timedelta(days=1)).timestamp()
        print(f"Archiv-Lauf: {d0.date()} aus Live-DB")
        total += process_source(args.stats_db, LIVE_DB, 'data_1min', target_cols, ts_from, ts_to)
        # Per-Gerät-Leistungskurven desselben Tages permanent sichern.
        process_fritz(args.stats_db, LIVE_DB, ts_from, ts_to)
        process_wattpilot(args.stats_db, LIVE_DB, ts_from, ts_to)

    if args.backfill or args.source:
        sources = args.source or [f'{LIVE_DB}:data_1min']
        print(f"Backfill aus {len(sources)} Quelle(n):")
        for spec in sources:
            if ':' in spec and not spec[1:3] == ':\\':
                path, table = spec.rsplit(':', 1)
            else:
                path, table = spec, 'data_1min'
            if not os.path.exists(path):
                print(f"  [miss] {path} — nicht gefunden")
                continue
            total += process_source(args.stats_db, path, table, target_cols)

    # Rekonstruktion der per-Gerät-Tabellen über das volle vorhandene Fenster.
    if args.devices_full:
        print("Per-Gerät-Rekonstruktion aus Live-Roh-Tabellen (volles Retention-Fenster):")
        process_fritz(args.stats_db, LIVE_DB)
        process_wattpilot(args.stats_db, LIVE_DB)

    print(f"Fertig: {total} Buckets verarbeitet.")
    coverage(args.stats_db)
    return 0


if __name__ == '__main__':
    sys.exit(main())
