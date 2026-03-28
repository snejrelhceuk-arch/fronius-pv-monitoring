#!/usr/bin/env python3
"""
Backfill Sonnenstunden (sunshine_hours) in monthly_statistics und yearly_statistics.

Quelle: Open-Meteo Archive API (https://archive-api.open-meteo.com/v1/archive)
  - Nutzt Koordinaten aus config.py (Erlau, Mittelsachsen)
  - Gitterauflösung: 9 km (ECMWF IFS ab 2017), ERA5 ~25 km für ältere Daten
  - sunshine_duration = Sekunden mit Direktstrahlung > 120 W/m² (WMO-Definition)

Für jeden Monat (Nov 2021 – Dez 2025) wird die tägliche sunshine_duration
abgerufen, zur Monatssumme in Stunden aggregiert und in monthly_statistics.sonnenstunden
gespeichert. Danach werden die Jahressummen in yearly_statistics aktualisiert.

Zusätzlich: Tägliche Sonnenstunden werden in forecast_daily eingefügt
(sofern noch kein Eintrag vorhanden), damit aggregate_statistics.py
bei zukünftigen Läufen konsistente Daten hat.

Usage:
    python3 scripts/backfill_sunshine_hours.py [--dry-run]
"""
import sys
import os
import time
import sqlite3
import requests
from datetime import date
from calendar import monthrange

# Projekt-Pfad
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LATITUDE, LONGITUDE, TIMEZONE, DB_PATH, DB_PERSIST_PATH

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DRY_RUN = '--dry-run' in sys.argv


