#!/usr/bin/env python3
"""
Batterie-Gesundheit (Tagesintervall): battery_health_daily befüllen.
Läuft im selben Cron-Takt wie die Statistik-Aggregation (stündlich :11).

Zweck:
  1. SOH-Historie: Der State-of-Health wird sonst nur live in der API gelesen
     (routes/system/battery.py). Hier wird er 1×/Tag best-effort vom BMS erfasst
     und träge fortgeschrieben, damit die langsame Alterung nachvollziehbar wird.
  2. Vollzyklen: Intervallbezogen = Σ Tagesladung / Nominal-Kapazität der jeweils
     gültigen Ausbaustufe (config.battery_capacity_kwh_for). Aus daily_data
     deterministisch rekonstruierbar → wird bei jedem Lauf neu berechnet.

Rollen-Reinheit: Rolle A (Collector-Aggregation). Reiner DB-Lesepfad aus
daily_data + best-effort HTTP-Lesezugriff auf das BMS (kein Hardware-Write).
"""
import sys
from host_role import is_failover

if is_failover():
    sys.exit(0)

import logging
from datetime import datetime

import config
from db_utils import get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DB_PATH = config.DB_PATH


def _read_live_soh():
    """Best-effort SOH (%) vom Fronius/BYD-BMS. None bei Fehler/Nichtverfügbarkeit."""
    try:
        import requests
        resp = requests.get(
            f'http://{config.INVERTER_IP}/components/readable', timeout=3)
        if resp.status_code != 200:
            return None
        data = resp.json().get('Body', {}).get('Data', {})
        batt_key = next((k for k in data if 'Storage' in k or 'BYD' in k), None)
        if not batt_key:
            return None
        channels = data.get(batt_key, {}).get('channels', {})
        soh = channels.get('BAT_VALUE_STATE_OF_HEALTH_RELATIVE_U16')
        return round(float(soh), 1) if soh is not None else None
    except Exception as exc:
        logging.debug(f"SOH-Live-Read fehlgeschlagen: {exc}")
        return None


def update_battery_health_daily():
    """Aktualisiere battery_health_daily aus daily_data + best-effort Live-SOH."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Tabelle defensiv sicherstellen (db_init legt sie regulär an).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS battery_health_daily (
                day_ts INTEGER PRIMARY KEY,
                soh_pct REAL,
                capacity_kwh REAL,
                charge_kwh REAL,
                discharge_kwh REAL,
                full_cycles REAL,
                updated_ts INTEGER DEFAULT (strftime('%s','now'))
            )
        """)

        import time
        current_day = (int(time.time()) // 86400) * 86400
        live_soh = _read_live_soh()

        cursor.execute("""
            SELECT ts, W_Batt_Charge_total, W_Batt_Discharge_total
            FROM daily_data
            ORDER BY ts
        """)
        rows = cursor.fetchall()

        count = 0
        for day_ts, charge_wh, discharge_wh in rows:
            day = datetime.fromtimestamp(day_ts)
            capacity = config.battery_capacity_kwh_for(day.year, day.month)
            charge_kwh = (charge_wh or 0.0) / 1000.0
            discharge_kwh = (discharge_wh or 0.0) / 1000.0
            full_cycles = (charge_kwh / capacity) if capacity > 0 else 0.0
            # SOH nur für den laufenden Tag live setzen; Vergangenheit bleibt erhalten.
            soh = live_soh if day_ts == current_day else None

            cursor.execute("""
                INSERT INTO battery_health_daily (
                    day_ts, soh_pct, capacity_kwh, charge_kwh, discharge_kwh,
                    full_cycles, updated_ts
                ) VALUES (?, ?, ?, ?, ?, ?, strftime('%s','now'))
                ON CONFLICT(day_ts) DO UPDATE SET
                    capacity_kwh = excluded.capacity_kwh,
                    charge_kwh = excluded.charge_kwh,
                    discharge_kwh = excluded.discharge_kwh,
                    full_cycles = excluded.full_cycles,
                    soh_pct = COALESCE(excluded.soh_pct, battery_health_daily.soh_pct),
                    updated_ts = excluded.updated_ts
            """, (day_ts, soh, round(capacity, 2), round(charge_kwh, 3),
                  round(discharge_kwh, 3), round(full_cycles, 4)))
            count += 1

        conn.commit()
        soh_txt = f"{live_soh}%" if live_soh is not None else "n/v"
        logging.info(f"✓ {count} Tage in battery_health_daily aktualisiert (SOH heute: {soh_txt})")
    except Exception as e:
        conn.rollback()
        logging.error(f"Fehler bei battery_health_daily: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    logging.info("=== Batterie-Gesundheit-Aggregation ===")
    update_battery_health_daily()
    logging.info("=== Batterie-Gesundheit-Aggregation abgeschlossen ===")
