#!/usr/bin/env python3
"""
build_tiered_dbs.py — Stufe-1-Fundament der 3-stufigen Datenhaltung.

Baut die beiden permanenten SD-Datenbanken **parallel zur Produktion** auf
(nicht-destruktiv, Produktions-DBs werden nur gelesen):

  Stufe 1  RAM-DB  /dev/shm/fronius_data.db   (rollierend, konstant — bleibt)
  Stufe 2  Monitoring  monitoring.db          (5-min-Raster, permanent)   ← HIER
  Stufe 3  Analyse     analysis.db            (Tagesraster, permanent)    ← HIER

Platzierungs-Manifest (welche Tabelle gehört in welche Stufe):

  Stufe 2 (monitoring.db) — 5-min-Verlauf für die „ewige" Tag-Ansicht:
    data_5min_permanent         (alle Monitoring-Größen; Schema = data_1min)
    fritzdect_5min_permanent    (Last-Leistung je Fritz!DECT-Gerät)
    wattpilot_5min_permanent    (Wattpilot-Leistung)
    Quelle: data_stats.db (bestehende Stufe-2-DB).

  Stufe 3 (analysis.db) — Tages-/Monats-/Jahres-Aggregate für die Analyse:
    daily_data, data_monthly, monthly_statistics, yearly_statistics,
    heizpatrone_daily/klimaanlage_daily/gefriertruhe_daily/lueftung_daily,
    heizpatrone_monthly/klimaanlage_monthly/gefriertruhe_monthly/lueftung_monthly,
    wattpilot_daily, battery_health_daily, forecast_daily, price_history
    Quelle: RAM-DB (DB_PATH).

  In Stufe 1 (RAM) VERBLEIBEN bewusst (rollierend oder operativ, NICHT permanent-
  wachsende Analyse-Daten): raw_data, data_1min, data_15min, hourly_data,
  fritzdect_readings, wattpilot_readings, energy_checkpoints, energy_state,
  automation_log, battery_control_log, system_info.

Modi:
  --build    Beide Ziel-DBs (neu) aus den Quellen aufbauen (voller Rebuild je
             Tabelle: DROP+CREATE+Copy; idempotent). Ziel sind AUSSCHLIESSLICH
             die parallelen DBs; Quellen werden nur gelesen.
  --verify   Zeilenzahlen Quelle↔Ziel vergleichen (Stufe-1-Abnahme).

Dieses Werkzeug ändert NICHTS an der laufenden Produktion (kein Cron, keine
Retention, keine API-Umstellung). Das sind spätere Stages.

Siehe: doc/system/TAGESDATEN_HALTBARKEIT.md
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
import config  # noqa: E402

# (Ziel-DB, Quelle-DB, [Tabellen])
MONITORING_TABLES = [
    'data_5min_permanent',
    'fritzdect_5min_permanent',
    'wattpilot_5min_permanent',
]
ANALYSIS_TABLES = [
    'daily_data',
    'data_monthly',
    'monthly_statistics',
    'yearly_statistics',
    'heizpatrone_daily', 'klimaanlage_daily', 'gefriertruhe_daily', 'lueftung_daily',
    'heizpatrone_monthly', 'klimaanlage_monthly', 'gefriertruhe_monthly', 'lueftung_monthly',
    'wattpilot_daily',
    'battery_health_daily',
    'forecast_daily',
    'price_history',
]


def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=30.0)


def _table_schema(src: sqlite3.Connection, table: str) -> str | None:
    row = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row[0] if row and row[0] else None


def _copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> int:
    """Voller Rebuild einer Tabelle im Ziel aus der Quelle (DROP+CREATE+Copy)."""
    schema = _table_schema(src, table)
    if not schema:
        print(f"  [skip] {table} — in Quelle nicht vorhanden")
        return -1
    cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
    collist = ','.join(f'"{c}"' for c in cols)
    rows = src.execute(f"SELECT {collist} FROM {table}").fetchall()

    dst.execute(f"DROP TABLE IF EXISTS {table}")
    dst.execute(schema)
    # Indizes der Quelle mitnehmen (ohne die autoindex-Einträge).
    for (idx_sql,) in src.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table,),
    ).fetchall():
        try:
            dst.execute(idx_sql)
        except sqlite3.OperationalError:
            pass
    if rows:
        ph = ','.join('?' * len(cols))
        dst.executemany(f"INSERT INTO {table} ({collist}) VALUES ({ph})", rows)
    dst.commit()
    print(f"  [ok]   {table}: {len(rows)} Zeilen kopiert")
    return len(rows)


def build(target_db: str, source_db: str, tables: list[str]) -> None:
    if not os.path.exists(source_db):
        print(f"FEHLER: Quelle fehlt: {source_db}")
        return
    print(f"\nBaue {os.path.basename(target_db)} aus {os.path.basename(source_db)}:")
    src = _ro(source_db)
    dst = sqlite3.connect(target_db, timeout=60.0)
    try:
        dst.execute("PRAGMA journal_mode=WAL")
        for t in tables:
            _copy_table(src, dst, t)
    finally:
        src.close()
        dst.close()


def verify(target_db: str, source_db: str, tables: list[str]) -> bool:
    if not os.path.exists(target_db):
        print(f"  {os.path.basename(target_db)} existiert noch nicht")
        return False
    src = _ro(source_db)
    dst = _ro(target_db)
    ok = True
    print(f"\nVerify {os.path.basename(target_db)} ↔ {os.path.basename(source_db)}:")
    try:
        for t in tables:
            try:
                n_src = src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.OperationalError:
                n_src = None
            try:
                n_dst = dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.OperationalError:
                n_dst = None
            flag = '✓' if n_src == n_dst else '✗'
            if n_src != n_dst:
                ok = False
            print(f"  {flag} {t:<26} Quelle={n_src}  Ziel={n_dst}")
    finally:
        src.close()
        dst.close()
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Stufe-1-Aufbau monitoring.db + analysis.db")
    ap.add_argument('--build', action='store_true')
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--monitoring-db', default=config.MONITORING_DB_PATH)
    ap.add_argument('--analysis-db', default=config.ANALYSIS_DB_PATH)
    ap.add_argument('--stats-db', default=config.STATS_DB_PATH)
    ap.add_argument('--ram-db', default=config.DB_PATH)
    args = ap.parse_args()

    if not args.build and not args.verify:
        ap.error("Bitte --build und/oder --verify angeben")

    if args.build:
        build(args.monitoring_db, args.stats_db, MONITORING_TABLES)
        build(args.analysis_db, args.ram_db, ANALYSIS_TABLES)

    if args.verify:
        m_ok = verify(args.monitoring_db, args.stats_db, MONITORING_TABLES)
        a_ok = verify(args.analysis_db, args.ram_db, ANALYSIS_TABLES)
        print(f"\nErgebnis: monitoring={'OK' if m_ok else 'ABWEICHUNG'}, "
              f"analysis={'OK' if a_ok else 'ABWEICHUNG'}")
        return 0 if (m_ok and a_ok) else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
