#!/usr/bin/env python3
"""
Statistik-Aggregation: daily_data → monthly_statistics → yearly_statistics
Läuft alle 15min via Cron (nach aggregate_daily.py)

Aktualisiert laufenden Monat und laufendes Jahr bei jedem Lauf.
Historische Daten (CSV-Import 2022-2025) werden NICHT überschrieben,
da daily_data erst ab Jan 2026 existiert.

Mapping:
  daily_data (Wh)   →  monthly_statistics (kWh)
  W_PV_total        →  solar_erzeugung_kwh
  W_Imp_Netz_total  →  netz_bezug_kwh
  W_Exp_Netz_total  →  netz_einspeisung_kwh
  W_Batt_Charge     →  batt_ladung_kwh
  W_Batt_Discharge  →  batt_entladung_kwh
  W_PV_Direct       →  direktverbrauch_kwh
  W_Consumption     →  gesamt_verbrauch_kwh
  W_WP_total        →  waermepumpe_kwh  (WP-SmartMeter = Wärmepumpe)
  heizpatrone_*     →  heizpatrone_kwh  (Fritz!DECT Heizpatrone)
  wattpilot_daily   →  wattpilot_kwh    (Wallbox, aus wattpilot_daily Tabelle)
"""

import sys
import sqlite3
from datetime import datetime, timezone
import logging
from host_role import is_failover

if is_failover():
    sys.exit(0)
import config
from db_utils import get_db_connection
from statistics_corrections import load_monthly_stat_corrections, apply_monthly_stat_correction

DB_PATH = config.DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Strompreise: Zentrale Tarif-Tabelle aus config.py (PRIMAT)
get_strompreis = config.get_strompreis
EINSPEISEVERGUETUNG = config.EINSPEISEVERGUETUNG

# Monate VOR diesem Datum sind manuell aus Solarweb korrigiert und werden NICHT überschrieben.
# Erst ab diesem Monat aggregiert das Script automatisch aus daily_data.
# Jan+Feb 2026: daily_data enthält Solarweb-Werte (import_solarweb_daily.py, 2026-02-19)
FIRST_AUTO_MONTH = (2026, 1)  # (Jahr, Monat) - ab Januar 2026 (daily_data = Solarweb-Import)


def _get_heizpatrone_monthly_kwh(cursor, year, month, ts_start, ts_end):
    """Hole Heizpatronenverbrauch aus Fritz!DECT-Referenztabellen.

    Priorität:
      1. Monatliche Referenz aus heizpatrone_monthly (manuell importierte Monatssummen)
      2. Summe aus heizpatrone_daily (manuell + counter_auto, täglich von aggregate_daily befüllt)
      3. 0.0 falls keine Daten vorhanden
    """
    try:
        cursor.execute("""
            SELECT energy_kwh
            FROM heizpatrone_monthly
            WHERE year = ? AND month = ?
        """, (year, month))
        row = cursor.fetchone()
        if row and row[0] is not None:
            return float(row[0]), 'monthly'
    except sqlite3.OperationalError:
        return 0.0, 'none'

    try:
        cursor.execute("""
            SELECT COALESCE(SUM(energy_wh), 0.0)
            FROM heizpatrone_daily
            WHERE ts >= ? AND ts < ?
        """, (ts_start, ts_end))
        row = cursor.fetchone()
        total_wh = float(row[0]) if row and row[0] else 0.0
        if total_wh > 0:
            return total_wh / 1000.0, 'daily'
    except sqlite3.OperationalError:
        pass

    return 0.0, 'none'


