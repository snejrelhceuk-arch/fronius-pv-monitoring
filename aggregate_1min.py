#!/usr/bin/env python3
"""
1-Minuten Aggregation aus raw_data - VERSION 2.0 FINAL
Läuft jede Minute via Cron

KORRIGIERTE VORZEICHEN-KONVENTIONEN (10.01.2026):
- P_Netz: positiv=Bezug, negativ=Einspeisung
- W_Exp_Netz: negativ (wird abs() für Einspeisung)
- W_Imp_Netz: positiv (bleibt so für Bezug)
- W_Exp_F2/F3: negativ aus TotWhImp (wird abs() für Ertrag)
"""

import sqlite3
import time
import config
from db_utils import get_db_connection

DB_PATH = config.DB_PATH

def aggregate_1min():
    """Aggregiere die letzte vollständige Minute mit ALLEN Berechnungen.
    Inkl. Backfill: Prüfe die letzten 10 Minuten auf fehlende Buckets.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        now = int(time.time())
        
        # Backfill: Prüfe die letzten 10 Minuten auf Lücken
        # (Collector hat ~88s-Pausen alle ~5.5 Min → 1-2 Buckets gehen verloren)
        for offset in range(10, 0, -1):
            bucket_ts = ((now - offset * 60) // 60) * 60
            cur.execute("SELECT 1 FROM data_1min WHERE ts = ?", (bucket_ts,))
            if not cur.fetchone():
                # Prüfe ob raw_data für diesen Bucket existiert
                cur.execute("SELECT COUNT(*) FROM raw_data WHERE ts >= ? AND ts < ?",
                            (bucket_ts, bucket_ts + 60))
                raw_count = cur.fetchone()[0]
                if raw_count >= 2:
                    _aggregate_1min_impl(conn, cur, bucket_ts)
    except Exception as e:
        conn.rollback()
        import logging
        logging.error(f"Fehler bei 1min-Aggregation: {e}")
    finally:
        conn.close()

def _aggregate_1min_impl(conn, cur, bucket_ts):
    
    # Prüfe nochmals ob bereits vorhanden (Race Condition)
    cur.execute("SELECT 1 FROM data_1min WHERE ts = ?", (bucket_ts,))
    if cur.fetchone():
        return
    
    # Aggregiere raw_data - NUR DIE WERTE DIE WIR BRAUCHEN
    cur.execute("""
        SELECT
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
            MAX(W_AC_Inv) - MIN(W_AC_Inv),
            MAX(W_DC1) - MIN(W_DC1),
            MAX(W_DC2) - MIN(W_DC2),
            MAX(W_Exp_Netz) - MIN(W_Exp_Netz),
            MAX(W_Imp_Netz) - MIN(W_Imp_Netz),
            MAX(W_Exp_F2) - MIN(W_Exp_F2),
            MAX(W_Imp_F2) - MIN(W_Imp_F2),
            MAX(W_Exp_F3) - MIN(W_Exp_F3),
            MAX(W_Imp_F3) - MIN(W_Imp_F3),
            MAX(W_Imp_WP) - MIN(W_Imp_WP),
            (SELECT W_AC_Inv FROM raw_data WHERE ts >= ? AND ts < ? ORDER BY ts ASC LIMIT 1) as W_AC_Inv_start,
            (SELECT W_AC_Inv FROM raw_data WHERE ts >= ? AND ts < ? ORDER BY ts DESC LIMIT 1) as W_AC_Inv_end,
            (SELECT W_DC1 FROM raw_data WHERE ts >= ? AND ts < ? ORDER BY ts ASC LIMIT 1) as W_DC1_start,
            (SELECT W_DC1 FROM raw_data WHERE ts >= ? AND ts < ? ORDER BY ts DESC LIMIT 1) as W_DC1_end,
            (SELECT W_DC2 FROM raw_data WHERE ts >= ? AND ts < ? ORDER BY ts ASC LIMIT 1) as W_DC2_start,
            (SELECT W_DC2 FROM raw_data WHERE ts >= ? AND ts < ? ORDER BY ts DESC LIMIT 1) as W_DC2_end,
            (SELECT W_Exp_Netz FROM raw_data WHERE ts >= ? AND ts < ? ORDER BY ts ASC LIMIT 1) as W_Exp_Netz_start,
            (SELECT W_Exp_Netz FROM raw_data WHERE ts >= ? AND ts < ? ORDER BY ts DESC LIMIT 1) as W_Exp_Netz_end,
            (SELECT W_Imp_Netz FROM raw_data WHERE ts >= ? AND ts < ? ORDER BY ts ASC LIMIT 1) as W_Imp_Netz_start,
            (SELECT W_Imp_Netz FROM raw_data WHERE ts >= ? AND ts < ? ORDER BY ts DESC LIMIT 1) as W_Imp_Netz_end
        FROM raw_data
        WHERE ts >= ? AND ts < ?
    """, (bucket_ts, bucket_ts + 60,
          bucket_ts, bucket_ts + 60,
          bucket_ts, bucket_ts + 60,
          bucket_ts, bucket_ts + 60,
          bucket_ts, bucket_ts + 60,
          bucket_ts, bucket_ts + 60,
          bucket_ts, bucket_ts + 60,
          bucket_ts, bucket_ts + 60,
          bucket_ts, bucket_ts + 60,
          bucket_ts, bucket_ts + 60,
          bucket_ts, bucket_ts + 60))
    
    row = cur.fetchone()
    if not row or row[0] is None:
        return
    
    # Validierung: SQL-Spaltenanzahl muss zu den Index-Konstanten passen
    # 21 AVG/MIN/MAX-Triplets (0-62) + 10 Deltas (63-72) + 10 Absolut-Werte (73-82) = 83
    if len(row) != 83:
        import logging
        logging.error(f"aggregate_1min: Unerwartete Spaltenanzahl {len(row)}, erwartet 83 — Indizes prüfen!")
        return
    
    # === KORREKTE INDIZES (basierend auf SELECT oben) ===
    # Index 0-2: P_AC_Inv, Index 21-23: P_DC_Inv, Index 24-26: P_DC1, Index 27-29: P_DC2
    # Index 30-32: SOC_Batt, Index 33-35: U_Batt_API, Index 36-38: I_Batt_API
    # Index 39-41: P_Netz, Index 54-56: P_F2, Index 57-59: P_F3, Index 60-62: P_WP
    P_AC_Inv_avg = row[0] or 0.0   # AVG(P_AC_Inv) - WICHTIG FÜR P_PV_total!
    P_DC_Inv_avg = row[21] or 0.0  # AVG(P_DC_Inv)
    P_DC1_avg = row[24] or 0.0     # AVG(P_DC1)
    P_DC2_avg = row[27] or 0.0     # AVG(P_DC2)
    SOC_Batt_avg = row[30] or 0.0  # AVG(SOC_Batt)
    U_Batt_avg = row[33] or 0.0    # AVG(U_Batt_API)
    I_Batt_avg = row[36] or 0.0    # AVG(I_Batt_API)
    P_Netz_avg = row[39] or 0.0    # AVG(P_Netz)
    P_F2_avg = row[54] or 0.0      # AVG(P_F2)
    P_F3_avg = row[57] or 0.0      # AVG(P_F3)
    P_WP_avg = row[60] or 0.0      # AVG(P_WP)
    
    # Delta-Werte ab Index 63
    W_AC_Inv_delta = row[63] or 0.0    # MAX(W_AC_Inv) - MIN(W_AC_Inv)
    W_DC1_delta = row[64] or 0.0
    W_DC2_delta = row[65] or 0.0
    W_Exp_Netz_delta = row[66] or 0.0  # NEGATIV bei Einspeisung!
    W_Imp_Netz_delta = row[67] or 0.0  # POSITIV bei Bezug
    W_Exp_F2_delta = row[68] or 0.0    # NEGATIV (aus TotWhImp)
    W_Imp_F2_delta = row[69] or 0.0
    W_Exp_F3_delta = row[70] or 0.0    # NEGATIV (aus TotWhImp)
    W_Imp_F3_delta = row[71] or 0.0
    W_Imp_WP_delta = row[72] or 0.0
    
    # Absolute Zählerstände (Start/End) ab Index 73
    W_AC_Inv_start = row[73]
    W_AC_Inv_end = row[74]
    W_DC1_start = row[75]
    W_DC1_end = row[76]
    W_DC2_start = row[77]
    W_DC2_end = row[78]
    W_Exp_Netz_start = row[79]
    W_Exp_Netz_end = row[80]
    W_Imp_Netz_start = row[81]
    W_Imp_Netz_end = row[82]
    
    # === BERECHNETE LEISTUNGSWERTE ===
    
    # P_Exp = Einspeisung (wenn P_Netz NEGATIV)
    P_Exp = abs(P_Netz_avg) if P_Netz_avg < 0 else 0.0
    
    # P_Imp = Bezug (wenn P_Netz POSITIV)
    P_Imp = P_Netz_avg if P_Netz_avg >= 0 else 0.0
    
    # === ENERGIE AUS LEISTUNG BERECHNEN ===
    # KRITISCH: W_DC1/W_DC2 Counter sammeln ~5 Min auf → unbrauchbar für 1-Min Aggregation!
    # Counter springen z.B. um 90 Wh bei 12:00 (= 5 Min Produktion) → 1 Minute bekommt 5x zu viel!
    # LÖSUNG: IMMER aus Leistung integrieren (P × t), Counter IGNORIEREN
    
    # F1 MPPT Energy aus Leistung (pure PV, keine Batterie!)
    W_DC1_delta = (P_DC1_avg * 60) / 3600 if P_DC1_avg > 0 else 0.0
    W_DC2_delta = (P_DC2_avg * 60) / 3600 if P_DC2_avg > 0 else 0.0
    
    # AC-Inv Energy (nur für Batterie-Berechnung verwendet, nicht für W_Ertrag)
    if W_AC_Inv_delta == 0 and P_DC_Inv_avg > 50:
        W_AC_Inv_delta = (P_DC_Inv_avg * 60) / 3600
    
    # KRITISCH: Netz Counter (W_Exp_Netz, W_Imp_Netz) haben unregelmäßige Updates!
    # 6.2.2026: Counter W_Bezug=41.91kWh, Power=77.45kWh (-35.54kWh = nur 54%!)
    # LÖSUNG: IMMER aus Leistung integrieren (wie F1/F2/F3) → Counter IGNORIEREN
    W_Exp_Netz_delta = -(P_Exp * 60) / 3600 if P_Exp > 0 else 0.0  # NEGATIV!
    W_Imp_Netz_delta = (P_Imp * 60) / 3600 if P_Imp > 0 else 0.0
    
    # KRITISCH: F2/F3 SmartMeter Counter haben unregelmäßige Updates (wie W_DC1/W_DC2!)
    # 6.2.2026 Counter-Delta: F2=3.38kWh, F3=1.02kWh (nur 50% erfasst!)
    # Power-Integration:      F2=6.72kWh, F3=2.17kWh (korrekt!)
    # LÖSUNG: IMMER aus Leistung integrieren → F2/F3 Counter komplett IGNORIEREN
    W_Exp_F2_delta = -(P_F2_avg * 60) / 3600 if P_F2_avg > 0 else 0.0  # NEGATIV!
    W_Exp_F3_delta = -(P_F3_avg * 60) / 3600 if P_F3_avg > 0 else 0.0  # NEGATIV!
    
    # Batterie-Ströme aufteilen (positiv=Ladung, negativ=Entladung)
    I_inBatt_avg = I_Batt_avg if I_Batt_avg >= 0 else 0.0
    I_outBatt_avg = abs(I_Batt_avg) if I_Batt_avg < 0 else 0.0
    
    # Batterie-Leistungen GESAMT
    P_inBatt_total = I_inBatt_avg * U_Batt_avg
    P_outBatt = I_outBatt_avg * U_Batt_avg
    
    # === BATTERIE-QUELLEN TRENNEN: PV vs NETZ ===
    # Heuristik: Wenn Netzbezug > Batterie-Ladung → Zwangsnachladung aus Netz
    # Beispiel: 9kW Batt-Ladung + 0,1kW Bezug (Lastwechsel) → Batterie lädt aus PV
    if P_Imp > P_inBatt_total:
        # Netzbezug größer als Batterie-Ladung → Zwangsnachladung
        P_inBatt_Grid = P_inBatt_total
        P_inBatt_PV = 0.0
    else:
        # Netzbezug kleiner/gleich → Batterie lädt aus PV
        P_inBatt_PV = P_inBatt_total
        P_inBatt_Grid = 0.0
    
    # Gesamt-Batterie-Ladung (für Kompatibilität)
    P_inBatt = P_inBatt_total
    
    # === PV-PRODUKTION KORREKT (OHNE BATTERY-EINFLUSS!) ===
    # KRITISCH: P_AC_Inv enthält bei Entladung Battery-Leistung → NICHT verwenden!
    # Echte PV-Produktion = Reine MPPT-Leistung von allen Invertoren
    P_F1_PV = P_DC1_avg + P_DC2_avg  # F1 PV-Leistung (ohne Battery!)
    P_PV_total = P_F1_PV + P_F2_avg + P_F3_avg
    
    # Direktverbrauch PV = Produktion - Einspeisung - Batterieladung
    # (Batterieentladung gehört zum Verbrauchs-Chart, nicht hier!)
    P_Direct = P_PV_total - P_Exp - P_inBatt_PV
    P_Direct = max(0.0, P_Direct)  # Nicht negativ
    
    # === BERECHNETE ENERGIEWERTE ===
    
    # W_Ertrag = Gesamte PV-Erzeugung
    # W_Exp_F2/F3 sind NEGATIV → abs() verwenden
    W_Ertrag = W_DC1_delta + W_DC2_delta + abs(W_Exp_F2_delta) + abs(W_Exp_F3_delta)
    
    # W_Einspeis = Was ins Netz eingespeist wurde
    # W_Exp_Netz ist NEGATIV → abs() verwenden
    W_Einspeis = abs(W_Exp_Netz_delta)
    
    # W_Bezug = Was vom Netz bezogen wurde (bleibt positiv)
    W_Bezug = W_Imp_Netz_delta
    
    # W_inBatt / W_outBatt aus AC-Inv Differenz
    # Formel von User: W_AC_Inv - W_DC1 - W_DC2
    # Negativ = Ladung, Positiv = Entladung
    batt_diff = W_AC_Inv_delta - W_DC1_delta - W_DC2_delta
    
    if batt_diff < 0:
        W_inBatt_total = abs(batt_diff)
        W_outBatt = 0.0
    else:
        W_inBatt_total = 0.0
        W_outBatt = batt_diff
    
    # === BATTERIE-ENERGIE QUELLEN TRENNEN ===
    # Analog zur Leistung: Wenn Bezug > Batterie-Ladung → Netz-Quelle
    if W_Bezug > W_inBatt_total:
        W_inBatt_Grid = W_inBatt_total
        W_inBatt_PV = 0.0
    else:
        W_inBatt_PV = W_inBatt_total
        W_inBatt_Grid = 0.0
    
    # Gesamt (für Kompatibilität)
    W_inBatt = W_inBatt_total
    
    # W_Direct KORRIGIERT = Direkt verbrauchte PV-Energie
    # W_Direct = Ertrag - Einspeisung - Batterie-Ladung-aus-PV
    W_Direct = W_Ertrag - W_Einspeis - W_inBatt_PV
    
    # W_Verbrauch = Gesamtverbrauch
    # Formel: W_Ertrag - W_Einspeis + W_Bezug
    W_Verbrauch = W_Ertrag - W_Einspeis + W_Bezug
    
    # === SPEICHERE IN DATENBANK ===
    
    cur.execute("""
        INSERT INTO data_1min (
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
            W_AC_Inv_delta, W_DC1_delta, W_DC2_delta,
            W_Exp_Netz_delta, W_Imp_Netz_delta,
            W_Exp_F2_delta, W_Imp_F2_delta,
            W_Exp_F3_delta, W_Imp_F3_delta,
            W_Imp_WP_delta,
            W_AC_Inv_start, W_AC_Inv_end,
            W_DC1_start, W_DC1_end,
            W_DC2_start, W_DC2_end,
            W_Exp_Netz_start, W_Exp_Netz_end,
            W_Imp_Netz_start, W_Imp_Netz_end,
            P_Exp, P_Imp,
            I_inBatt_avg, I_outBatt_avg,
            P_inBatt, P_outBatt, P_Direct,
            P_inBatt_PV, P_inBatt_Grid,
            W_Ertrag, W_Einspeis, W_Bezug,
            W_inBatt, W_outBatt, W_Direct, W_Verbrauch,
            W_inBatt_PV, W_inBatt_Grid
        ) VALUES (
            ?,
            ?, ?,  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
    """, (
        bucket_ts,
        row[0], row[1], row[2],      # P_AC_Inv
        row[3], row[4], row[5],      # I_L1_Inv
        row[6], row[7], row[8],      # I_L2_Inv
        row[9], row[10], row[11],    # I_L3_Inv
        row[12], row[13], row[14],   # U_L1_N_Inv
        row[15], row[16], row[17],   # U_L2_N_Inv
        row[18], row[19], row[20],   # U_L3_N_Inv
        row[21], row[22], row[23],   # P_DC_Inv
        row[24], row[25], row[26],   # P_DC1
        row[27], row[28], row[29],   # P_DC2
        SOC_Batt_avg, row[31], row[32],  # SOC_Batt (KORRIGIERT: 30-32)
        U_Batt_avg, row[34], row[35],    # U_Batt (KORRIGIERT: 33-35)
        I_Batt_avg, row[37], row[38],    # I_Batt (KORRIGIERT: 36-38)
        P_Netz_avg, row[40], row[41],    # P_Netz (KORRIGIERT: 39-41)
        row[42], row[43], row[44],   # f_Netz (KORRIGIERT: 42-44, war 45-47=U_L1!)
        row[45], row[46], row[47],   # U_L1_N_Netz (45-47)
        row[48], row[49], row[50],   # U_L2_N_Netz
        row[51], row[52], row[53],   # U_L3_N_Netz
        P_F2_avg, row[55], row[56],  # P_F2 (KORRIGIERT: 54-56)
        P_F3_avg, row[58], row[59],  # P_F3 (KORRIGIERT: 57-59)
        P_WP_avg, row[61], row[62],  # P_WP (KORRIGIERT: 60-62)
        W_AC_Inv_delta, W_DC1_delta, W_DC2_delta,
        W_Exp_Netz_delta, W_Imp_Netz_delta,
        W_Exp_F2_delta, W_Imp_F2_delta,
        W_Exp_F3_delta, W_Imp_F3_delta,
        W_Imp_WP_delta,
        W_AC_Inv_start, W_AC_Inv_end,
        W_DC1_start, W_DC1_end,
        W_DC2_start, W_DC2_end,
        W_Exp_Netz_start, W_Exp_Netz_end,
        W_Imp_Netz_start, W_Imp_Netz_end,
        P_Exp, P_Imp,
        I_inBatt_avg, I_outBatt_avg,
        P_inBatt, P_outBatt, P_Direct,
        P_inBatt_PV, P_inBatt_Grid,
        W_Ertrag, W_Einspeis, W_Bezug,
        W_inBatt, W_outBatt, W_Direct, W_Verbrauch,
        W_inBatt_PV, W_inBatt_Grid
    ))
    
    conn.commit()
    
    print(f"[OK] {bucket_ts}: W_Ertrag={W_Ertrag:.1f}Wh W_Verbrauch={W_Verbrauch:.1f}Wh P_Direct={P_Direct:.1f}W P_inBatt_PV={P_inBatt_PV:.1f}W SOC={SOC_Batt_avg:.1f}%")

if __name__ == "__main__":
    aggregate_1min()
