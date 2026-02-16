#!/usr/bin/env python3
"""
Fronius Modbus Data Collector - NUR Datensammlung
Separater Prozess: Sammelt Daten, flask_api.py serviert Visualisierung
"""

# Importiere alle Funktionen aus modbus_v3.py
from modbus_v3 import poller_loop, flush_buffer_to_db

if __name__ == '__main__':
    print("=== Fronius Modbus Data Collector ===")
    print("Nur Datensammlung (kein Webserver)")
    print("Visualisierung: http://192.0.2.195:8000")
    print("")
    
    try:
        # Starte nur Datensammlung
        poller_loop()
    except KeyboardInterrupt:
        print("\n[INFO] Schreibe verbleibende Daten...")
        flush_buffer_to_db()
        print("[INFO] Collector beendet")
