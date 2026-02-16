#!/usr/bin/env python3
"""
Tägliche Aggregation: hourly_data → daily_data
Läuft alle 15min via Cron (für Status-Visualisierung)
Verwendet aktuelles DB-Schema von hourly_data/daily_data
"""
import sqlite3
import time
import logging
import config
from db_utils import get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

DB_PATH = config.DB_PATH

def get_db():
    return get_db_connection()

def aggregate_daily():
    """Aggregiere hourly_data zu daily_data (aktuelles Schema)"""
    conn = get_db()
    c = conn.cursor()
    
    try:
        # Finde letzten aggregierten Tag
        c.execute("SELECT MAX(ts) FROM daily_data")
        last_day = c.fetchone()[0]
        
        now = time.time()
        current_day = (int(now) // 86400) * 86400
        
        if last_day is None:
            # Finde ersten Tag in hourly_data
            c.execute("SELECT MIN(ts) FROM hourly_data")
            first_hour = c.fetchone()[0]
            if not first_hour:
                logging.info("Keine hourly_data vorhanden")
                conn.close()
                return
            start_day = (int(first_hour) // 86400) * 86400
        else:
            start_day = int(last_day)  # Re-aggregiere letzten Tag (könnte partial sein)
        
        count = 0
        # Inkludiere aktuellen Tag (+86400): Monatsansicht zeigt heutigen Tag mit bisherigen Daten
        for day_ts in range(start_day, current_day + 86400, 86400):
            next_day = day_ts + 86400
            
            # Aggregiere aus hourly_data
            # W_*_delta sind in Wh, W_Batt_*_total sind in Wh
            # daily_data soll alles in Wh speichern (API macht /1000 für kWh)
            c.execute("""
                SELECT
                    AVG(P_AC_Inv_avg), MIN(P_AC_Inv_min), MAX(P_AC_Inv_max),
                    AVG(f_Netz_avg), MIN(f_Netz_min), MAX(f_Netz_max),
                    AVG(P_Netz_avg), MIN(P_Netz_min), MAX(P_Netz_max),
                    AVG(P_F2_avg), MIN(P_F2_min), MAX(P_F2_max),
                    AVG(P_F3_avg), MIN(P_F3_min), MAX(P_F3_max),
                    AVG(SOC_Batt_avg), MIN(SOC_Batt_min), MAX(SOC_Batt_max),
                    SUM(W_PV_total_delta),
                    SUM(W_Exp_Netz_delta),
                    SUM(W_Imp_Netz_delta),
                    SUM(W_PV_total_delta + W_Imp_Netz_delta - W_Exp_Netz_delta),
                    SUM(W_Batt_Charge_total),
                    SUM(W_Batt_Discharge_total),
                    SUM(W_WP_total),
                    SUM(W_PV_Direct_total),
                    MIN(W_AC_Inv_start),
                    MAX(W_AC_Inv_end),
                    MIN(W_Exp_Netz_start),
                    MAX(W_Exp_Netz_end),
                    MIN(W_Imp_Netz_start),
                    MAX(W_Imp_Netz_end)
                FROM hourly_data
                WHERE ts >= ? AND ts < ?
            """, (day_ts, next_day))
            
            row = c.fetchone()
            if not row or row[0] is None:
                continue
            
            # Prognose-kWh aus forecast_daily übernehmen (falls vorhanden)
            from datetime import datetime as _dt
            date_str = _dt.utcfromtimestamp(day_ts).strftime('%Y-%m-%d')
            c.execute("SELECT expected_kwh FROM forecast_daily WHERE date = ?", (date_str,))
            fc_row = c.fetchone()
            forecast_kwh = fc_row[0] if fc_row else None

            c.execute("""
                INSERT OR REPLACE INTO daily_data (
                    ts,
                    P_AC_Inv_avg, P_AC_Inv_min, P_AC_Inv_max,
                    f_Netz_avg, f_Netz_min, f_Netz_max,
                    P_Netz_avg, P_Netz_min, P_Netz_max,
                    P_F2_avg, P_F2_min, P_F2_max,
                    P_F3_avg, P_F3_min, P_F3_max,
                    SOC_Batt_avg, SOC_Batt_min, SOC_Batt_max,
                    W_PV_total, W_Exp_Netz_total, W_Imp_Netz_total, W_Consumption_total,
                    W_Batt_Charge_total, W_Batt_Discharge_total, W_WP_total, W_PV_Direct_total,
                    W_AC_Inv_start, W_AC_Inv_end,
                    W_Exp_Netz_start, W_Exp_Netz_end,
                    W_Imp_Netz_start, W_Imp_Netz_end,
                    forecast_kwh
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, tuple([day_ts] + list(row) + [forecast_kwh]))
            count += 1
        
        conn.commit()
        logging.info(f"✓ {count} Tage aggregiert")
        
    except Exception as e:
        logging.error(f"Fehler bei täglicher Aggregation: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    logging.info("Starte tägliche Aggregation")
    aggregate_daily()
    logging.info("Tägliche Aggregation abgeschlossen")
