#!/usr/bin/env python3
"""
Import historischer Statistikdaten in die Datenbank
Liest CSV-Dateien im Format: data_YYYY.csv
"""

import sqlite3
import csv
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "data.db"

def init_statistics_tables():
    """Erstelle Statistik-Tabellen falls nicht vorhanden"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Lese Schema-Datei
    schema_path = Path(__file__).parent / "db_schema_statistics.sql"
    with open(schema_path) as f:
        schema_sql = f.read()
    
    # Führe Schema aus (mit Fehlerbehandlung für einzelne Statements)
    for statement in schema_sql.split(';'):
        statement = statement.strip()
        if statement:
            try:
                c.execute(statement)
            except sqlite3.OperationalError as e:
                if 'already exists' not in str(e):
                    print(f"⚠ Schema-Warnung: {e}")
    
    conn.commit()
    conn.close()
    print("OK Statistik-Tabellen initialisiert")


def import_monthly_data(year: int, csv_file: Path, strompreis=0.30, einspeisung=0.082):
    """
    Import monatlicher Daten aus CSV
    
    CSV-Format (Komma-separiert):
    month,heizpatrone_kwh,netz_bezug_kwh,batt_entladung_kwh,batt_ladung_kwh,
    direktverbrauch_kwh,solar_erzeugung_kwh,wattpilot_kwh,gesamt_verbrauch_kwh,autarkie_prozent,
    kosten_gesamt_eur,kosten_batterie_eur,batterie_amort_prozent
    
    wattpilot_kwh ist optional (0 wenn nicht vorhanden)
    """
    if not csv_file.exists():
        print(f"ERROR Datei nicht gefunden: {csv_file}")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    imported = 0
    skipped = 0
    
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            month = int(row['month'])
            
            # Lese Werte aus CSV
            solar = float(row['solar_erzeugung_kwh'])
            direkt = float(row['direktverbrauch_kwh'])
            batt_lad = float(row['batt_ladung_kwh'])
            
            # Netzeinspeisung: Aus CSV wenn vorhanden, sonst berechnen
            if 'netz_einspeisung_kwh' in row and row['netz_einspeisung_kwh']:
                netz_einsp = float(row['netz_einspeisung_kwh'])
            else:
                # Fallback-Berechnung für alte CSVs
                netz_einsp = max(0, solar - direkt - batt_lad)
            
            # Berechne Eigenverbrauchsquote: (Solar - Netzeinspeisung) / Solar * 100
            eigenverbrauch_pct = ((solar - netz_einsp) / solar * 100) if solar > 0 else 0
            
            # Wattpilot (optional, ab 2024)
            wattpilot = float(row.get('wattpilot_kwh', 0))
            
            # Kosten (optional - falls nicht vorhanden, mit 0 initialisieren)
            kosten_gesamt = float(row.get('kosten_gesamt_eur', 0))
            kosten_batterie = float(row.get('kosten_batterie_eur', 0))
            batterie_amort = float(row.get('batterie_amort_prozent', 0))
            
            try:
                c.execute("""
                    INSERT INTO monthly_statistics (
                        year, month,
                        heizpatrone_kwh, netz_bezug_kwh, batt_entladung_kwh,
                        direktverbrauch_kwh, wattpilot_kwh, gesamt_verbrauch_kwh,
                        solar_erzeugung_kwh, batt_ladung_kwh, netz_einspeisung_kwh,
                        autarkie_prozent, eigenverbrauch_prozent,
                        kosten_gesamt_eur, kosten_batterie_eur, batterie_amort_prozent,
                        strompreis_bezug_eur_kwh, einspeiseverguetung_eur_kwh
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    year, month,
                    float(row['heizpatrone_kwh']),
                    float(row['netz_bezug_kwh']),
                    float(row['batt_entladung_kwh']),
                    float(row['direktverbrauch_kwh']),
                    wattpilot,
                    float(row['gesamt_verbrauch_kwh']),
                    solar,
                    batt_lad,
                    netz_einsp,
                    float(row['autarkie_prozent']),
                    eigenverbrauch_pct,
                    kosten_gesamt,
                    kosten_batterie,
                    batterie_amort,
                    strompreis,
                    einspeisung
                ))
                imported += 1
            except sqlite3.IntegrityError:
                print(f"  SKIP {year}-{month:02d} bereits vorhanden, ueberspringe")
                skipped += 1
    
    conn.commit()
    
    # Aggregiere Jahresstatistik
    aggregate_yearly(conn, year)
    
    conn.close()
    
    print(f"OK {year}: {imported} Monate importiert, {skipped} uebersprungen")
    return True


