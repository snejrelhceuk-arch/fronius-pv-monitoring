#!/usr/bin/env python3
"""
Analyse der echten Wattpilot Poll-Zykluszeiten aus wattpilot_readings

Ermittelt:
1. Durchschnittliche Zeit zwischen Polls (sollte ~10s sein)
2. Echte Zykluszeit für charging_hours Korrektur
3. Verteilung der Zeiten (min/max/median/p95)
"""

import sqlite3
import sys
import os
from datetime import datetime, timedelta

# Pfad zu config.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def analyze_wattpilot_cycles(hours=24):
    """Analysiert Wattpilot Poll-Zyklen der letzten N Stunden"""
    
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    # Daten der letzten N Stunden
    cutoff = int((datetime.now() - timedelta(hours=hours)).timestamp())
    
    # Poll-Zeiten holen
    cursor.execute("""
        SELECT ts, car_state
        FROM wattpilot_readings
        WHERE ts > ?
        ORDER BY ts
    """, (cutoff,))
    
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < 2:
        print(f"❌ Zu wenig Daten (nur {len(rows)} Einträge)")
        return
    
    # Zeit zwischen Polls (echte Zykluszeit)
    cycle_times = []
    charging_cycle_times = []
    
    for i in range(1, len(rows)):
        dt = rows[i][0] - rows[i-1][0]
        if dt < 300:  # Max 5min (sonst war Restart/Pause)
            cycle_times.append(dt)
            
            # Zyklen während Ladung (car_state = 2)
            if rows[i-1][1] == 2:
                charging_cycle_times.append(dt)
    
    # Statistiken berechnen
    def stats(data, name, unit="s"):
        if not data:
            print(f"❌ Keine Daten für {name}")
            return None, None
        
        data_sorted = sorted(data)
        n = len(data_sorted)
        
        avg = sum(data) / len(data)
        median = data_sorted[n // 2]
        p95 = data_sorted[int(n * 0.95)]
        p99 = data_sorted[int(n * 0.99)]
        min_val = min(data)
        max_val = max(data)
        
        print(f"\n{'='*60}")
        print(f"📊 {name}")
        print(f"{'='*60}")
        print(f"  Anzahl:     {n:,}")
        print(f"  Mittelwert: {avg:.3f} {unit}")
        print(f"  Median:     {median:.3f} {unit}")
        print(f"  Min:        {min_val:.3f} {unit}")
        print(f"  Max:        {max_val:.3f} {unit}")
        print(f"  P95:        {p95:.3f} {unit}")
        print(f"  P99:        {p99:.3f} {unit}")
        
        return avg, median
    
    # Alle Zyklen
    overall_avg, overall_med = stats(cycle_times, "Cycle Time (alle Messungen)", "s")
    
    # Nur Zyklen während Ladung
    if charging_cycle_times:
        charging_avg, charging_med = stats(charging_cycle_times, 
                                          "Cycle Time (während Ladung)", "s")
    else:
        print("\n⚠️  Keine Ladezustände in diesem Zeitraum")
        charging_avg = overall_avg
        charging_med = overall_med
    
    # Zusammenfassung
    print(f"\n{'='*60}")
    print("🎯 ZUSAMMENFASSUNG")
    print(f"{'='*60}")
    print(f"  Analysierte Zeitspanne: {hours}h")
    print(f"  Anzahl Messungen:       {len(rows):,}")
    print("")
    print(f"  POLL_INTERVAL (Soll):   {config.WATTPILOT_POLL_INTERVAL:.3f} s")
    print(f"  Cycle Time (Ist):       {overall_avg:.3f} s")
    
    if charging_avg:
        print(f"  Cycle Time (Laden):     {charging_avg:.3f} s")
    
    print("")
    print(f"  → Echter Zyklus = {overall_avg:.3f}s")
    print(f"  → Für charging_hours Faktor: {overall_avg:.3f}/3600 = {overall_avg/3600:.6f} h/Zyklus")
    
    # Warnung bei großen Abweichungen
    soll = config.WATTPILOT_POLL_INTERVAL
    abweichung = abs(overall_avg - soll) / soll * 100
    
    if abweichung > 1:
        print(f"\n⚠️  WARNUNG: Zykluszeit {overall_avg:.3f}s weicht um {abweichung:.1f}% vom Soll ({soll}s) ab!")
        print("   → Empfehlung: wattpilot_collector.py korrigieren")
        print(f"   → ACTUAL_CYCLE_TIME = {overall_avg:.3f} in config.py ergänzen")
    else:
        print(f"\n✅ Zykluszeit liegt im Toleranzbereich ({abweichung:.1f}% Abweichung)")
    
    # Überprüfung auf große Lücken
    large_gaps = [ct for ct in cycle_times if ct > 30]
    if large_gaps:
        print(f"\n⚠️  {len(large_gaps)} große Lücken (>30s) gefunden:")
        for gap in sorted(large_gaps, reverse=True)[:10]:
            print(f"     {gap:.1f}s")
    
    # Verteilung anzeigen
    print(f"\n{'='*60}")
    print("📈 VERTEILUNG (Cycle Time)")
    print(f"{'='*60}")
    
    buckets = {
        "< 10.0s": 0,
        "10.0-10.5s": 0,
        "10.5-11.0s": 0,
        "11.0-12.0s": 0,
        "12.0-20.0s": 0,
        "> 20.0s": 0
    }
    
    for ct in cycle_times:
        if ct < 10.0:
            buckets["< 10.0s"] += 1
        elif ct < 10.5:
            buckets["10.0-10.5s"] += 1
        elif ct < 11.0:
            buckets["10.5-11.0s"] += 1
        elif ct < 12.0:
            buckets["11.0-12.0s"] += 1
        elif ct < 20.0:
            buckets["12.0-20.0s"] += 1
        else:
            buckets["> 20.0s"] += 1
    
    total = len(cycle_times)
    for bucket, count in buckets.items():
        pct = (count / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 2)
        print(f"  {bucket:14s}: {count:6d} ({pct:5.1f}%) {bar}")
    
    # Lade-Statistik
    charging_count = sum(1 for row in rows if row[1] == 2)
    charging_pct = (charging_count / len(rows) * 100) if len(rows) > 0 else 0
    
    print(f"\n{'='*60}")
    print("🔋 LADE-STATISTIK")
    print(f"{'='*60}")
    print(f"  Messungen mit car_state=2:  {charging_count:,} ({charging_pct:.1f}%)")
    print(f"  Geschätzte Ladezeit:        {charging_count * overall_avg / 3600:.1f}h")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Analysiere Wattpilot Poll-Zykluszeiten')
    parser.add_argument('--hours', type=int, default=24, help='Anzahl Stunden zu analysieren (default: 24)')
    
    args = parser.parse_args()
    
    print(f"\n🔍 Analysiere Wattpilot Poll-Zyklen der letzten {args.hours}h...")
    print(f"   Datenbank: {config.DB_PATH}")
    
    analyze_wattpilot_cycles(args.hours)
