#!/usr/bin/env python3
"""
Rekonstruiert die permanente Tages-WR-Aufteilung (daily_data.W_PV_F1/F2/F3_total)
aus der permanenten 5-min-Statistik-DB (stats.data_5min_permanent).

Hintergrund:
  Die Erzeuger-Monatsansicht las die WR-Aufteilung F1/F2/F3 live aus
  data_1min/data_15min (90-Tage-Retention). Ältere Monate fielen weg.
  daily_data trägt jetzt permanente Spalten W_PV_F1/F2/F3_total; dieses
  Tool füllt sie rückwirkend aus der permanenten 5-min-DD-Statistik, die
  bis 2026-01-01 zurückreicht.

Formel (netto, identisch zu daily.py / /api/erzeuger):
  F1 = Σ(W_DC1_delta + W_DC2_delta)
  F2 = Σ(-W_Exp_F2_delta - W_Imp_F2_delta)   (= Export − Standby-Import)
  F3 = Σ(-W_Exp_F3_delta - W_Imp_F3_delta)

Nicht-destruktiv: Es werden nur Tage befüllt, deren Spalten aktuell NULL sind.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import config
import db_init
from db_utils import get_db_connection


def reconstruct(start_date=None, overwrite=False, dry_run=False):
    conn = get_db_connection()
    c = conn.cursor()

    # Permanente 5-min-Statistik je lokalem Tag → Netto-WR-Erzeugung (Wh)
    try:
        c.execute("SELECT 1 FROM stats.data_5min_permanent LIMIT 1")
    except Exception as e:
        print(f"FEHLER: stats.data_5min_permanent nicht verfügbar ({e})")
        conn.close()
        return 1

    where = ""
    params = []
    if start_date:
        where = "WHERE date(ts,'unixepoch','localtime') >= ?"
        params.append(start_date)

    c.execute(f"""
        SELECT date(ts, 'unixepoch', 'localtime') AS day,
               SUM(COALESCE(W_DC1_delta, 0) + COALESCE(W_DC2_delta, 0)) AS f1,
               SUM(-COALESCE(W_Exp_F2_delta, 0) - COALESCE(W_Imp_F2_delta, 0)) AS f2,
               SUM(-COALESCE(W_Exp_F3_delta, 0) - COALESCE(W_Imp_F3_delta, 0)) AS f3
        FROM stats.data_5min_permanent
        {where}
        GROUP BY day
    """, params)
    per_day = {}
    for day, f1, f2, f3 in c.fetchall():
        per_day[day] = (max(0.0, f1 or 0.0), max(0.0, f2 or 0.0), max(0.0, f3 or 0.0))

    # Ziel-Tage in daily_data (lokales Datum → ts)
    cond = "" if overwrite else (
        "AND (W_PV_F1_total IS NULL AND W_PV_F2_total IS NULL AND W_PV_F3_total IS NULL)")
    dwhere = "WHERE 1=1 " + cond
    dparams = []
    if start_date:
        dwhere = f"WHERE date(ts,'unixepoch','localtime') >= ? {cond}"
        dparams.append(start_date)

    c.execute(f"SELECT ts, date(ts,'unixepoch','localtime') FROM daily_data {dwhere}", dparams)
    targets = c.fetchall()

    updated = 0
    skipped = 0
    for ts, day in targets:
        vals = per_day.get(day)
        if vals is None:
            skipped += 1
            continue
        f1, f2, f3 = vals
        if (f1 + f2 + f3) <= 0:
            skipped += 1
            continue
        if dry_run:
            updated += 1
            continue
        c.execute("""
            UPDATE daily_data
            SET W_PV_F1_total = ?, W_PV_F2_total = ?, W_PV_F3_total = ?
            WHERE ts = ?
        """, (round(f1, 1), round(f2, 1), round(f3, 1), ts))
        updated += 1

    if not dry_run:
        conn.commit()
    conn.close()

    print(f"{'[DRY-RUN] ' if dry_run else ''}Rekonstruiert: {updated} Tage, übersprungen: {skipped}")

    # RAM-DB → SD persistieren (sonst ginge die Rekonstruktion beim Reboot verloren)
    if not dry_run and updated > 0:
        ok = db_init._persist_tmpfs_to_sd(config.DB_PATH, config.DB_PERSIST_PATH)
        print(f"Persist RAM→SD ({config.DB_PERSIST_PATH}): {'OK' if ok else 'FEHLGESCHLAGEN'}")
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--start', default='2026-01-01', help='frühestes lokales Datum (YYYY-MM-DD)')
    ap.add_argument('--overwrite', action='store_true', help='auch vorhandene Werte überschreiben')
    ap.add_argument('--dry-run', action='store_true', help='nur anzeigen, nichts schreiben')
    args = ap.parse_args()
    sys.exit(reconstruct(args.start, args.overwrite, args.dry_run))
