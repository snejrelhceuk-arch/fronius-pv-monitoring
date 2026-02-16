#!/usr/bin/env python3
"""
Aggregations-Script für Fronius PV-Datenbank
Aggregiert: 5s → 15min → hourly
Cleanup: raw_data >72h
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

def aggregate_15min():
    """Aggregiere 5s-Daten zu 15min-Blöcken.
    
    Primärquelle: raw_data (volle Auflösung)
    Fallback:     data_1min (wenn raw_data bereits gelöscht)
    
    Damit werden Lücken in data_15min auch nach raw_data-Cleanup
    automatisch aus data_1min gefüllt.
    """
    conn = get_db()
    c = conn.cursor()
    
    # Letzte aggregierte 15min
    c.execute("SELECT MAX(ts) FROM data_15min")
    last_agg = c.fetchone()[0]
    
    now = time.time()
    current_15min = (int(now) // 900) * 900
    
    if last_agg is None:
        # Frühesten Datenpunkt finden (raw_data oder data_1min)
        c.execute("SELECT MIN(ts) FROM raw_data")
        min_ts = c.fetchone()[0]
        if not min_ts:
            c.execute("SELECT MIN(ts) FROM data_1min")
            min_ts = c.fetchone()[0]
        if not min_ts:
            logging.info("Keine raw_data/data_1min vorhanden")
            conn.close()
            return
        start_15min = (int(min_ts) // 900) * 900
    else:
        # Re-aggregiere letzten Bucket (könnte partial gewesen sein)
        start_15min = int(last_agg)
    
    count = 0
    for ts_15min in range(start_15min, current_15min, 900):
        next_15min = ts_15min + 900
        
        # Aggregiere für dieses 15min-Fenster
        c.execute("""
            INSERT OR REPLACE INTO data_15min (
                ts,
                P_AC_Inv_avg, P_AC_Inv_min, P_AC_Inv_max,
                I_L1_Inv_avg, I_L1_Inv_min, I_L1_Inv_max,
                I_L2_Inv_avg, I_L2_Inv_min, I_L2_Inv_max,
                I_L3_Inv_avg, I_L3_Inv_min, I_L3_Inv_max,
                U_L1_N_Inv_avg, U_L1_N_Inv_min, U_L1_N_Inv_max,
                U_L2_N_Inv_avg, U_L2_N_Inv_min, U_L2_N_Inv_max,
                U_L3_N_Inv_avg, U_L3_N_Inv_min, U_L3_N_Inv_max,
                P_DC_Inv_avg, P_DC_Inv_min, P_DC_Inv_max,
                P_DC1_avg, P_DC1_min, P_DC1_max,
                P_DC2_avg, P_DC2_min, P_DC2_max,
                SOC_Batt_avg, SOC_Batt_min, SOC_Batt_max,
                U_Batt_API_avg, U_Batt_API_min, U_Batt_API_max,
                I_Batt_API_avg, I_Batt_API_min, I_Batt_API_max,
                P_Netz_avg, P_Netz_min, P_Netz_max,
                f_Netz_avg, f_Netz_min, f_Netz_max,
                U_L1_N_Netz_avg, U_L1_N_Netz_min, U_L1_N_Netz_max,
                U_L2_N_Netz_avg, U_L2_N_Netz_min, U_L2_N_Netz_max,
                U_L3_N_Netz_avg, U_L3_N_Netz_min, U_L3_N_Netz_max,
                P_F2_avg, P_F2_min, P_F2_max,
                P_F3_avg, P_F3_min, P_F3_max,
                P_WP_avg, P_WP_min, P_WP_max,
                W_PV_total_delta,
                W_DC1_delta,
                W_DC2_delta,
                W_Exp_Netz_delta,
                W_Imp_Netz_delta,
                W_Exp_F2_delta,
                W_Imp_F2_delta,
                W_Exp_F3_delta,
                W_Imp_F3_delta,
                W_Exp_WP_delta,
                W_Imp_WP_delta,
                W_AC_Inv_start,
                W_AC_Inv_end,
                W_DC1_start,
                W_DC1_end,
                W_DC2_start,
                W_DC2_end,
                W_Exp_Netz_start,
                W_Exp_Netz_end,
                W_Imp_Netz_start,
                W_Imp_Netz_end,
                W_Exp_F2_start,
                W_Exp_F2_end,
                W_Imp_F2_start,
                W_Imp_F2_end,
                W_Exp_F3_start,
                W_Exp_F3_end,
                W_Imp_F3_start,
                W_Imp_F3_end,
                W_Imp_WP_start,
                W_Imp_WP_end
            )
            SELECT
                ? as ts,
                AVG(P_AC_Inv), MIN(P_AC_Inv), MAX(P_AC_Inv),
                AVG(I_L1_Inv), MIN(I_L1_Inv), MAX(I_L1_Inv),
                AVG(I_L2_Inv), MIN(I_L2_Inv), MAX(I_L2_Inv),
                AVG(I_L3_Inv), MIN(I_L3_Inv), MAX(I_L3_Inv),
                AVG(U_L1_N_Inv), MIN(U_L1_N_Inv), MAX(U_L1_N_Inv),
                AVG(U_L2_N_Inv), MIN(U_L2_N_Inv), MAX(U_L2_N_Inv),
                AVG(U_L3_N_Inv), MIN(U_L3_N_Inv), MAX(U_L3_N_Inv),
                AVG(P_DC_Inv), MIN(P_DC_Inv), MAX(P_DC_Inv),
                AVG(P_DC1), MIN(P_DC1), MAX(P_DC1),
                AVG(P_DC2), MIN(P_DC2), MAX(P_DC2),
                AVG(SOC_Batt), MIN(SOC_Batt), MAX(SOC_Batt),
                AVG(U_Batt_API), MIN(U_Batt_API), MAX(U_Batt_API),
                AVG(I_Batt_API), MIN(I_Batt_API), MAX(I_Batt_API),
                AVG(P_Netz), MIN(P_Netz), MAX(P_Netz),
                AVG(f_Netz), MIN(f_Netz), MAX(f_Netz),
                AVG(U_L1_N_Netz), MIN(U_L1_N_Netz), MAX(U_L1_N_Netz),
                AVG(U_L2_N_Netz), MIN(U_L2_N_Netz), MAX(U_L2_N_Netz),
                AVG(U_L3_N_Netz), MIN(U_L3_N_Netz), MAX(U_L3_N_Netz),
                AVG(P_F2), MIN(P_F2), MAX(P_F2),
                AVG(P_F3), MIN(P_F3), MAX(P_F3),
                AVG(P_WP), MIN(P_WP), MAX(P_WP),
                ((MAX(W_DC1) + MAX(W_DC2)) - (MIN(W_DC1) + MIN(W_DC2))) + (MAX(W_Exp_F2) - MIN(W_Exp_F2)) + (MAX(W_Exp_F3) - MIN(W_Exp_F3)),
                MAX(W_DC1) - MIN(W_DC1),
                MAX(W_DC2) - MIN(W_DC2),
                MAX(W_Exp_Netz) - MIN(W_Exp_Netz),
                MAX(W_Imp_Netz) - MIN(W_Imp_Netz),
                MAX(W_Exp_F2) - MIN(W_Exp_F2),
                MAX(W_Imp_F2) - MIN(W_Imp_F2),
                MAX(W_Exp_F3) - MIN(W_Exp_F3),
                MAX(W_Imp_F3) - MIN(W_Imp_F3),
                0,  -- W_Exp_WP (keine Einspeisung)
                MAX(W_Imp_WP) - MIN(W_Imp_WP),
                MIN(W_AC_Inv),
                MAX(W_AC_Inv),
                MIN(W_DC1),
                MAX(W_DC1),
                MIN(W_DC2),
                MAX(W_DC2),
                MIN(W_Exp_Netz),
                MAX(W_Exp_Netz),
                MIN(W_Imp_Netz),
                MAX(W_Imp_Netz),
                MIN(W_Exp_F2),
                MAX(W_Exp_F2),
                MIN(W_Imp_F2),
                MAX(W_Imp_F2),
                MIN(W_Exp_F3),
                MAX(W_Exp_F3),
                MIN(W_Imp_F3),
                MAX(W_Imp_F3),
                MIN(W_Imp_WP),
                MAX(W_Imp_WP)
            FROM raw_data
            WHERE ts >= ? AND ts < ?
            HAVING COUNT(*) > 0
        """, (ts_15min, ts_15min, next_15min))
        
        if c.rowcount > 0:
            count += 1
    
    conn.commit()
    
    # ─── Fallback: Lücken aus data_1min füllen ───────────────
    # Wenn raw_data für ein Fenster bereits gelöscht war, versuche data_1min.
    # data_1min hat _avg/_min/_max/_delta/_start/_end Spalten.
    fallback_count = _fill_15min_gaps_from_1min(conn, start_15min, current_15min)
    
    conn.close()
    logging.info(f"✓ {count} x 15min aus raw_data, {fallback_count} x aus data_1min (Fallback)")


def _fill_15min_gaps_from_1min(conn, start_ts, end_ts):
    """Füllt Lücken in data_15min aus data_1min (Fallback-Aggregation).
    
    Wird automatisch aufgerufen wenn raw_data für einen Zeitraum
    bereits durch Retention gelöscht wurde, data_1min aber noch existiert.
    """
    c = conn.cursor()
    
    # Gemeinsame Spalten zwischen data_15min und data_1min ermitteln
    cols_15 = [r[1] for r in c.execute("PRAGMA table_info(data_15min)") if r[1] != 'ts']
    cols_1m = set(r[1] for r in c.execute("PRAGMA table_info(data_1min)"))
    
    insert_cols = ['ts']
    select_parts = []
    for col in cols_15:
        if col not in cols_1m:
            continue
        insert_cols.append(col)
        if col.endswith('_avg'):
            select_parts.append(f"AVG({col})")
        elif col.endswith('_min'):
            select_parts.append(f"MIN({col})")
        elif col.endswith('_max'):
            select_parts.append(f"MAX({col})")
        elif col.endswith('_delta') or col.endswith('_total'):
            select_parts.append(f"SUM({col})")
        elif col.endswith('_start'):
            select_parts.append(f"MIN({col})")
        elif col.endswith('_end'):
            select_parts.append(f"MAX({col})")
        else:
            select_parts.append(f"AVG({col})")
    
    if not select_parts:
        return 0
    
    sql = f"""
        INSERT OR IGNORE INTO data_15min ({', '.join(insert_cols)})
        SELECT ?, {', '.join(select_parts)}
        FROM data_1min
        WHERE ts >= ? AND ts < ?
        HAVING COUNT(*) > 0
    """
    
    count = 0
    for ts in range(start_ts, end_ts, 900):
        c.execute(sql, (ts, ts, ts + 900))
        if c.execute("SELECT changes()").fetchone()[0] > 0:
            count += 1
    
    if count > 0:
        conn.commit()
    return count

def aggregate_hourly():
    """Aggregiere 15min-Daten zu stündlichen Blöcken"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT MAX(ts) FROM hourly_data")
    last_agg = c.fetchone()[0]
    
    now = time.time()
    current_hour = (int(now) // 3600) * 3600
    
    if last_agg is None:
        c.execute("SELECT MIN(ts) FROM data_15min")
        min_ts = c.fetchone()[0]
        if not min_ts:
            logging.info("Keine 15min-Daten vorhanden")
            conn.close()
            return
        start_hour = (int(min_ts) // 3600) * 3600
    else:
        # Re-aggregiere letzte Stunde (könnte partial gewesen sein)
        start_hour = int(last_agg)
    
    count = 0
    for ts_hour in range(start_hour, current_hour, 3600):
        next_hour = ts_hour + 3600
        
        c.execute("""
            INSERT OR REPLACE INTO hourly_data (
                ts,
                P_AC_Inv_avg, P_AC_Inv_min, P_AC_Inv_max,
                P_DC_Inv_avg, P_DC_Inv_min, P_DC_Inv_max,
                P_DC1_avg, P_DC1_min, P_DC1_max,
                P_DC2_avg, P_DC2_min, P_DC2_max,
                SOC_Batt_avg, SOC_Batt_min, SOC_Batt_max,
                U_Batt_API_avg, U_Batt_API_min, U_Batt_API_max,
                I_Batt_API_avg, I_Batt_API_min, I_Batt_API_max,
                P_Netz_avg, P_Netz_min, P_Netz_max,
                f_Netz_avg, f_Netz_min, f_Netz_max,
                P_F2_avg, P_F2_min, P_F2_max,
                P_F3_avg, P_F3_min, P_F3_max,
                P_WP_avg, P_WP_min, P_WP_max,
                W_PV_total_delta,
                W_Exp_Netz_delta,
                W_Imp_Netz_delta,
                W_Batt_Charge_total,
                W_Batt_Discharge_total,
                W_WP_total,
                W_PV_Direct_total,
                W_AC_Inv_start,
                W_AC_Inv_end,
                W_Exp_Netz_start,
                W_Exp_Netz_end,
                W_Imp_Netz_start,
                W_Imp_Netz_end
            )
            SELECT
                ? as ts,
                AVG(P_AC_Inv_avg), MIN(P_AC_Inv_min), MAX(P_AC_Inv_max),
                AVG(P_DC_Inv_avg), MIN(P_DC_Inv_min), MAX(P_DC_Inv_max),
                AVG(P_DC1_avg), MIN(P_DC1_min), MAX(P_DC1_max),
                AVG(P_DC2_avg), MIN(P_DC2_min), MAX(P_DC2_max),
                AVG(SOC_Batt_avg), MIN(SOC_Batt_min), MAX(SOC_Batt_max),
                AVG(U_Batt_API_avg), MIN(U_Batt_API_min), MAX(U_Batt_API_max),
                AVG(I_Batt_API_avg), MIN(I_Batt_API_min), MAX(I_Batt_API_max),
                AVG(P_Netz_avg), MIN(P_Netz_min), MAX(P_Netz_max),
                AVG(f_Netz_avg), MIN(f_Netz_min), MAX(f_Netz_max),
                AVG(P_F2_avg), MIN(P_F2_min), MAX(P_F2_max),
                AVG(P_F3_avg), MIN(P_F3_min), MAX(P_F3_max),
                AVG(P_WP_avg), MIN(P_WP_min), MAX(P_WP_max),
                SUM(W_PV_total_delta),
                SUM(W_Exp_Netz_delta),
                SUM(W_Imp_Netz_delta),
                SUM((P_DC1_avg + P_DC2_avg - P_AC_Inv_avg) * 0.25 * (CASE WHEN (P_DC1_avg + P_DC2_avg - P_AC_Inv_avg) > 0 THEN 1 ELSE 0 END)),
                SUM(ABS(P_DC1_avg + P_DC2_avg - P_AC_Inv_avg) * 0.25 * (CASE WHEN (P_DC1_avg + P_DC2_avg - P_AC_Inv_avg) < 0 THEN 1 ELSE 0 END)),
                SUM(COALESCE(W_Imp_WP_delta, 0)),
                MAX(0, SUM(W_PV_total_delta - W_Exp_Netz_delta) - SUM((P_DC1_avg + P_DC2_avg - P_AC_Inv_avg) * 0.25 * (CASE WHEN (P_DC1_avg + P_DC2_avg - P_AC_Inv_avg) > 0 THEN 1 ELSE 0 END))),
                MIN(W_AC_Inv_start),
                MAX(W_AC_Inv_end),
                MIN(W_Exp_Netz_start),
                MAX(W_Exp_Netz_end),
                MIN(W_Imp_Netz_start),
                MAX(W_Imp_Netz_end)
            FROM data_15min
            WHERE ts >= ? AND ts < ?
            HAVING COUNT(*) > 0
        """, (ts_hour, ts_hour, next_hour))
        
        if c.rowcount > 0:
            count += 1
    
    conn.commit()
    conn.close()
    logging.info(f"✓ {count} x Stunden-Aggregate erstellt")

def cleanup_old_data():
    """Lösche raw_data älter als Retention-Policy (redundant zu modbus_v3.py cleanup_db)"""
    # Cleanup wird zentral über modbus_v3.py cleanup_db() gesteuert
    # Hier nur raw_data als Fallback, falls Collector nicht läuft
    conn = get_db()
    c = conn.cursor()
    
    cutoff = time.time() - (config.RAW_DATA_RETENTION_DAYS * 86400)
    c.execute("DELETE FROM raw_data WHERE ts < ?", (cutoff,))
    deleted = c.rowcount
    
    conn.commit()
    conn.close()
    if deleted > 0:
        logging.info(f"✓ {deleted} alte raw_data Zeilen gelöscht")

if __name__ == '__main__':
    logging.info("=== Start Aggregation ===")
    aggregate_15min()
    aggregate_hourly()
    cleanup_old_data()
    logging.info("=== Aggregation abgeschlossen ===")
