#!/usr/bin/env python3
"""
Re-Aggregiere ALLE 1-Minuten-Daten aus raw_data
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sqlite3
from datetime import datetime
import config

DB_PATH = config.DB_PATH

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Finde Zeitbereich in raw_data
cur.execute("SELECT MIN(ts), MAX(ts) FROM raw_data")
min_ts, max_ts = cur.fetchone()

if not min_ts:
    print("Keine raw_data vorhanden!")
    exit(1)

# Runde auf Minuten
start_min = int(min_ts // 60) * 60
end_min = int(max_ts // 60) * 60

total_mins = (end_min - start_min) // 60
print(f"Re-aggregiere {total_mins} Minuten von {datetime.fromtimestamp(start_min)} bis {datetime.fromtimestamp(end_min)}")

count = 0
for bucket_ts in range(start_min, end_min + 60, 60):
    # Prüfe ob schon vorhanden
    cur.execute("SELECT 1 FROM data_1min WHERE ts=?", (bucket_ts,))
    if cur.fetchone():
        continue
    
    # Hole Daten
    cur.execute("""SELECT
        AVG(P_DC_Inv), AVG(U_Batt_API), AVG(I_Batt_API), AVG(P_Netz), AVG(P_F2), AVG(P_F3),
        MAX(W_AC_Inv)-MIN(W_AC_Inv), MAX(W_DC1)-MIN(W_DC1), MAX(W_DC2)-MIN(W_DC2),
        MAX(W_Exp_Netz)-MIN(W_Exp_Netz), MAX(W_Imp_Netz)-MIN(W_Imp_Netz),
        MAX(W_Exp_F2)-MIN(W_Exp_F2), MAX(W_Exp_F3)-MIN(W_Exp_F3)
        FROM raw_data WHERE ts>=? AND ts<?""", (bucket_ts, bucket_ts+60))
    
    r = cur.fetchone()
    if not r or r[0] is None:
        continue
    
    P_DC_Inv, U_Batt, I_Batt, P_Netz, P_F2, P_F3 = [x or 0 for x in r[:6]]
    W_AC, W_DC1, W_DC2, W_Exp_Netz, W_Imp_Netz, W_Exp_F2, W_Exp_F3 = [x or 0 for x in r[6:]]
    
    # Berechnungen
    P_Exp = abs(P_Netz) if P_Netz < 0 else 0
    P_Imp = P_Netz if P_Netz >= 0 else 0
    
    I_in = I_Batt if I_Batt >= 0 else 0
    I_out = abs(I_Batt) if I_Batt < 0 else 0
    
    P_inBatt = I_in * U_Batt
    P_outBatt = I_out * U_Batt
    P_Direct = P_DC_Inv - P_inBatt + P_F2 + P_F3
    
    W_Ertrag = W_DC1 + W_DC2 + abs(W_Exp_F2) + abs(W_Exp_F3)
    W_Einspeis = abs(W_Exp_Netz)
    W_Bezug = W_Imp_Netz
    
    batt = W_AC - W_DC1 - W_DC2
    W_inBatt = abs(batt) if batt < 0 else 0
    W_outBatt = batt if batt >= 0 else 0
    
    W_Direct = W_Ertrag - W_inBatt
    W_Verbrauch = W_Ertrag - W_Einspeis + W_Bezug
    
    # INSERT
    cur.execute("""INSERT INTO data_1min (ts, P_Exp, P_Imp, I_inBatt_avg, I_outBatt_avg,
        P_inBatt, P_outBatt, P_Direct, W_Ertrag, W_Einspeis, W_Bezug,
        W_inBatt, W_outBatt, W_Direct, W_Verbrauch)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        bucket_ts, P_Exp, P_Imp, I_in, I_out,
        P_inBatt, P_outBatt, P_Direct,
        W_Ertrag, W_Einspeis, W_Bezug,
        W_inBatt, W_outBatt, W_Direct, W_Verbrauch
    ))
    
    count += 1
    if count % 100 == 0:
        conn.commit()
        print(f"  {count}/{total_mins} - {datetime.fromtimestamp(bucket_ts)}")

conn.commit()
conn.close()

print(f"\nFertig! {count} Minuten aggregiert")
