#!/usr/bin/env python3
"""
Einmaliges Korrektur-Script: Strompreise in monthly_statistics korrigieren.

Problem: import_statistics.py hat alle historischen Monate pauschal mit 
strompreis=0.30 importiert. Korrekt ist config.get_strompreis(year, month).

Betrifft insbesondere 2023: Soll 0.40, war 0.30 → Ersparnisberechnungen ~25% zu niedrig.

Nach Korrektur: yearly_statistics neu berechnen (aggregate_statistics.py).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db_utils import get_db_connection

def fix_strompreise():
    conn = get_db_connection()
    if not conn:
        print("❌ DB-Verbindung fehlgeschlagen")
        return

    cursor = conn.cursor()
    
    # Alle Monate mit ihren aktuellen Strompreisen lesen
    cursor.execute("""
        SELECT year, month, strompreis_bezug_eur_kwh
        FROM monthly_statistics
        ORDER BY year, month
    """)
    rows = cursor.fetchall()
    
    if not rows:
        print("❌ Keine Daten in monthly_statistics")
        conn.close()
        return
    
    print("=" * 70)
    print("  Strompreis-Korrektur in monthly_statistics")
    print("  Quelle: config.STROMTARIFE (tagesgenau gewichtet)")
    print("=" * 70)
    print()
    print(f"  {'Monat':<10} {'DB-Preis':>10} {'Soll-Preis':>12} {'Status'}")
    print(f"  {'-'*10} {'-'*10} {'-'*12} {'-'*20}")
    
    fixes = []
    for year, month, db_preis in rows:
        soll_preis = config.get_strompreis(year, month)
        db_preis = db_preis or 0.0
        
        # Vergleich mit 4 Nachkomma-Genauigkeit
        if abs(db_preis - soll_preis) > 0.0001:
            fixes.append((year, month, db_preis, soll_preis))
            print(f"  {year}-{month:02d}    {db_preis:>10.4f} {soll_preis:>12.6f}   ❌ KORREKTUR")
        else:
            print(f"  {year}-{month:02d}    {db_preis:>10.4f} {soll_preis:>12.6f}   ✅ OK")
    
    print()
    
    if not fixes:
        print("✅ Alle Strompreise sind korrekt. Keine Änderungen nötig.")
        conn.close()
        return
    
    print(f"⚠️  {len(fixes)} Monate mit falschem Strompreis gefunden.")
    print()
    
    # Dry-Run-Modus: Nur mit --fix werden Änderungen geschrieben
    if '--fix' not in sys.argv:
        print("🔍 DRY-RUN: Keine Änderungen. Starte mit --fix zum Korrigieren.")
        conn.close()
        return
    
    # Korrekturen durchführen
    for year, month, alt, neu in fixes:
        cursor.execute("""
            UPDATE monthly_statistics
            SET strompreis_bezug_eur_kwh = ?
            WHERE year = ? AND month = ?
        """, (neu, year, month))
        print(f"  🔧 {year}-{month:02d}: {alt:.4f} → {neu:.6f}")
    
    conn.commit()
    print(f"\n✅ {len(fixes)} Strompreise korrigiert.")
    
    # Yearly-Statistics neu berechnen
    print("\n📊 Berechne yearly_statistics neu...")
    try:
        # Import hier, damit aggregate_statistics die korrigierten Preise liest
        import aggregate_statistics
        aggregate_statistics.update_yearly_statistics()
        print("✅ yearly_statistics aktualisiert.")
    except Exception as e:
        print(f"⚠️  yearly_statistics Fehler: {e}")
        print("   Bitte manuell ausführen: python3 aggregate_statistics.py")
    
    conn.close()


if __name__ == "__main__":
    fix_strompreise()