def update_monthly_statistics():
    """Berechne monthly_statistics aus daily_data für aktuelle und letzte 2 Monate"""
    conn = get_db_connection()
    cursor = conn.cursor()
    corrections = load_monthly_stat_corrections()
    try:
        now = datetime.now()

        # Re-aggregate: aktueller Monat + 2 Vormonate (falls Tageswerte korrigiert)
        months_to_update = []
        for offset in range(3):
            m = now.month - offset
            y = now.year
            if m < 1:
                m += 12
                y -= 1
            months_to_update.append((y, m))

        count = 0
        for year, month in months_to_update:
            # Solarweb-korrigierte Monate nicht überschreiben
            if (year, month) < FIRST_AUTO_MONTH:
                continue
            month_start = datetime(year, month, 1)
            if month == 12:
                month_end = datetime(year + 1, 1, 1)
            else:
                month_end = datetime(year, month + 1, 1)

            ts_start = int(month_start.timestamp())
            ts_end = int(month_end.timestamp())

            # Aggregiere daily_data (Wh → kWh, /1000)
            cursor.execute("""
                SELECT
                    COALESCE(SUM(W_PV_total), 0) / 1000.0,
                    COALESCE(SUM(W_Imp_Netz_total), 0) / 1000.0,
                    COALESCE(SUM(W_Exp_Netz_total), 0) / 1000.0,
                    COALESCE(SUM(W_Batt_Charge_total), 0) / 1000.0,
                    COALESCE(SUM(W_Batt_Discharge_total), 0) / 1000.0,
                    COALESCE(SUM(W_PV_Direct_total), 0) / 1000.0,
                    COALESCE(SUM(W_Consumption_total), 0) / 1000.0,
                    COALESCE(SUM(W_WP_total), 0) / 1000.0,
                    COUNT(*)
                FROM daily_data
                WHERE ts >= ? AND ts < ?
            """, (ts_start, ts_end))

            row = cursor.fetchone()
            if not row or row[8] == 0:
                continue

            solar, bezug, einsp, batt_lad, batt_entl, direkt, gesamt, wp_total, tage = row
            wp_total, wp_correction = apply_monthly_stat_correction(
                year, month, 'waermepumpe_kwh', wp_total, corrections
            )
            if wp_correction:
                logging.info(
                    f"  {year}-{month:02d}: WP-Korrektur {wp_correction['mode']} "
                    f"{wp_correction['source_value']:.2f} -> {wp_total:.2f} kWh "
                    f"[{wp_correction['source']}]"
                )

            heizpatrone_kwh, hp_source = _get_heizpatrone_monthly_kwh(
                cursor, year, month, ts_start, ts_end
            )

            # Wattpilot-Verbrauch aus wattpilot_daily (Wh → kWh)
            wattpilot_kwh = 0
            try:
                cursor.execute("""
                    SELECT COALESCE(SUM(energy_wh), 0) / 1000.0
                    FROM wattpilot_daily
                    WHERE ts >= ? AND ts < ?
                """, (ts_start, ts_end))
                wattpilot_row = cursor.fetchone()
                if wattpilot_row and wattpilot_row[0]:
                    wattpilot_kwh = wattpilot_row[0]
            except Exception:
                pass  # Tabelle existiert noch nicht

            wattpilot_kwh, wattpilot_correction = apply_monthly_stat_correction(
                year, month, 'wattpilot_kwh', wattpilot_kwh, corrections
            )
            if wattpilot_correction:
                logging.info(
                    f"  {year}-{month:02d}: Wattpilot-Korrektur {wattpilot_correction['mode']} "
                    f"{wattpilot_correction['source_value']:.2f} -> {wattpilot_kwh:.2f} kWh "
                    f"[{wattpilot_correction['source']}]"
                )

            if heizpatrone_kwh > 0:
                logging.info(
                    f"  {year}-{month:02d}: Heizpatrone {heizpatrone_kwh:.2f} kWh [{hp_source}]"
                )

            # Sonnenstunden aus forecast_daily (Summe der prognostizierten Sonnenstunden)
            sonnenstunden = None
            try:
                date_start = month_start.strftime('%Y-%m-%d')
                date_end = month_end.strftime('%Y-%m-%d')
                cursor.execute("""
                    SELECT SUM(sunshine_hours)
                    FROM forecast_daily
                    WHERE date >= ? AND date < ?
                      AND sunshine_hours IS NOT NULL
                """, (date_start, date_end))
                sh_row = cursor.fetchone()
                if sh_row and sh_row[0] is not None:
                    sonnenstunden = round(sh_row[0], 1)
            except Exception:
                pass

            # Autarkie: Anteil des Verbrauchs, der NICHT aus dem Netz kommt
            # (1 - Bezug/Verbrauch) ist korrekt, weil Direktverbrauch den
            # Wattpilot-PV-Anteil nicht enthält (WTP sitzt hinter Netz-SM)
            autarkie = ((1 - bezug / gesamt) * 100) if gesamt > 0 else 0

            # Eigenverbrauchsquote: Anteil selbst verbrauchter PV am PV-Ertrag
            eigenverbrauch_pct = ((solar - einsp) / solar * 100) if solar > 0 else 0

            strompreis = get_strompreis(year, month)

            # UPSERT: Nur Monate mit daily_data überschreiben
            # Historische Monate (2022-2025) ohne daily_data bleiben unberührt
            cursor.execute("""
                INSERT INTO monthly_statistics (
                    year, month,
                    solar_erzeugung_kwh, netz_bezug_kwh, netz_einspeisung_kwh,
                    batt_ladung_kwh, batt_entladung_kwh, direktverbrauch_kwh,
                    gesamt_verbrauch_kwh, waermepumpe_kwh, heizpatrone_kwh, wattpilot_kwh,
                    autarkie_prozent, eigenverbrauch_prozent,
                    strompreis_bezug_eur_kwh, einspeiseverguetung_eur_kwh,
                    sonnenstunden
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?)
                ON CONFLICT(year, month) DO UPDATE SET
                    solar_erzeugung_kwh = excluded.solar_erzeugung_kwh,
                    netz_bezug_kwh = excluded.netz_bezug_kwh,
                    netz_einspeisung_kwh = excluded.netz_einspeisung_kwh,
                    batt_ladung_kwh = excluded.batt_ladung_kwh,
                    batt_entladung_kwh = excluded.batt_entladung_kwh,
                    direktverbrauch_kwh = excluded.direktverbrauch_kwh,
                    gesamt_verbrauch_kwh = excluded.gesamt_verbrauch_kwh,
                    waermepumpe_kwh = excluded.waermepumpe_kwh,
                    heizpatrone_kwh = excluded.heizpatrone_kwh,
                    wattpilot_kwh = excluded.wattpilot_kwh,
                    autarkie_prozent = excluded.autarkie_prozent,
                    eigenverbrauch_prozent = excluded.eigenverbrauch_prozent,
                    strompreis_bezug_eur_kwh = excluded.strompreis_bezug_eur_kwh,
                    sonnenstunden = excluded.sonnenstunden
            """, (
                year, month,
                round(solar, 2), round(bezug, 2), round(einsp, 2),
                round(batt_lad, 2), round(batt_entl, 2), round(direkt, 2),
                round(gesamt, 2), round(wp_total, 2), round(heizpatrone_kwh, 2), round(wattpilot_kwh, 2),
                round(autarkie, 2), round(eigenverbrauch_pct, 2),
                strompreis, sonnenstunden
            ))
            count += 1
            logging.info(f"  {year}-{month:02d}: {solar:.1f} kWh Solar, {bezug:.1f} kWh Bezug, {tage} Tage")

        conn.commit()
        logging.info(f"✓ {count} Monate in monthly_statistics aktualisiert")
    except Exception as e:
        conn.rollback()
        logging.error(f"Fehler bei monthly_statistics: {e}")
    finally:
        conn.close()