def fetch_monthly_sunshine(year, month):
    """Ruft tägliche sunshine_duration von Open-Meteo ab und gibt Monatssumme in Stunden zurück."""
    days_in_month = monthrange(year, month)[1]
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{days_in_month:02d}"

    params = {
        'latitude': LATITUDE,
        'longitude': LONGITUDE,
        'start_date': start,
        'end_date': end,
        'daily': 'sunshine_duration',
        'timezone': TIMEZONE,
    }

    for attempt in range(3):
        try:
            resp = requests.get(ARCHIVE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if 'error' in data:
                print(f"  API-Fehler: {data.get('reason', 'unbekannt')}")
                return None, []

            daily = data['daily']
            daily_hours = []
            total_seconds = 0
            for i, d in enumerate(daily['time']):
                sec = daily['sunshine_duration'][i] or 0
                hours = sec / 3600.0
                daily_hours.append((d, round(hours, 2)))
                total_seconds += sec

            total_hours = round(total_seconds / 3600.0, 1)
            return total_hours, daily_hours

        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"  Versuch {attempt+1}/3 fehlgeschlagen: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

    return None, []


def backfill():
    """Hauptfunktion: Sonnenstunden für alle Monate abrufen und speichern."""
    db_path = DB_PATH if os.path.exists(DB_PATH) else DB_PERSIST_PATH
    print(f"Datenbank: {db_path}")
    print(f"Koordinaten: {LATITUDE}°N, {LONGITUDE}°E")
    print(f"Modus: {'DRY-RUN (keine Änderungen)' if DRY_RUN else 'LIVE'}")
    print()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Prüfe welche Monate existieren
    existing = conn.execute(
        "SELECT year, month, sonnenstunden FROM monthly_statistics ORDER BY year, month"
    ).fetchall()

    if not existing:
        print("FEHLER: Keine Einträge in monthly_statistics gefunden!")
        conn.close()
        return

    months_to_fill = []
    for row in existing:
        y, m = row['year'], row['month']
        current_ss = row['sonnenstunden']
        # Feb 2026 hat schon 5.5h, laufenden Monat nicht überschreiben
        today = date.today()
        if y == today.year and m == today.month:
            print(f"  {y}-{m:02d}: übersprungen (laufender Monat, aktuell {current_ss}h)")
            continue
        # Zukunft überspringen
        if date(y, m, 1) > today:
            continue
        months_to_fill.append((y, m, current_ss))

    print(f"Zu befüllende Monate: {len(months_to_fill)}")
    print("=" * 60)

    updated_months = 0
    updated_daily = 0
    yearly_sums = {}

    for y, m, current_ss in months_to_fill:
        label = f"{y}-{m:02d}"

        # Abruf von Open-Meteo
        total_hours, daily_hours = fetch_monthly_sunshine(y, m)

        if total_hours is None:
            print(f"  {label}: FEHLER beim Abruf")
            continue

        print(f"  {label}: {total_hours:6.1f}h  ({len(daily_hours)} Tage)", end="")

        if current_ss is not None and abs(current_ss - total_hours) < 0.2:
            print("  [bereits korrekt]")
        else:
            if current_ss is not None:
                print(f"  [Update: {current_ss} → {total_hours}]", end="")
            else:
                print("  [NEU]", end="")

            if not DRY_RUN:
                conn.execute(
                    "UPDATE monthly_statistics SET sonnenstunden = ? WHERE year = ? AND month = ?",
                    (total_hours, y, m)
                )
                updated_months += 1

            print()

        # Tägliche Sonnenstunden in forecast_daily einfügen
        if not DRY_RUN:
            for day_date, day_hours in daily_hours:
                # Nur einfügen wenn noch kein Eintrag (OR IGNORE)
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO forecast_daily (date, sunshine_hours)
                        VALUES (?, ?)
                    """, (day_date, day_hours))
                    if conn.total_changes:
                        updated_daily += 1
                except sqlite3.OperationalError:
                    # Tabelle hat evtl. NOT NULL constraints → update statt insert
                    conn.execute("""
                        UPDATE forecast_daily SET sunshine_hours = ?
                        WHERE date = ? AND sunshine_hours IS NULL
                    """, (day_hours, day_date))

        # Jahressumme tracken
        if y not in yearly_sums:
            yearly_sums[y] = 0.0
        yearly_sums[y] += total_hours

        # Rate-Limiting: 0.3s zwischen Requests
        time.sleep(0.3)

    # Commit monthly
    if not DRY_RUN:
        conn.commit()

    # Yearly aggregieren
    print()
    print("=" * 60)
    print("Jahressummen aktualisieren:")

    for year in sorted(yearly_sums.keys()):
        # Prüfe ob alle Monate des Jahres befüllt sind
        row = conn.execute(
            "SELECT SUM(sonnenstunden) as total, COUNT(*) as cnt "
            "FROM monthly_statistics WHERE year = ? AND sonnenstunden IS NOT NULL",
            (year,)
        ).fetchone()

        total = row['total'] if row['total'] else 0
        cnt = row['cnt'] if row['cnt'] else 0

        # Für 2021: nur Nov+Dez
        expected = 12
        if year == 2021:
            expected = 2  # Nov + Dez

        print(f"  {year}: {total:.1f}h ({cnt} Monate befüllt)", end="")

        if not DRY_RUN:
            conn.execute(
                "UPDATE yearly_statistics SET sonnenstunden = ? WHERE year = ?",
                (round(total, 1), year)
            )
            print("  [gespeichert]")
        else:
            print("  [dry-run]")

    if not DRY_RUN:
        conn.commit()

    conn.close()

    print()
    print(f"Fertig! {updated_months} Monate aktualisiert.")

    # Auch persistente DB aktualisieren falls RAM-DB genutzt
    if db_path == DB_PATH and os.path.exists(DB_PERSIST_PATH):
        print(f"Kopiere Änderungen auch in persistente DB: {DB_PERSIST_PATH}")
        if not DRY_RUN:
            # Statt Kopie: gleiche Updates auf persistente DB anwenden
            backfill_persist(DB_PERSIST_PATH, db_path)


def backfill_persist(persist_path, ram_path):
    """Kopiert sonnenstunden von RAM-DB in persistente DB."""
    ram = sqlite3.connect(ram_path)
    ram.row_factory = sqlite3.Row
    persist = sqlite3.connect(persist_path)

    # Monthly
    rows = ram.execute(
        "SELECT year, month, sonnenstunden FROM monthly_statistics WHERE sonnenstunden IS NOT NULL"
    ).fetchall()
    for r in rows:
        persist.execute(
            "UPDATE monthly_statistics SET sonnenstunden = ? WHERE year = ? AND month = ?",
            (r['sonnenstunden'], r['year'], r['month'])
        )

    # Yearly
    rows = ram.execute(
        "SELECT year, sonnenstunden FROM yearly_statistics WHERE sonnenstunden IS NOT NULL"
    ).fetchall()
    for r in rows:
        persist.execute(
            "UPDATE yearly_statistics SET sonnenstunden = ? WHERE year = ?",
            (r['sonnenstunden'], r['year'])
        )

    persist.commit()
    persist.close()
    ram.close()
    print("  Persistente DB aktualisiert.")


if __name__ == '__main__':
    backfill()