def aggregate_yearly(conn, year: int):
    """Berechne Jahresstatistik aus monatlichen Daten"""
    c = conn.cursor()
    
    # Hole Monatsdaten für das Jahr
    c.execute("""
        SELECT 
            SUM(heizpatrone_kwh),
            SUM(netz_bezug_kwh),
            SUM(batt_entladung_kwh),
            SUM(direktverbrauch_kwh),
            SUM(wattpilot_kwh),
            SUM(gesamt_verbrauch_kwh),
            SUM(solar_erzeugung_kwh),
            SUM(batt_ladung_kwh),
            SUM(netz_einspeisung_kwh),
            AVG(autarkie_prozent),
            AVG(eigenverbrauch_prozent),
            MAX(kosten_gesamt_eur),
            MAX(kosten_batterie_eur),
            MAX(batterie_amort_prozent),
            AVG(strompreis_bezug_eur_kwh),
            AVG(einspeiseverguetung_eur_kwh)
        FROM monthly_statistics
        WHERE year = ?
    """, (year,))
    
    row = c.fetchone()
    if not row or row[0] is None:
        return
    
    # Index mapping: 0=heizpatrone, 1=netz_bezug, 2=batt_entladung, 3=direktverbrauch,
    # 4=wattpilot, 5=gesamt, 6=solar, 7=batt_ladung, 8=netz_einspeisung,
    # 9=autarkie_avg, 10=eigenverbrauch_avg, 11=kosten, 12=kosten_batt, 13=amort,
    # 14=strompreis, 15=einspeise_verg
    
    netz_bezug = row[1] or 0
    strompreis = row[14] or 0.30
    
    solar_total = row[6] or 0
    
    # NULLEINSPEISER: Keine Einspeisevergütung
    # Ersparnis = Gesamte Solar-Erzeugung × Strompreis
    ersparnis_solar = solar_total * strompreis
    
    # Insert or Replace
    c.execute("""
        INSERT OR REPLACE INTO yearly_statistics (
            year,
            heizpatrone_kwh, netz_bezug_kwh, batt_entladung_kwh,
            direktverbrauch_kwh, wattpilot_kwh, gesamt_verbrauch_kwh,
            solar_erzeugung_kwh, batt_ladung_kwh, netz_einspeisung_kwh,
            autarkie_prozent_avg, eigenverbrauch_prozent_avg,
            kosten_gesamt_eur, kosten_batterie_eur, batterie_amort_prozent,
            ersparnis_autarkie_eur, ersparnis_eigenverbrauch_eur, einnahmen_einspeisung_eur
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        year,
        row[0], row[1], row[2], row[3], row[4], row[5],
        row[6], row[7], row[8],
        row[9], row[10],
        row[11], row[12], row[13],
        ersparnis_solar, ersparnis_solar, 0
    ))
    
    conn.commit()
    print(f"  OK Jahresstatistik {year} aktualisiert")


def show_statistics():
    """Zeige importierte Statistiken"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print("\n=== IMPORTIERTE STATISTIKEN ===")
    print("=" * 80)
    
    # Jahresübersicht
    c.execute("""
        SELECT 
            year,
            solar_erzeugung_kwh,
            gesamt_verbrauch_kwh,
            autarkie_prozent_avg,
            kosten_gesamt_eur,
            ersparnis_autarkie_eur
        FROM yearly_statistics
        ORDER BY year
    """)
    
    print("\nJahresuebersicht:")
    print(f"{'Jahr':<6} {'Solar [kWh]':>12} {'Verbrauch [kWh]':>16} {'Autarkie':>10} {'Kosten [EUR]':>12} {'Ersparnis [EUR]':>16}")
    print("-" * 80)
    
    for row in c.fetchall():
        year, solar, verbrauch, autarkie, kosten, ersparnis = row
        if solar is not None:  # Nur vollständige Jahre anzeigen
            print(f"{year:<6} {solar:>12,.0f} {verbrauch:>16,.0f} {autarkie:>9.1f}% {kosten:>11,.2f} {ersparnis:>15,.2f}")
    
    # Monatsdetails letztes Jahr
    c.execute("SELECT MAX(year) FROM monthly_statistics")
    last_year = c.fetchone()[0]
    
    if last_year:
        print(f"\n\nMonatsdetails {last_year}:")
        c.execute("""
            SELECT 
                month,
                solar_erzeugung_kwh,
                autarkie_prozent,
                kosten_gesamt_eur
            FROM monthly_statistics
            WHERE year = ?
            ORDER BY month
        """, (last_year,))
        
        print(f"{'Monat':<6} {'Solar [kWh]':>12} {'Autarkie':>10} {'Kosten kum. [EUR]':>18}")
        print("-" * 50)
        
        for row in c.fetchall():
            month, solar, autarkie, kosten = row
            print(f"{month:>2}/{last_year:<4} {solar:>12,.0f} {autarkie:>9.1f}% {kosten:>15,.2f}")
    
    conn.close()


if __name__ == "__main__":
    print("=== STATISTIK-IMPORT ===")
    print("=" * 80)
    
    # Initialisiere Tabellen
    init_statistics_tables()
    
    # Import 2022
    csv_2022 = Path(__file__).parent / "data_2022.csv"
    if csv_2022.exists():
        import_monthly_data(2022, csv_2022, strompreis=0.30, einspeisung=0.082)
    
    # Import 2023
    csv_2023 = Path(__file__).parent / "data_2023.csv"
    if csv_2023.exists():
        import_monthly_data(2023, csv_2023, strompreis=0.30, einspeisung=0.082)
    
    # Import 2024
    csv_2024 = Path(__file__).parent / "data_2024.csv"
    if csv_2024.exists():
        import_monthly_data(2024, csv_2024, strompreis=0.30, einspeisung=0.082)
    
    # Import 2025
    csv_2025 = Path(__file__).parent / "data_2025.csv"
    if csv_2025.exists():
        import_monthly_data(2025, csv_2025, strompreis=0.30, einspeisung=0.082)
    
    # Zeige Ergebnis
    show_statistics()
    
    print("\nOK Import abgeschlossen")
    print("\nNaechste Schritte:")
    print("  1. Weitere Jahre hinzufuegen: data_2023.csv, data_2024.csv, ...")
    print("  2. API-Endpunkte nutzen: /api/statistics/monthly, /api/statistics/yearly")
    print("  3. Web-Ansicht: http://192.168.2.195:8000/statistics")
