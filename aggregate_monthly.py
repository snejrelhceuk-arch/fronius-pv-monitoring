#!/usr/bin/env python3
"""
Monatliche Aggregation: data_15min → data_monthly
Läuft alle 15min via Cron (aktualisiert laufenden Monat)
"""
import sys
import sqlite3
from datetime import datetime, timedelta
import logging
import config
from host_role import is_failover
from db_utils import get_db_connection

if is_failover():
    sys.exit(0)

DB_PATH = config.DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_month_start(date):
    """Berechne 1. des Monats 00:00"""
    return date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

def aggregate_monthly():
    """Aggregiere 15min-Daten zu Monatsdaten"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        now = datetime.now()
        current_month_start = get_month_start(now)
        
        # Finde letzten aggregierten Monat
        last_monthly = cursor.execute(
            "SELECT MAX(ts) FROM data_monthly"
        ).fetchone()[0]
        
        if last_monthly:
            # Re-aggregiere immer die letzten 2 Monate (aktueller + vorheriger)
            prev_month = current_month_start.replace(day=1)
            if prev_month.month == 1:
                prev_month = datetime(prev_month.year - 1, 12, 1)
            else:
                prev_month = datetime(prev_month.year, prev_month.month - 1, 1)
            start_date = prev_month
        else:
            # Finde erste verfügbare 15min-Daten
            first_15min = cursor.execute(
                "SELECT MIN(ts) FROM data_15min"
            ).fetchone()[0]
            if not first_15min:
                logging.info("Keine 15min-Daten vorhanden")
                return
            start_date = datetime.fromtimestamp(first_15min)
            start_date = get_month_start(start_date)
        
        current_month = get_month_start(start_date)
        
        count = 0
        while current_month <= current_month_start:
            month_start_ts = int(current_month.timestamp())
            
            # Nächster Monat
            if current_month.month == 12:
                next_month = datetime(current_month.year + 1, 1, 1)
            else:
                next_month = datetime(current_month.year, current_month.month + 1, 1)
            month_end_ts = int(next_month.timestamp())
            
            # Aggregiere aus 15min-Daten
            # _start/_end: Absolute Zählerstände am Monatsrand (Fixpunkte)
            # MIN(_start) = erster Zählerstand des Monats
            # MAX(_end) = letzter Zählerstand des Monats
            # NULLIF(..., 0): Schema-Default 0.0 ignorieren (Altdaten ohne echte Zählerstände)
            cursor.execute("""
                INSERT OR REPLACE INTO data_monthly (
                    ts,
                    W_PV_total_delta, W_Exp_Netz_delta, W_Imp_Netz_delta,
                    W_DC1_delta, W_DC2_delta,
                    W_Exp_F2_delta, W_Imp_F2_delta,
                    W_Exp_F3_delta, W_Imp_F3_delta,
                    W_Exp_WP_delta, W_Imp_WP_delta,
                    f_Netz_min, f_Netz_max, f_Netz_avg,
                    P_AC_Inv_min, P_AC_Inv_max, P_AC_Inv_avg,
                    P_DC_Inv_min, P_DC_Inv_max, P_DC_Inv_avg,
                    P_DC1_min, P_DC1_max, P_DC1_avg,
                    P_DC2_min, P_DC2_max, P_DC2_avg,
                    SOC_Batt_min, SOC_Batt_max, SOC_Batt_avg,
                    P_Netz_min, P_Netz_max, P_Netz_avg,
                    U_L1_N_Netz_min, U_L1_N_Netz_max, U_L1_N_Netz_avg,
                    U_L2_N_Netz_min, U_L2_N_Netz_max, U_L2_N_Netz_avg,
                    U_L3_N_Netz_min, U_L3_N_Netz_max, U_L3_N_Netz_avg,
                    P_F2_min, P_F2_max, P_F2_avg,
                    P_F3_min, P_F3_max, P_F3_avg,
                    P_WP_min, P_WP_max, P_WP_avg,
                    W_Batt_Charge_total, W_Batt_Discharge_total, W_PV_Direct_total,
                    W_AC_Inv_start, W_AC_Inv_end,
                    W_DC1_start, W_DC1_end,
                    W_DC2_start, W_DC2_end,
                    W_Exp_Netz_start, W_Exp_Netz_end,
                    W_Imp_Netz_start, W_Imp_Netz_end,
                    W_Exp_F2_start, W_Exp_F2_end,
                    W_Imp_F2_start, W_Imp_F2_end,
                    W_Exp_F3_start, W_Exp_F3_end,
                    W_Imp_F3_start, W_Imp_F3_end,
                    W_Imp_WP_start, W_Imp_WP_end
                )
                SELECT 
                    ?,
                    SUM(W_PV_total_delta), SUM(W_Exp_Netz_delta), SUM(W_Imp_Netz_delta),
                    SUM(W_DC1_delta), SUM(W_DC2_delta),
                    SUM(W_Exp_F2_delta), SUM(W_Imp_F2_delta),
                    SUM(W_Exp_F3_delta), SUM(W_Imp_F3_delta),
                    SUM(W_Exp_WP_delta), SUM(W_Imp_WP_delta),
                    MIN(f_Netz_min), MAX(f_Netz_max), AVG(f_Netz_avg),
                    MIN(P_AC_Inv_min), MAX(P_AC_Inv_max), AVG(P_AC_Inv_avg),
                    MIN(P_DC_Inv_min), MAX(P_DC_Inv_max), AVG(P_DC_Inv_avg),
                    MIN(P_DC1_min), MAX(P_DC1_max), AVG(P_DC1_avg),
                    MIN(P_DC2_min), MAX(P_DC2_max), AVG(P_DC2_avg),
                    MIN(SOC_Batt_min), MAX(SOC_Batt_max), AVG(SOC_Batt_avg),
                    MIN(P_Netz_min), MAX(P_Netz_max), AVG(P_Netz_avg),
                    MIN(U_L1_N_Netz_min), MAX(U_L1_N_Netz_max), AVG(U_L1_N_Netz_avg),
                    MIN(U_L2_N_Netz_min), MAX(U_L2_N_Netz_max), AVG(U_L2_N_Netz_avg),
                    MIN(U_L3_N_Netz_min), MAX(U_L3_N_Netz_max), AVG(U_L3_N_Netz_avg),
                    MIN(P_F2_min), MAX(P_F2_max), AVG(P_F2_avg),
                    MIN(P_F3_min), MAX(P_F3_max), AVG(P_F3_avg),
                    MIN(P_WP_min), MAX(P_WP_max), AVG(P_WP_avg),
                    SUM(CASE WHEN I_Batt_API_avg >= 0 THEN (I_Batt_API_avg * U_Batt_API_avg) * 0.25 ELSE 0 END),
                    SUM(CASE WHEN I_Batt_API_avg < 0 THEN (ABS(I_Batt_API_avg) * U_Batt_API_avg) * 0.25 ELSE 0 END),
                    MAX(0, SUM(W_PV_total_delta - W_Exp_Netz_delta) - SUM(CASE WHEN I_Batt_API_avg >= 0 THEN (I_Batt_API_avg * U_Batt_API_avg) * 0.25 ELSE 0 END)),
                    MIN(NULLIF(W_AC_Inv_start, 0)), MAX(NULLIF(W_AC_Inv_end, 0)),
                    MIN(NULLIF(W_DC1_start, 0)), MAX(NULLIF(W_DC1_end, 0)),
                    MIN(NULLIF(W_DC2_start, 0)), MAX(NULLIF(W_DC2_end, 0)),
                    MIN(NULLIF(W_Exp_Netz_start, 0)), MAX(NULLIF(W_Exp_Netz_end, 0)),
                    MIN(NULLIF(W_Imp_Netz_start, 0)), MAX(NULLIF(W_Imp_Netz_end, 0)),
                    MIN(NULLIF(W_Exp_F2_start, 0)), MAX(NULLIF(W_Exp_F2_end, 0)),
                    MIN(NULLIF(W_Imp_F2_start, 0)), MAX(NULLIF(W_Imp_F2_end, 0)),
                    MIN(NULLIF(W_Exp_F3_start, 0)), MAX(NULLIF(W_Exp_F3_end, 0)),
                    MIN(NULLIF(W_Imp_F3_start, 0)), MAX(NULLIF(W_Imp_F3_end, 0)),
                    MIN(NULLIF(W_Imp_WP_start, 0)), MAX(NULLIF(W_Imp_WP_end, 0))
                FROM data_15min
                WHERE ts >= ? AND ts < ?
                AND W_PV_total_delta IS NOT NULL
            """, (month_start_ts, month_start_ts, month_end_ts))
            
            if cursor.rowcount > 0:
                count += 1
                logging.info(f"Monat {current_month.strftime('%Y-%m')} aggregiert")
            
            current_month = next_month
        
        conn.commit()
        logging.info(f"✓ {count} Monate aggregiert")
        
    except Exception as e:
        logging.error(f"Fehler bei Monatsaggregation: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    aggregate_monthly()
