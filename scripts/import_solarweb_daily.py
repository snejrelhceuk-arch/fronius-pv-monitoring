#!/usr/bin/env python3
"""
Import Solarweb-Tagesdaten in daily_data und wattpilot_daily.

Ersetzt die Energie-Summenfelder in daily_data mit den exakten Solarweb-Werten.
Für Tage ohne bestehenden daily_data-Eintrag (Jan 1-6) werden neue Zeilen
eingefügt. Counter-Start/End werden auf NULL gesetzt, damit die Visualisierung
den Fallback (= Solarweb-Wert) verwendet.

Mapping Solarweb → daily_data:
  gesamt_prod_kwh      → W_PV_total (Wh)
  netzbezug_kwh        → W_Imp_Netz_total (Wh)
  einspeisung_kwh      → W_Exp_Netz_total (Wh)
  in_batt_kwh          → W_Batt_Charge_total (Wh)
  out_batt_kwh         → W_Batt_Discharge_total (Wh)
  direkt_kwh+wattpilot → W_PV_Direct_total (Wh)  (= PV - Export - BattCharge)
  verbrauch_kwh        → W_Consumption_total (Wh)
  wattpilot_kwh        → wattpilot_daily.energy_wh (Wh)

W_WP_total (Wärmepumpe) bleibt unverändert (kein Solarweb-Pendant).
Leistungsmittelwerte (P_*) und Frequenz (f_*) bleiben unverändert.

Nutzung:
  python3 scripts/import_solarweb_daily.py [--dry-run]
"""

import sys
import os
import csv
import sqlite3
import logging
from datetime import datetime, timezone

# Projekt-Root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

DB_PATH = config.DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

SOLARWEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'imports', 'solarweb')

CSV_FILES = [
    os.path.join(SOLARWEB_DIR, 'solarweb_daily_2026-01_working.csv'),
    os.path.join(SOLARWEB_DIR, 'solarweb_daily_2026-02_working.csv'),
]


def date_to_daily_ts(date_str):
    """Konvertiere 'YYYY-MM-DD' in den daily_data-Timestamp (Midnight UTC = 01:00 CET)."""
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    # daily_data ts = Midnight UTC des jeweiligen Tages
    dt_utc = dt.replace(hour=0, minute=0, second=0, tzinfo=timezone.utc)
    return int(dt_utc.timestamp())


def load_solarweb_data():
    """Lade alle Solarweb-Tagesdaten aus CSV-Dateien."""
    data = {}
    for csv_path in CSV_FILES:
        if not os.path.exists(csv_path):
            logging.warning(f"CSV nicht gefunden: {csv_path}")
            continue
        with open(csv_path, newline='') as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                date = row['date']
                # Leere Zeilen überspringen (z.B. Feb 20-28 ohne Daten)
                if not row.get('einspeisung_kwh'):
                    continue
                try:
                    data[date] = {
                        'pv_kwh': float(row['gesamt_prod_kwh']),
                        'imp_kwh': float(row['netzbezug_kwh']),
                        'exp_kwh': float(row['einspeisung_kwh']),
                        'batt_charge_kwh': float(row['in_batt_kwh']),
                        'batt_discharge_kwh': float(row['out_batt_kwh']),
                        'direkt_kwh': float(row['direkt_kwh']),
                        'wattpilot_kwh': float(row['wattpilot_kwh']),
                        'consumption_kwh': float(row['verbrauch_kwh']),
                    }
                except (ValueError, KeyError) as e:
                    logging.warning(f"Fehler in Zeile {date}: {e}")
        logging.info(f"  {csv_path}: {sum(1 for d in data if d.startswith(os.path.basename(csv_path).split('_')[2][:7]))} Tage geladen")
    return data


