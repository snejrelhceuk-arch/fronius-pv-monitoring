#!/usr/bin/env python3
"""
WP-Thermik (Tagesintervall): wp_thermal_daily befüllen + COP/SCOP-Basis.

Zweck:
  Die Dimplex-WP führt intern kumulative Wärmemengen- (Heizen + WW) und
  Laufstunden-Zähler (Modbus-Historie 5.2). Dieses Modul snapshotet die Zähler
  1×/Takt als End-Stand des laufenden Tages, bildet das Tagesdelta (thermische
  kWh) und stellt es der elektrischen WP-Tagesenergie (daily_data.W_WP_total,
  sekundärer SM) gegenüber:  COP = thermal_delta / el_kwh.

Datenpfad (Rolle A, read-only ggü. Hardware):
  wp_modbus.get_wp_energy() nutzt denselben local/remote-Transport wie der
  Collector-WP-Status (auf Primary via Pi4-Tech-Bridge). KEIN Hardware-Write.

Auflösung: Wärmemengen-Zähler in ganzen kWh, Laufstunden in ganzen h → das
Tagesdelta ist deterministisch (±1 kWh Quantisierung). Deltas werden bei jedem
Lauf per Self-Join neu berechnet (self-healing); der COP eines Tages wird erst
belastbar, sobald der Folgetag einen End-Stand hat.
"""
import sys
from host_role import is_failover

if is_failover():
    sys.exit(0)

import logging
import time
from datetime import datetime

import config
import wp_modbus
from db_utils import get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Unterhalb dieser el. Tagesenergie ist der COP nicht belastbar (Rausch-/Quantisierung).
_COP_MIN_EL_KWH = 1.0


def update_wp_thermal_daily():
    """Snapshot der WP-Zähler für heute + Delta/COP-Neuberechnung aller Tage."""
    energy = wp_modbus.get_wp_energy()
    if not energy:
        logging.warning("WP-Thermik: keine Zählerdaten (Bridge/Modbus nicht erreichbar) — übersprungen")
        return

    heizen = energy.get('waerme_heizen_kwh')
    ww = energy.get('waerme_ww_kwh')
    if heizen is None or ww is None:
        logging.warning("WP-Thermik: Wärmemengen unvollständig (%s) — übersprungen", energy)
        return
    thermal_end = heizen + ww

    today = datetime.now().strftime('%Y-%m-%d')
    today_day_ts = (int(time.time()) // 86400) * 86400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wp_thermal_daily (
                day TEXT PRIMARY KEY,
                heizen_kwh_end REAL, ww_kwh_end REAL, thermal_kwh_end REAL,
                heizen_delta_kwh REAL, ww_delta_kwh REAL, thermal_delta_kwh REAL,
                verdichter1_h_end REAL, verdichter1_h_delta REAL,
                verdichter2_h_end REAL, primaerpumpe_h_end REAL,
                heizpumpe_h_end REAL, wwpumpe_h_end REAL, zweiterwe_h_end REAL,
                el_kwh REAL, cop REAL, src TEXT DEFAULT 'counter',
                created_ts INTEGER DEFAULT (strftime('%s','now'))
            )
        """)

        # el. WP-Tagesenergie (sekundärer SM) für heute aus daily_data.
        cur.execute("""
            SELECT W_WP_total FROM daily_data
            WHERE date(ts, 'unixepoch', 'localtime') = ?
        """, (today,))
        row = cur.fetchone()
        el_kwh_today = round((row[0] or 0.0) / 1000.0, 3) if row else None

        # Heutigen End-Stand upserten (Zähler = Stand zum Lauf-Zeitpunkt).
        cur.execute("""
            INSERT INTO wp_thermal_daily (
                day, heizen_kwh_end, ww_kwh_end, thermal_kwh_end,
                verdichter1_h_end, verdichter2_h_end, primaerpumpe_h_end,
                heizpumpe_h_end, wwpumpe_h_end, zweiterwe_h_end, el_kwh, created_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s','now'))
            ON CONFLICT(day) DO UPDATE SET
                heizen_kwh_end = excluded.heizen_kwh_end,
                ww_kwh_end = excluded.ww_kwh_end,
                thermal_kwh_end = excluded.thermal_kwh_end,
                verdichter1_h_end = excluded.verdichter1_h_end,
                verdichter2_h_end = excluded.verdichter2_h_end,
                primaerpumpe_h_end = excluded.primaerpumpe_h_end,
                heizpumpe_h_end = excluded.heizpumpe_h_end,
                wwpumpe_h_end = excluded.wwpumpe_h_end,
                zweiterwe_h_end = excluded.zweiterwe_h_end,
                el_kwh = COALESCE(excluded.el_kwh, wp_thermal_daily.el_kwh),
                created_ts = excluded.created_ts
        """, (today, float(heizen), float(ww), float(thermal_end),
              energy.get('verdichter1_h'), energy.get('verdichter2_h'),
              energy.get('primaerpumpe_h'), energy.get('heizpumpe_h'),
              energy.get('wwpumpe_h'), energy.get('zweiterwe_h'), el_kwh_today))

        # Deltas + COP für alle Tage neu berechnen (Self-Join auf Vortag).
        cur.execute("SELECT day, thermal_kwh_end, heizen_kwh_end, ww_kwh_end, verdichter1_h_end, el_kwh FROM wp_thermal_daily ORDER BY day")
        rows = cur.fetchall()
        prev = None
        for day, thermal, heizen_e, ww_e, v1, el in rows:
            if prev is not None:
                p_day, p_thermal, p_heizen, p_ww, p_v1 = prev
                th_d = round((thermal or 0) - (p_thermal or 0), 1)
                hz_d = round((heizen_e or 0) - (p_heizen or 0), 1)
                ww_d = round((ww_e or 0) - (p_ww or 0), 1)
                v1_d = round((v1 or 0) - (p_v1 or 0), 1) if (v1 is not None and p_v1 is not None) else None
                # COP nur bei belastbarer el. Energie und nicht-negativem Delta.
                cop = None
                if el and el >= _COP_MIN_EL_KWH and th_d >= 0:
                    cop = round(th_d / el, 2)
                cur.execute("""
                    UPDATE wp_thermal_daily SET
                        heizen_delta_kwh=?, ww_delta_kwh=?, thermal_delta_kwh=?,
                        verdichter1_h_delta=?, cop=?
                    WHERE day=?
                """, (hz_d, ww_d, th_d, v1_d, cop, day))
            prev = (day, thermal, heizen_e, ww_e, v1)

        conn.commit()
        logging.info("✓ WP-Thermik: %s thermal_end=%.0f kWh (Heizen=%.0f, WW=%.0f), el_heute=%s kWh, Tage=%d",
                     today, thermal_end, heizen, ww,
                     el_kwh_today if el_kwh_today is not None else 'n/v', len(rows))
    except Exception as e:
        conn.rollback()
        logging.error("Fehler bei wp_thermal_daily: %s", e)
    finally:
        conn.close()


if __name__ == "__main__":
    logging.info("=== WP-Thermik-Aggregation ===")
    update_wp_thermal_daily()
    logging.info("=== WP-Thermik-Aggregation abgeschlossen ===")
