#!/usr/bin/env python3
"""
Tages-CSV-Export: daily_data → doc/csv/daily_YYYY.csv (tagegenau, Solarweb-frei).

Zweck:
  Menschenlesbares Langzeit-Archiv der Energiebilanz je Tag — unabhängig von der
  Fronius-Solarweb-Cloud (Abkopplung s. doc/transition/SOLARWEB_ABKOPPLUNG.md).
  Eine CSV je Jahr, per Tabellenkalkulation sofort erschließbar.

Datenquelle (Rolle: Lese-/Export-Werkzeug, read-only):
  db_utils.get_db_connection_ro() → Shadow-Views (volle Historie, nicht nur das
  120-Tage-RAM-Fenster). Join auf wattpilot_daily (Wallbox-Tagesenergie).

Nutzung:
  python3 tools/export_daily_csv.py                  # alle Jahre
  python3 tools/export_daily_csv.py --year 2026      # nur ein Jahr
  python3 tools/export_daily_csv.py --out-dir /tmp   # anderes Zielverzeichnis

Felder (Einheit kWh, Trennzeichen ';' wie solarweb_daily_*):
  date, pv, bezug, einsp, batt_in, batt_out, verbrauch, direktverbrauch, wp, wattpilot
"""
import argparse
import csv
import logging
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
import config  # noqa: E402
from db_utils import get_db_connection_ro  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_OUT_DIR = os.path.join(config.BASE_DIR, 'doc', 'csv')

FIELDNAMES = [
    'date', 'pv', 'bezug', 'einsp', 'batt_in', 'batt_out',
    'verbrauch', 'direktverbrauch', 'wp', 'wattpilot',
]


def _rows_for_year(cur, year):
    """Tageszeilen eines Jahres aus daily_data (+ wattpilot_daily) lesen."""
    cur.execute("""
        SELECT date(d.ts, 'unixepoch', 'localtime') AS tag,
               d.W_PV_total, d.W_Imp_Netz_total, d.W_Exp_Netz_total,
               d.W_Batt_Charge_total, d.W_Batt_Discharge_total,
               d.W_Consumption_total, d.W_PV_Direct_total, d.W_WP_total,
               w.energy_wh
        FROM daily_data d
        LEFT JOIN wattpilot_daily w ON w.ts = d.ts
        WHERE strftime('%Y', d.ts, 'unixepoch', 'localtime') = ?
        ORDER BY d.ts
    """, (str(year),))
    out = []
    for r in cur.fetchall():
        kwh = lambda v: round((v or 0.0) / 1000.0, 3)
        out.append({
            'date': r[0],
            'pv': kwh(r[1]),
            'bezug': kwh(r[2]),
            'einsp': kwh(r[3]),
            'batt_in': kwh(r[4]),
            'batt_out': kwh(r[5]),
            'verbrauch': kwh(r[6]),
            'direktverbrauch': kwh(r[7]),
            'wp': kwh(r[8]),
            'wattpilot': kwh(r[9]),
        })
    return out


def export(years=None, out_dir=DEFAULT_OUT_DIR):
    conn = get_db_connection_ro()
    cur = conn.cursor()
    try:
        if not years:
            cur.execute("""
                SELECT DISTINCT strftime('%Y', ts, 'unixepoch', 'localtime')
                FROM daily_data ORDER BY 1
            """)
            years = [int(x[0]) for x in cur.fetchall() if x[0]]

        os.makedirs(out_dir, exist_ok=True)
        total = 0
        for year in years:
            rows = _rows_for_year(cur, year)
            if not rows:
                logging.info("Jahr %s: keine Daten — übersprungen", year)
                continue
            path = os.path.join(out_dir, f'daily_{year}.csv')
            with open(path, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter=';')
                w.writeheader()
                w.writerows(rows)
            logging.info("✓ %s (%d Tage)", path, len(rows))
            total += len(rows)
        logging.info("Fertig: %d Tageszeilen über %d Jahr(e)", total, len(years))
    finally:
        conn.close()


def main():
    p = argparse.ArgumentParser(description='Tages-CSV-Export daily_data → doc/csv/daily_YYYY.csv')
    p.add_argument('--year', type=int, action='append',
                   help='Nur dieses Jahr (mehrfach möglich). Default: alle.')
    p.add_argument('--out-dir', default=DEFAULT_OUT_DIR,
                   help=f'Zielverzeichnis (Default: {DEFAULT_OUT_DIR})')
    args = p.parse_args()
    export(years=args.year, out_dir=args.out_dir)


if __name__ == '__main__':
    sys.exit(main())
