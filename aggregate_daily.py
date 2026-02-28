#!/usr/bin/env python3
"""
Tägliche Aggregation: hourly_data → daily_data
Läuft alle 15min via Cron (für Status-Visualisierung)

Energiesummen-Strategie (seit 19.02.2026):
  Primär:   Counter End−Start aus data_1min (lückenresistent innerhalb des Tages)
  Fallback: SUM(Δ) aus hourly_data (bei Zähler-Reset oder fehlenden Countern)

Verfügbare Counter-Paare in data_1min:
  W_Imp_Netz_start/end  → Netzbezug
  W_Exp_Netz_start/end  → Einspeisung
  W_DC1_start/end        → PV F1 String 1
  W_DC2_start/end        → PV F1 String 2
  W_AC_Inv_start/end     → Inverter AC (inkl. Batterie-Durchfluss)

Nicht als Counter verfügbar (bleiben P×t):
  Batterie Laden/Entladen    → BMS-Checkpoints (separat, in Arbeit)
  Direktverbrauch             → berechnet (PV − Einsp − inBatt)
  Wärmepumpe (W_WP)          → P×t in hourly (W_Imp_WP Counter nur in raw_data ab 12.02)
  Wattpilot                   → eigener Zähler in wattpilot_daily

WP = Wärmepumpe, NICHT Wattpilot!
"""
import sys
import sqlite3
from host_role import is_failover

if is_failover():
    sys.exit(0)
import time
import logging
from datetime import datetime, timedelta
import config
from db_utils import get_db_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

DB_PATH = config.DB_PATH

# Schwellwert für Counter-Reset-Erkennung:
# Wenn Counter(End−Start) > RESET_FACTOR × SUM(Δ), liegt ein Zähler-Reset vor → Fallback auf SUM(Δ)
RESET_FACTOR = 3.0

# Mindestdelta damit ein Reset-Check greift (vermeidet Division durch ~0)
MIN_DELTA_WH = 50.0


def get_db():
    return get_db_connection()


def _local_day_boundaries(utc_midnight_ts):
    """Berechne CET/CEST-Tagesgrenzen für einen UTC-Mitternacht-Timestamp.

    day_ts (UTC midnight) → (query_start, query_end) in UTC,
    die den lokalen Kalendertag vollständig abdecken.

    Beispiel CET (Winter, UTC+1):
      day_ts = 2026-02-19 00:00 UTC → localtime = 01:00 CET
      query_start = 2026-02-18 23:00 UTC (= 00:00 CET am 19.)
      query_end   = 2026-02-19 23:00 UTC (= 00:00 CET am 20.)

    Behandelt DST-Übergänge korrekt (23h/25h Tage).
    """
    local_dt = datetime.fromtimestamp(utc_midnight_ts)
    date_str = local_dt.strftime('%Y-%m-%d')
    midnight_local = datetime.strptime(date_str, '%Y-%m-%d')
    next_midnight_local = midnight_local + timedelta(days=1)
    return int(midnight_local.timestamp()), int(next_midnight_local.timestamp())


def _counter_or_fallback(counter_val, sum_delta, label=""):
    """Wähle Counter-Wert oder SUM(Δ) mit Reset-Erkennung.

    Returns (value_wh, source_str)
    """
    if counter_val is None or sum_delta is None:
        return (sum_delta or 0.0, "sum_delta")

    # Beide Werte nahe Null → kein Unterschied, nimm Counter
    if abs(counter_val) < MIN_DELTA_WH and abs(sum_delta) < MIN_DELTA_WH:
        return (counter_val, "counter")

    # Negativer Counter → Zähler-Reset (neuer Zählerstand < alter)
    if counter_val < -MIN_DELTA_WH:
        logging.info(f"  {label}: Counter negativ ({counter_val:.0f} Wh) → Fallback SUM(Δ)={sum_delta:.0f}")
        return (sum_delta, "sum_delta/reset_neg")

    # Counter viel größer als SUM(Δ) → Zähler-Sprint (z.B. 04.02. Umstellung)
    if abs(sum_delta) > MIN_DELTA_WH and counter_val > RESET_FACTOR * abs(sum_delta):
        logging.info(f"  {label}: Counter ({counter_val:.0f}) >> SUM(Δ) ({sum_delta:.0f}) → Fallback SUM(Δ)")
        return (sum_delta, "sum_delta/reset_jump")

    return (counter_val, "counter")