def import_solarweb(dry_run=False):
    """Importiere Solarweb-Daten in daily_data und wattpilot_daily."""
    sw_data = load_solarweb_data()
    if not sw_data:
        logging.error("Keine Solarweb-Daten geladen!")
        return

    logging.info(f"Solarweb: {len(sw_data)} Tage geladen")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    updated = 0
    inserted = 0
    wp_updated = 0

    for date_str in sorted(sw_data.keys()):
        sw = sw_data[date_str]
        ts = date_to_daily_ts(date_str)

        # kWh → Wh
        pv_wh = sw['pv_kwh'] * 1000
        imp_wh = sw['imp_kwh'] * 1000
        exp_wh = sw['exp_kwh'] * 1000
        batt_charge_wh = sw['batt_charge_kwh'] * 1000
        batt_discharge_wh = sw['batt_discharge_kwh'] * 1000
        # PV_Direct = Direkt + Wattpilot (unser DV = PV − Export − BattCharge)
        pv_direct_wh = (sw['direkt_kwh'] + sw['wattpilot_kwh']) * 1000
        consumption_wh = sw['consumption_kwh'] * 1000
        wattpilot_wh = sw['wattpilot_kwh'] * 1000

        # Prüfe ob daily_data-Eintrag existiert
        c.execute("SELECT ts FROM daily_data WHERE ts = ?", (ts,))
        exists = c.fetchone() is not None

        if exists:
            # UPDATE: Energie-Felder ersetzen, Counter-Start/End nullen
            if not dry_run:
                c.execute("""
                    UPDATE daily_data SET
                        W_PV_total = ?,
                        W_Imp_Netz_total = ?,
                        W_Exp_Netz_total = ?,
                        W_Batt_Charge_total = ?,
                        W_Batt_Discharge_total = ?,
                        W_PV_Direct_total = ?,
                        W_Consumption_total = ?,
                        -- Counter-Start/End nullen → Visualisierung nutzt Fallback
                        W_AC_Inv_start = NULL,
                        W_AC_Inv_end = NULL,
                        W_Exp_Netz_start = NULL,
                        W_Exp_Netz_end = NULL,
                        W_Imp_Netz_start = NULL,
                        W_Imp_Netz_end = NULL
                    WHERE ts = ?
                """, (pv_wh, imp_wh, exp_wh, batt_charge_wh, batt_discharge_wh,
                      pv_direct_wh, consumption_wh, ts))
            updated += 1
            logging.info(f"  UPDATE {date_str}: PV={sw['pv_kwh']:.1f} Imp={sw['imp_kwh']:.1f} Exp={sw['exp_kwh']:.1f} BL={sw['batt_charge_kwh']:.1f} DV={sw['direkt_kwh']+sw['wattpilot_kwh']:.1f}")
        else:
            # INSERT: Neue Zeile mit Solarweb-Werten (P-Felder bleiben NULL)
            if not dry_run:
                c.execute("""
                    INSERT INTO daily_data (
                        ts,
                        W_PV_total, W_Imp_Netz_total, W_Exp_Netz_total,
                        W_Consumption_total,
                        W_Batt_Charge_total, W_Batt_Discharge_total,
                        W_PV_Direct_total
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (ts, pv_wh, imp_wh, exp_wh, consumption_wh,
                      batt_charge_wh, batt_discharge_wh, pv_direct_wh))
            inserted += 1
            logging.info(f"  INSERT {date_str}: PV={sw['pv_kwh']:.1f} Imp={sw['imp_kwh']:.1f} Exp={sw['exp_kwh']:.1f} (neu)")

        # Wattpilot: INSERT OR REPLACE in wattpilot_daily
        if wattpilot_wh > 0:
            # Prüfe ob wattpilot_daily den gleichen ts-Offset nutzt
            # wattpilot_daily ts: 1770854400 = 2026-02-12 01:00 CET = midnight UTC
            wp_ts = float(ts)
            if not dry_run:
                c.execute("""
                    INSERT OR REPLACE INTO wattpilot_daily (ts, energy_wh)
                    VALUES (?, ?)
                """, (wp_ts, wattpilot_wh))
            wp_updated += 1

    if not dry_run:
        conn.commit()

    conn.close()

    logging.info(f"\n{'DRY-RUN: ' if dry_run else ''}Ergebnis:")
    logging.info(f"  daily_data:     {updated} aktualisiert, {inserted} neu eingefügt")
    logging.info(f"  wattpilot_daily: {wp_updated} Tage mit Wattpilot-Daten")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        logging.info("=== DRY-RUN Modus (keine DB-Änderungen) ===")
    import_solarweb(dry_run=dry_run)
