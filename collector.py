#!/usr/bin/env python3
"""
Fronius Modbus Data Collector - NUR Datensammlung
Separater Prozess: Sammelt Daten, flask_api.py serviert Visualisierung
"""

# Public Entry-Points aus dem collector-Package (Refactor 2026-05-16,
# vormals monolithisch in modbus_v3.py).
from collector import poller_loop, flush_buffer_to_db

if __name__ == '__main__':
    print("=== Fronius Modbus Data Collector ===")
    print("Nur Datensammlung (kein Webserver)")
    print("Visualisierung: http://localhost:8000")
    print("")
    
    try:
        # Starte nur Datensammlung
        poller_loop()
    except KeyboardInterrupt:
        print("\n[INFO] Schreibe verbleibende Daten...")
        flush_buffer_to_db()
        print("[INFO] Collector beendet")