def aggregate_daily():
    """Aggregiere hourly_data + data_1min Counter zu daily_data (aktuelles Schema)"""
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

        # ── Geschützte Tage: Manuell korrigierte SolarWeb-Werte nicht überschreiben ──
        # Tage mit unvollständiger Datenerfassung, deren daily_data manuell aus
        # SolarWeb-Referenzwerten gesetzt wurde. Die Aggregation würde hier
        # falsche Werte aus den lückenhaften hourly/1min-Daten berechnen.
        PROTECTED_DAYS = {
            # ── Jan 2026: Collector unvollständig (F2/F3 fehlen, Batt=0) → Solarweb-Backfill ──
            *(f'2026-01-{d:02d}' for d in range(1, 32)),
            # ── Feb 01-06: Batt=0 / SmartMeter ohne Wattpilot-Circuit → Solarweb-Backfill ──
            *(f'2026-02-{d:02d}' for d in range(1, 7)),
            # ── Feb 13: Collector-Ausfall (626/1440 1min) → Solarweb-Backfill ──
            '2026-02-13',
            # ── Feb 14: Collector-Ausfall (901/1440 1min) → Solarweb-Backfill ──
            '2026-02-14',
            # ── Feb 20: Collector-Ausfall 01:00-20:43 → Solarweb-Backfill ──
            '2026-02-20',
        }

        count = 0
        # Inkludiere aktuellen Tag (+86400): Monatsansicht zeigt heutigen Tag mit bisherigen Daten
        for day_ts in range(start_day, current_day + 86400, 86400):
            # Lokale Tagesgrenzen (CET/CEST) für Datenabfragen
            q_start, q_end = _local_day_boundaries(day_ts)

            # Geschützte Tage überspringen
            day_local = datetime.fromtimestamp(day_ts).strftime('%Y-%m-%d')
            if day_local in PROTECTED_DAYS:
                logging.info(f"  Tag {day_local} ist geschützt (SolarWeb-Korrektur) → übersprungen")
                continue

            # ── 1. Leistungsmittelwerte + P×t-Summen aus hourly_data (wie bisher) ──
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
            """, (q_start, q_end))

            row = c.fetchone()
            if not row or row[0] is None:
                continue

            # Unpack hourly_data
            (P_AC_Inv_avg, P_AC_Inv_min, P_AC_Inv_max,
             f_Netz_avg, f_Netz_min, f_Netz_max,
             P_Netz_avg, P_Netz_min, P_Netz_max,
             P_F2_avg, P_F2_min, P_F2_max,
             P_F3_avg, P_F3_min, P_F3_max,
             SOC_Batt_avg, SOC_Batt_min, SOC_Batt_max,
             sum_pv_delta, sum_exp_delta, sum_imp_delta,
             sum_batt_charge, sum_batt_discharge,
             sum_wp_total, sum_pv_direct,
             h_inv_start, h_inv_end,
             h_exp_start, h_exp_end,
             h_imp_start, h_imp_end) = row

            # ── 2. Counter End−Start aus data_1min (präziser, lückenresistent) ──
            c.execute("""
                SELECT
                    MAX(W_Imp_Netz_end) - MIN(W_Imp_Netz_start),
                    MAX(W_Exp_Netz_end) - MIN(W_Exp_Netz_start),
                    MAX(W_DC1_end)  - MIN(W_DC1_start),
                    MAX(W_DC2_end)  - MIN(W_DC2_start),
                    MAX(W_AC_Inv_end) - MIN(W_AC_Inv_start),
                    MIN(W_Imp_Netz_start), MAX(W_Imp_Netz_end),
                    MIN(W_Exp_Netz_start), MAX(W_Exp_Netz_end),
                    MIN(W_AC_Inv_start),   MAX(W_AC_Inv_end)
                FROM data_1min
                WHERE ts >= ? AND ts < ?
            """, (q_start, q_end))
            cnt_row = c.fetchone()

            if cnt_row and cnt_row[0] is not None:
                cnt_imp, cnt_exp, cnt_dc1, cnt_dc2, cnt_inv = cnt_row[:5]
                cnt_imp_start, cnt_imp_end = cnt_row[5], cnt_row[6]
                cnt_exp_start, cnt_exp_end = cnt_row[7], cnt_row[8]
                cnt_inv_start, cnt_inv_end = cnt_row[9], cnt_row[10]

                # PV F1 Counter = DC1 + DC2
                cnt_pv_f1 = (cnt_dc1 or 0) + (cnt_dc2 or 0)
            else:
                cnt_imp = cnt_exp = cnt_pv_f1 = cnt_inv = None
                cnt_imp_start, cnt_imp_end = h_imp_start, h_imp_end
                cnt_exp_start, cnt_exp_end = h_exp_start, h_exp_end
                cnt_inv_start, cnt_inv_end = h_inv_start, h_inv_end

            # ── 3. F2/F3-Counter + Wärmepumpe-Counter aus raw_data (ab 12.02.) ──
            c.execute("""
                SELECT
                    MAX(W_Exp_F2) - MIN(W_Exp_F2),
                    MAX(W_Exp_F3) - MIN(W_Exp_F3),
                    MAX(W_Imp_WP) - MIN(W_Imp_WP)
                FROM raw_data
                WHERE ts >= ? AND ts < ?
            """, (q_start, q_end))
            raw_row = c.fetchone()

            cnt_f2 = raw_row[0] if (raw_row and raw_row[0] is not None) else None
            cnt_f3 = raw_row[1] if (raw_row and raw_row[1] is not None) else None
            cnt_waermepumpe = raw_row[2] if (raw_row and raw_row[2] is not None) else None

            # ── 4. Wattpilot-Zähler aus wattpilot_daily ──
            c.execute("""
                SELECT energy_wh
                FROM wattpilot_daily
                WHERE ts = ?
            """, (day_ts,))
            wtp_row = c.fetchone()
            wattpilot_wh = wtp_row[0] if (wtp_row and wtp_row[0] is not None) else None

            # ── 4b. BMS-Checkpoint-Deltas für Batterie (ab 21.02.2026) ──
            # Checkpoints sind zu lokaler Mitternacht gespeichert (= q_start/q_end)
            bms_charge_wh = None
            bms_discharge_wh = None
            try:
                c.execute("""
                    SELECT W_Batt_Charge_BMS, W_Batt_Discharge_BMS
                    FROM energy_checkpoints
                    WHERE ts = ? AND W_Batt_Charge_BMS IS NOT NULL
                """, (q_start,))
                cp_start = c.fetchone()
                c.execute("""
                    SELECT W_Batt_Charge_BMS, W_Batt_Discharge_BMS
                    FROM energy_checkpoints
                    WHERE ts = ? AND W_Batt_Charge_BMS IS NOT NULL
                """, (q_end,))
                cp_end = c.fetchone()
                if cp_start and cp_end:
                    bms_charge_wh = cp_end[0] - cp_start[0]
                    bms_discharge_wh = cp_end[1] - cp_start[1]
                    if bms_charge_wh < 0 or bms_discharge_wh < 0:
                        logging.warning(f"  {day_local}: BMS-Counter negativ (Ch={bms_charge_wh:.0f}, Dis={bms_discharge_wh:.0f}) → ignoriert")
                        bms_charge_wh = None
                        bms_discharge_wh = None
            except Exception as e:
                logging.debug(f"BMS-Checkpoints nicht verfügbar: {e}")

            # ── 5. Counter vs SUM(Δ) mit Reset-Erkennung ──
            date_str = datetime.fromtimestamp(day_ts).strftime('%Y-%m-%d')

            W_Imp_Netz, src_imp = _counter_or_fallback(cnt_imp, sum_imp_delta, f"{date_str} Bezug")
            W_Exp_Netz, src_exp = _counter_or_fallback(cnt_exp, sum_exp_delta, f"{date_str} Einsp")

            # PV: Counter = DC1+DC2 (F1) + F2 + F3 | Fallback = SUM(W_PV_total_delta)
            if cnt_pv_f1 is not None:
                pv_f1, src_pv1 = _counter_or_fallback(cnt_pv_f1, sum_pv_delta, f"{date_str} PV-F1")
                # F2/F3: Counter aus raw_data oder Anteil aus P×t
                pv_f2 = abs(cnt_f2) if cnt_f2 is not None else 0.0
                pv_f3 = abs(cnt_f3) if cnt_f3 is not None else 0.0

                if src_pv1 == "counter":
                    # Bei Counter-Modus für F1: PV-Gesamt = F1-Counter + F2/F3-Counter
                    # Falls F2/F3-Counter fehlt → PV-Gesamtdelta aus hourly als Fallback
                    if cnt_f2 is not None and cnt_f3 is not None:
                        W_PV_total = pv_f1 + pv_f2 + pv_f3
                        src_pv = "counter(DC1+DC2+F2+F3)"
                    else:
                        # F2/F3-Counter fehlt: SUM(Δ) enthält bereits alle 3 Inverter
                        W_PV_total = sum_pv_delta or 0.0
                        src_pv = "sum_delta(kein F2/F3-Counter)"
                else:
                    W_PV_total = sum_pv_delta or 0.0
                    src_pv = src_pv1
            else:
                W_PV_total = sum_pv_delta or 0.0
                src_pv = "sum_delta"

            # Sanity-Check: Counter-basierter PV < 80% des hourly SUM?
            # Ursache: F2/F3-Counter aus raw_data mit Lücken → Undershoot
            # Fallback auf hourly SUM (enthält alle 3 Inverter aus data_1min)
            if src_pv.startswith("counter") and sum_pv_delta and sum_pv_delta > MIN_DELTA_WH:
                if W_PV_total < 0.8 * sum_pv_delta:
                    logging.info(f"  {date_str}: PV-Counter ({W_PV_total:.0f}) < 80% hourly SUM ({sum_pv_delta:.0f}) → Fallback")
                    W_PV_total = sum_pv_delta
                    src_pv = "sum_delta(counter_undershoot)"

            # Wärmepumpe (WP = Wärmepumpe!): Counter aus raw_data oder P×t
            if cnt_waermepumpe is not None:
                W_WP, src_wp = _counter_or_fallback(cnt_waermepumpe, sum_wp_total, f"{date_str} Wärmepumpe")
            else:
                W_WP = sum_wp_total or 0.0
                src_wp = "sum_delta"

            # Batterie: BMS-Counter bevorzugt, Fallback I×U aus hourly
            W_Batt_Charge = sum_batt_charge or 0.0
            W_Batt_Discharge = sum_batt_discharge or 0.0
            W_Batt_Charge_BMS = bms_charge_wh   # None oder Wh
            W_Batt_Discharge_BMS = bms_discharge_wh  # None oder Wh

            if bms_charge_wh is not None:
                logging.info(f"  {date_str}: BMS-Counter: Ch={bms_charge_wh:.0f} Wh, Dis={bms_discharge_wh:.0f} Wh"
                             f" (I×U: Ch={W_Batt_Charge:.0f}, Dis={W_Batt_Discharge:.0f})")

            # Beste verfügbare Batterie-Ladung für Restgrößen-Berechnung
            best_batt_charge = bms_charge_wh if bms_charge_wh is not None else W_Batt_Charge

            # Direktverbrauch: Für ABGELAUFENE Tage als Restgröße berechnen
            # PV_Direct = PV − Einsp − BattCh (konsistent mit Zählerlogik)
            # Für LAUFENDEN Tag: SUM(hourly) wie bisher (noch kein End-Checkpoint)
            is_current = (day_ts >= current_day)
            if is_current:
                W_PV_Direct = sum_pv_direct or 0.0
            else:
                W_PV_Direct = max(0.0, W_PV_total - W_Exp_Netz - best_batt_charge)
                if sum_pv_direct and abs(W_PV_Direct - sum_pv_direct) > 500:
                    logging.info(f"  {date_str}: PV_Direct Restgröße={W_PV_Direct:.0f} vs hourly={sum_pv_direct:.0f} Δ={(W_PV_Direct-sum_pv_direct):.0f} Wh")

            # Verbrauch = PV + Bezug − Einspeisung (immer konsistent berechnet)
            W_Consumption = W_PV_total + W_Imp_Netz - W_Exp_Netz

            # Counter-Start/End für daily_data (bevorzuge data_1min, Fallback hourly)
            # Bei erkanntem Zähler-Reset: Start/End auf None setzen,
            # damit Visualisierung nicht aus falschen Zählerständen rechnet
            inv_start = cnt_inv_start if (cnt_row and cnt_row[0] is not None) else h_inv_start
            inv_end = cnt_inv_end if (cnt_row and cnt_row[0] is not None) else h_inv_end
            exp_start = cnt_exp_start if (cnt_row and cnt_row[0] is not None) else h_exp_start
            exp_end = cnt_exp_end if (cnt_row and cnt_row[0] is not None) else h_exp_end
            imp_start = cnt_imp_start if (cnt_row and cnt_row[0] is not None) else h_imp_start
            imp_end = cnt_imp_end if (cnt_row and cnt_row[0] is not None) else h_imp_end

            # Plausibilitätsprüfung: Bei Reset Start/End nullen
            if "reset" in src_exp:
                logging.info(f"  {date_str}: Einsp-Reset erkannt → Start/End auf NULL")
                exp_start = None
                exp_end = None
            if "reset" in src_imp:
                logging.info(f"  {date_str}: Bezug-Reset erkannt → Start/End auf NULL")
                imp_start = None
                imp_end = None
            if "reset" in src_pv:
                logging.info(f"  {date_str}: PV-Reset erkannt → Start/End auf NULL")
                inv_start = None
                inv_end = None

            # Logging für Debugging
            if src_imp != "counter" or src_pv != "counter(DC1+DC2+F2+F3)":
                logging.info(f"  {date_str}: Bezug={src_imp}, PV={src_pv}, Einsp={src_exp}, WP={src_wp}")

            # ── 6. Prognose-kWh aus forecast_daily übernehmen ──
            c.execute("SELECT expected_kwh FROM forecast_daily WHERE date = ?", (date_str,))
            fc_row = c.fetchone()
            forecast_kwh = fc_row[0] if fc_row else None

            # ── 7. INSERT OR REPLACE ──
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
                    forecast_kwh,
                    W_Batt_Charge_BMS, W_Batt_Discharge_BMS
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (day_ts,
                  P_AC_Inv_avg, P_AC_Inv_min, P_AC_Inv_max,
                  f_Netz_avg, f_Netz_min, f_Netz_max,
                  P_Netz_avg, P_Netz_min, P_Netz_max,
                  P_F2_avg, P_F2_min, P_F2_max,
                  P_F3_avg, P_F3_min, P_F3_max,
                  SOC_Batt_avg, SOC_Batt_min, SOC_Batt_max,
                  W_PV_total, W_Exp_Netz, W_Imp_Netz, W_Consumption,
                  W_Batt_Charge, W_Batt_Discharge, W_WP, W_PV_Direct,
                  inv_start, inv_end,
                  exp_start, exp_end,
                  imp_start, imp_end,
                  forecast_kwh,
                  W_Batt_Charge_BMS, W_Batt_Discharge_BMS))
            count += 1

        conn.commit()
        logging.info(f"✓ {count} Tage aggregiert")

    except Exception as e:
        logging.error(f"Fehler bei täglicher Aggregation: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()

if __name__ == "__main__":
    logging.info("Starte tägliche Aggregation")
    aggregate_daily()
    logging.info("Tägliche Aggregation abgeschlossen")
