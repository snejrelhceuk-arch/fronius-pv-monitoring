#!/usr/bin/env python3
"""
Analyse der echten Poll-Zykluszeiten aus raw_data

Ermittelt:
1. Durchschnittliche Zeit zwischen Polls (sollte ~3s auf Pi5, länger auf Pi4 sein)
2. Durchschnittliche poll_dur_ms (Zeit für eine Datensammlung)
3. Echte Zykluszeit = Zeit zwischen Polls
4. Verteilung der Zeiten (min/max/median/p95)
"""

import sqlite3
import sys
import os
from datetime import datetime, timedelta

# Pfad zu config.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def analyze_poll_cycles(hours=24):
    """Analysiert Poll-Zyklen der letzten N Stunden"""
    
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    # Daten der letzten N Stunden
    cutoff = int((datetime.now() - timedelta(hours=hours)).timestamp())
    
    # Poll-Zeiten holen
    cursor.execute("""
        SELECT ts, t_poll_ms
        FROM raw_data
        WHERE ts > ?
        ORDER BY ts
    """, (cutoff,))
    
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < 2:
        print(f"❌ Zu wenig Daten (nur {len(rows)} Einträge)")
        return
    
    # Analyse
    poll_durations = [row[1] for row in rows if row[1] is not None]
    
    # Zeit zwischen Polls (echte Zykluszeit)
    cycle_times = []
    for i in range(1, len(rows)):
        dt = rows[i][0] - rows[i-1][0]
        if dt < 300:  # Max 5min (sonst war Restart/Pause)
            cycle_times.append(dt)
    
    # Statistiken berechnen
    def stats(data, name, unit="s"):
        if not data:
            print(f"❌ Keine Daten für {name}")
            return
        
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
    
    # Poll-Duration (wie lange dauert eine Datensammlung)
    if poll_durations:
        poll_dur_s = [ms / 1000.0 for ms in poll_durations]
        poll_avg, poll_med = stats(poll_dur_s, "Poll Duration (Datensammlungs-Zeit)", "s")
    else:
        poll_avg = 0
        poll_med = 0
    
    # Cycle Time (Zeit zwischen Polls)
    cycle_avg, cycle_med = stats(cycle_times, "Cycle Time (Zeit zwischen Polls)", "s")
    
    # Zusammenfassung
    print(f"\n{'='*60}")
    print(f"🎯 ZUSAMMENFASSUNG")
    print(f"{'='*60}")
    print(f"  Analysierte Zeitspanne: {hours}h")
    print(f"  Anzahl Messungen:       {len(rows):,}")
    print(f"")
    print(f"  POLL_INTERVAL (Soll):   3.000 s")
    print(f"  Poll Duration (Ist):    {poll_avg:.3f} s (Datensammlung)")
    print(f"  Cycle Time (Ist):       {cycle_avg:.3f} s (echter Abstand)")
    print(f"")
    print(f"  → Echter Zyklus = {cycle_avg:.3f}s")
    print(f"  → Für Integrationen Faktor verwenden: {cycle_avg:.3f}/3600 = {cycle_avg/3600:.6f} h/Zyklus")
    
    # Warnung bei großen Abweichungen
    if cycle_avg > 3.5:
        print(f"\n⚠️  WARNUNG: Zykluszeit {cycle_avg:.3f}s deutlich über Soll (3s)!")
        print(f"   Mögliche Ursachen:")
        print(f"   - CPU-Throttling (Hitze)")
        print(f"   - Modbus-Timeouts")
        print(f"   - Langsamer Pi4 vs Pi5")
    
    # Überprüfung auf große Lücken
    large_gaps = [ct for ct in cycle_times if ct > 10]
    if large_gaps:
        print(f"\n⚠️  {len(large_gaps)} große Lücken (>10s) gefunden:")
        for gap in sorted(large_gaps, reverse=True)[:10]:
            print(f"     {gap:.1f}s")
    
    # Verteilung anzeigen
    print(f"\n{'='*60}")
    print(f"📈 VERTEILUNG (Cycle Time)")
    print(f"{'='*60}")
    
    buckets = {
        "< 3.0s": 0,
        "3.0-3.5s": 0,
        "3.5-4.0s": 0,
        "4.0-5.0s": 0,
        "5.0-10.0s": 0,
        "> 10.0s": 0
    }
    
    for ct in cycle_times:
        if ct < 3.0:
            buckets["< 3.0s"] += 1
        elif ct < 3.5:
            buckets["3.0-3.5s"] += 1
        elif ct < 4.0:
            buckets["3.5-4.0s"] += 1
        elif ct < 5.0:
            buckets["4.0-5.0s"] += 1
        elif ct < 10.0:
            buckets["5.0-10.0s"] += 1
        else:
            buckets["> 10.0s"] += 1
    
    total = len(cycle_times)
    for bucket, count in buckets.items():
        pct = (count / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 2)
        print(f"  {bucket:12s}: {count:6d} ({pct:5.1f}%) {bar}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Analysiere Poll-Zykluszeiten')
    parser.add_argument('--hours', type=int, default=24, help='Anzahl Stunden zu analysieren (default: 24)')
    
    args = parser.parse_args()
    
    print(f"\n🔍 Analysiere Poll-Zyklen der letzten {args.hours}h...")
    print(f"   Datenbank: {config.DB_PATH}")
    
    analyze_poll_cycles(args.hours)