def update_yearly_statistics():
    """Berechne yearly_statistics aus monthly_statistics"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Alle Jahre mit Daten in monthly_statistics
        cursor.execute("""
            SELECT DISTINCT year FROM monthly_statistics
            WHERE solar_erzeugung_kwh IS NOT NULL AND solar_erzeugung_kwh > 0
            ORDER BY year
        """)
        years = [row[0] for row in cursor.fetchall()]

        count = 0
        for year in years:
            cursor.execute("""
                SELECT
                    COALESCE(SUM(waermepumpe_kwh), 0),
                    COALESCE(SUM(heizpatrone_kwh), 0),
                    COALESCE(SUM(netz_bezug_kwh), 0),
                    COALESCE(SUM(batt_entladung_kwh), 0),
                    COALESCE(SUM(direktverbrauch_kwh), 0),
                    COALESCE(SUM(gesamt_verbrauch_kwh), 0),
                    COALESCE(SUM(solar_erzeugung_kwh), 0),
                    COALESCE(SUM(batt_ladung_kwh), 0),
                    COALESCE(SUM(netz_einspeisung_kwh), 0),
                    AVG(autarkie_prozent),
                    AVG(eigenverbrauch_prozent),
                    COALESCE(SUM(wattpilot_kwh), 0),
                    COUNT(*),
                    SUM(sonnenstunden)
                FROM monthly_statistics
                WHERE year = ?
                  AND solar_erzeugung_kwh IS NOT NULL
                  AND solar_erzeugung_kwh > 0
            """, (year,))

            row = cursor.fetchone()
            if not row or row[11] == 0:
                continue

            wp_kwh, heiz, bezug, batt_entl, direkt, gesamt, solar, batt_lad, einsp, \
                _autarkie_avg, _eigen_avg, wattpilot_kwh, monate, sonnenstunden_jahr = row

            # Autarkie/Eigenverbrauch aus Jahressummen berechnen (gewichtet, nicht AVG)
            # Korrekte Formel: (1 - Bezug/Verbrauch) — Direktverbrauch enthält
            # den Wattpilot-PV-Anteil nicht (WTP sitzt hinter Netz-Smartmeter)
            autarkie = ((1 - bezug / gesamt) * 100) if gesamt > 0 else 0
            eigenverbrauch_pct = ((solar - einsp) / solar * 100) if solar > 0 else 0

            # Autark verbrauchte kWh = Verbrauch - Bezug (alles, was nicht vom Netz kam)
            autarkie_kwh = gesamt - bezug

            # Gewichteter Jahres-Strompreis (aus monatlichen Preisen)
            monats_preise = [get_strompreis(year, m) for m in range(1, 13)]
            strompreis = sum(monats_preise) / 12

            # Ersparnisse berechnen
            ersparnis_autarkie = autarkie_kwh * strompreis
            ersparnis_eigen = (solar - einsp) * strompreis
            einnahmen_einsp = einsp * EINSPEISEVERGUETUNG

            sonnenstunden_val = round(sonnenstunden_jahr, 1) if sonnenstunden_jahr else None

            cursor.execute("""
                INSERT INTO yearly_statistics (
                    year,
                    waermepumpe_kwh, heizpatrone_kwh, netz_bezug_kwh, batt_entladung_kwh,
                    direktverbrauch_kwh, gesamt_verbrauch_kwh,
                    solar_erzeugung_kwh, batt_ladung_kwh, netz_einspeisung_kwh,
                    autarkie_prozent_avg, eigenverbrauch_prozent_avg,
                    ersparnis_autarkie_eur, ersparnis_eigenverbrauch_eur,
                    einnahmen_einspeisung_eur, wattpilot_kwh, sonnenstunden
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(year) DO UPDATE SET
                    waermepumpe_kwh = excluded.waermepumpe_kwh,
                    heizpatrone_kwh = excluded.heizpatrone_kwh,
                    netz_bezug_kwh = excluded.netz_bezug_kwh,
                    batt_entladung_kwh = excluded.batt_entladung_kwh,
                    direktverbrauch_kwh = excluded.direktverbrauch_kwh,
                    gesamt_verbrauch_kwh = excluded.gesamt_verbrauch_kwh,
                    solar_erzeugung_kwh = excluded.solar_erzeugung_kwh,
                    batt_ladung_kwh = excluded.batt_ladung_kwh,
                    netz_einspeisung_kwh = excluded.netz_einspeisung_kwh,
                    autarkie_prozent_avg = excluded.autarkie_prozent_avg,
                    eigenverbrauch_prozent_avg = excluded.eigenverbrauch_prozent_avg,
                    ersparnis_autarkie_eur = excluded.ersparnis_autarkie_eur,
                    ersparnis_eigenverbrauch_eur = excluded.ersparnis_eigenverbrauch_eur,
                    einnahmen_einspeisung_eur = excluded.einnahmen_einspeisung_eur,
                    wattpilot_kwh = excluded.wattpilot_kwh,
                    sonnenstunden = excluded.sonnenstunden
            """, (
                year,
                round(wp_kwh, 2), round(heiz, 2), round(bezug, 2), round(batt_entl, 2),
                round(direkt, 2), round(gesamt, 2),
                round(solar, 2), round(batt_lad, 2), round(einsp, 2),
                round(autarkie, 2), round(eigenverbrauch_pct, 2),
                round(ersparnis_autarkie, 2), round(ersparnis_eigen, 2),
                round(einnahmen_einsp, 2), round(wattpilot_kwh, 2), sonnenstunden_val
            ))
            count += 1

        conn.commit()
        logging.info(f"✓ {count} Jahre in yearly_statistics aktualisiert")
    except Exception as e:
        conn.rollback()
        logging.error(f"Fehler bei yearly_statistics: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    logging.info("=== Statistik-Aggregation ===")
    update_monthly_statistics()
    update_yearly_statistics()
    logging.info("=== Statistik-Aggregation abgeschlossen ===")
