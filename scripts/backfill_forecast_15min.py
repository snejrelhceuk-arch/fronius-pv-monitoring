#!/usr/bin/env python3
"""
Backfill Prognose/Clear-Sky in data_15min aus forecast_daily.

Default: nutzt die RAM-DB (/dev/shm) und schreibt nur in existierende
15min-Zeilen. Persist-DB wird nur mit --persist verwendet.

Usage:
    python3 scripts/backfill_forecast_15min.py --days 90
    python3 scripts/backfill_forecast_15min.py --days 30 --dry-run
    python3 scripts/backfill_forecast_15min.py --persist --days 7
"""
import os
import sys
import json
import argparse
import sqlite3
from datetime import datetime, timedelta

# Projekt-Pfad
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


FORECAST_COLS = (
    'P_PV_FC_avg',
    'W_PV_FC_delta',
    'P_PV_CS_avg',
    'W_PV_CS_delta',
)


def _day_timestamps(date_str, step_seconds):
    day = datetime.strptime(date_str, '%Y-%m-%d')
    start = int(day.timestamp())
    return [start + i * step_seconds for i in range(int(86400 / step_seconds))]


def _interpolate_series(points, target_ts):
    if not points:
        return []

    points = sorted(points, key=lambda p: p[0])
    min_ts = points[0][0]
    max_ts = points[-1][0]
    result = []
    idx = 0

    for ts in target_ts:
        if ts < min_ts or ts > max_ts:
            result.append((ts, 0.0))
            continue

        while idx + 1 < len(points) and points[idx + 1][0] < ts:
            idx += 1

        if idx + 1 < len(points):
            t0, v0 = points[idx]
            t1, v1 = points[idx + 1]
            if t1 == t0:
                val = v0
            else:
                ratio = (ts - t0) / (t1 - t0)
                ratio = max(0.0, min(1.0, ratio))
                val = v0 + (v1 - v0) * ratio
        else:
            val = points[-1][1]

        result.append((ts, val))

    return result


def _extract_points(raw, value_keys):
    points = []
    for dp in raw:
        ts = dp.get('ts') or dp.get('timestamp')
        if ts is None:
            continue
        val = None
        for key in value_keys:
            if key in dp and dp[key] is not None:
                val = dp[key]
                break
        if val is None:
            continue
        points.append((int(ts), float(val)))
    return points


def _ensure_columns(conn):
    for col in FORECAST_COLS:
        try:
            conn.execute(f"SELECT {col} FROM data_15min LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(f"ALTER TABLE data_15min ADD COLUMN {col} REAL DEFAULT NULL")
            conn.commit()


def _load_forecast_profiles(conn, date_str):
    row = conn.execute(
        "SELECT hourly_profile, clearsky_profile FROM forecast_daily WHERE date = ?",
        (date_str,)
    ).fetchone()
    if not row:
        return None, None

    hourly_raw = []
    clearsky_raw = []

    if row[0]:
        try:
            hourly_raw = json.loads(row[0])
        except json.JSONDecodeError:
            hourly_raw = []

    if row[1]:
        try:
            clearsky_raw = json.loads(row[1])
        except json.JSONDecodeError:
            clearsky_raw = []

    hourly_points = _extract_points(hourly_raw, ('p', 'p_produktion', 'total_ac'))
    clearsky_points = _extract_points(clearsky_raw, ('ac', 'total_ac'))

    return hourly_points, clearsky_points


def _day_has_15min_rows(conn, date_str):
    row = conn.execute(
        """
        SELECT COUNT(*) FROM data_15min
        WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day')
          AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')
        """,
        (date_str, date_str),
    ).fetchone()
    return (row[0] or 0) > 0


def _update_day(conn, date_str, forecast_15m, clearsky_15m, dry_run=False):
    by_ts = {}
    for ts, val in forecast_15m:
        by_ts.setdefault(ts, {})['p_fc'] = val
    for ts, val in clearsky_15m:
        by_ts.setdefault(ts, {})['p_cs'] = val

    updates = []
    for ts, vals in by_ts.items():
        p_fc = vals.get('p_fc')
        p_cs = vals.get('p_cs')
        w_fc = (p_fc or 0) * 0.25
        w_cs = (p_cs or 0) * 0.25
        updates.append((p_fc, w_fc, p_cs, w_cs, ts))

    if dry_run:
        return len(updates)

    conn.executemany(
        """
        UPDATE data_15min
        SET P_PV_FC_avg = ?,
            W_PV_FC_delta = ?,
            P_PV_CS_avg = ?,
            W_PV_CS_delta = ?
        WHERE ts = ?
        """,
        updates,
    )
    return len(updates)


def run_backfill(db_path, days, dry_run=False):
    conn = sqlite3.connect(db_path, timeout=20.0)
    _ensure_columns(conn)

    today = datetime.now().date()
    total_updates = 0
    total_days = 0

    for offset in range(days):
        target = today - timedelta(days=offset)
        date_str = target.isoformat()

        if not _day_has_15min_rows(conn, date_str):
            continue

        hourly_points, clearsky_points = _load_forecast_profiles(conn, date_str)
        if not hourly_points and not clearsky_points:
            continue

        day_15m = _day_timestamps(date_str, 900)

        forecast_15m = _interpolate_series(hourly_points, day_15m) if hourly_points else []
        clearsky_15m = _interpolate_series(clearsky_points, day_15m) if clearsky_points else []

        if not forecast_15m and not clearsky_15m:
            continue

        total_days += 1
        updated = _update_day(conn, date_str, forecast_15m, clearsky_15m, dry_run=dry_run)
        total_updates += updated

    if not dry_run:
        conn.commit()
    conn.close()

    return total_days, total_updates


def main():
    parser = argparse.ArgumentParser(description='Backfill Forecast/Clear-Sky in data_15min')
    parser.add_argument('--days', type=int, default=90, help='Anzahl Tage rueckwaerts')
    parser.add_argument('--dry-run', action='store_true', help='Keine DB-Aenderungen')
    parser.add_argument('--persist', action='store_true', help='Nutze Persist-DB (data.db) statt RAM-DB')
    args = parser.parse_args()

    if args.persist:
        db_path = config.DB_PERSIST_PATH
    else:
        db_path = config.DB_PATH

    if not os.path.exists(db_path):
        print(f"FEHLER: DB nicht gefunden: {db_path}")
        if args.persist and os.path.exists(config.DB_PATH):
            print("Hinweis: RAM-DB existiert. Wenn gewuenscht, ohne --persist starten.")
        sys.exit(1)

    print(f"DB: {db_path}")
    print(f"Tage: {args.days}")
    print(f"Modus: {'DRY-RUN' if args.dry_run else 'LIVE'}")
    if args.persist:
        print("Hinweis: Persist-DB wird regelmaessig aus der RAM-DB ueberschrieben.")

    days, updates = run_backfill(db_path, args.days, dry_run=args.dry_run)
    print(f"Fertig: {days} Tage, {updates} Updates")


if __name__ == '__main__':
    main()
