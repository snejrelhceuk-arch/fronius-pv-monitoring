#!/usr/bin/env python3
"""
wattpilot_collector.py — Periodische Wattpilot-Zählerstanderfassung
====================================================================
Liest alle 30 Sekunden den Zählerstand (eto) und Live-Daten vom Wattpilot
und speichert sie in die Datenbank (wattpilot_readings).
Bei Fehler (z.B. WebSocket-Konflikt durch mobile App) wird nach 5s erneut versucht.

Tägliche Aggregate (wattpilot_daily) werden automatisch berechnet.

HINWEIS: Der Wattpilot erlaubt nur EINE gleichzeitige WebSocket-Verbindung.
         Externe Zugriffe (Fronius App, go-e App) verdrängen diese Verbindung.
         Der Collector erkennt dies und wartet automatisch.

Ausführung:
  - Als Daemon: python3 wattpilot_collector.py
  - Einmaliger Lauf: python3 wattpilot_collector.py --once

Autor: PV-Anlage Monitoring
Datum: 2026-02-12
"""

import sqlite3
import time
import logging
import sys
import os
import atexit
from pathlib import Path

import config
from wattpilot_api import WattpilotClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_PATH = config.DB_PATH
POLL_INTERVAL = config.WATTPILOT_POLL_INTERVAL
RETRY_INTERVAL = getattr(config, 'WATTPILOT_RETRY_INTERVAL', 5)
MAX_RETRIES = getattr(config, 'WATTPILOT_MAX_RETRIES', 2)
PID_FILE = Path(__file__).parent / 'wattpilot_collector.pid'


# ─── Single Instance Protection ───
def _is_wattpilot_process(pid):
    """Prüft ob der Prozess mit dieser PID tatsächlich ein Wattpilot-Collector ist"""
    try:
        with open(f'/proc/{pid}/cmdline', 'r') as f:
            cmdline = f.read()
        return 'wattpilot_collector' in cmdline
    except (FileNotFoundError, PermissionError):
        return False

def create_pid_file():
    """Erstellt PID-File und prüft auf laufende Instanz."""
    if PID_FILE.exists():
        try:
            with open(PID_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            
            # Prüfe ob Prozess existiert UND ein Wattpilot-Collector ist
            try:
                os.kill(old_pid, 0)
                if _is_wattpilot_process(old_pid):
                    logger.error(f"Wattpilot-Collector läuft bereits (PID {old_pid})")
                    logger.error(f"   Stoppen Sie den Prozess mit: kill {old_pid}")
                    logger.error(f"   Oder erzwingen: rm {PID_FILE}")
                    sys.exit(1)
                else:
                    logger.warning(f"PID {old_pid} lebt, ist aber kein Wattpilot-Collector — entferne stale PID-File")
                    PID_FILE.unlink()
            except OSError:
                logger.warning(f"Entferne verwaistes PID-File (PID {old_pid})")
                PID_FILE.unlink()
        except (ValueError, FileNotFoundError):
            PID_FILE.unlink()
    
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    atexit.register(remove_pid_file)
    logger.info(f"PID-File erstellt: {PID_FILE} (PID {os.getpid()})")


def remove_pid_file():
    """Entfernt PID-File beim sauberen Beenden."""
    if PID_FILE.exists():
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                PID_FILE.unlink()
                logger.info("PID-File entfernt")
        except Exception:
            pass


def init_db():
    """Erstelle Wattpilot-Tabellen falls nicht vorhanden."""
    conn = sqlite3.connect(DB_PATH)
    schema_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'doc', 'schema', 'db_schema_wattpilot.sql')
    if os.path.exists(schema_file):
        with open(schema_file, 'r') as f:
            conn.executescript(f.read())
        logger.info("Wattpilot DB-Schema initialisiert")
    conn.close()


def collect_reading():
    """
    Liest den aktuellen Wattpilot-Status und speichert ihn in die DB.
    
    Bei WebSocket-Konflikt (z.B. mobile App aktiv) wird nach RETRY_INTERVAL
    Sekunden erneut versucht (max MAX_RETRIES Versuche).
    
    Returns:
        dict: Zusammenfassung oder None bei Fehler
    """
    client = WattpilotClient()
    
    summary = None
    last_error = None
    
    for attempt in range(1, MAX_RETRIES + 2):  # 1 Versuch + MAX_RETRIES Wiederholungen
        try:
            summary = client.get_status_summary()
            if summary.get('online'):
                last_error = None
                break
            last_error = summary.get('error_message', 'offline')
        except ConnectionRefusedError as e:
            # WebSocket-Konflikt: andere App (go-e, Fronius) belegt Verbindung
            last_error = f"WebSocket belegt (externe App aktiv?): {e}"
        except (ConnectionResetError, BrokenPipeError) as e:
            # Verbindung während Zugriff unterbrochen (App-Wechsel)
            last_error = f"Verbindung unterbrochen: {e}"
        except Exception as e:
            last_error = str(e)
        
        if attempt <= MAX_RETRIES:
            logger.info(f"Wattpilot Versuch {attempt}/{MAX_RETRIES+1} fehlgeschlagen: {last_error} "
                        f"→ Retry in {RETRY_INTERVAL}s")
            time.sleep(RETRY_INTERVAL)
            client = WattpilotClient()  # Frische Verbindung
    
    if last_error:
        logger.warning(f"Wattpilot nicht erreichbar nach {MAX_RETRIES+1} Versuchen: {last_error}")
        return None
    
    if not summary or not summary.get('online'):
        logger.warning(f"Wattpilot offline: {summary.get('error_message', '?') if summary else '?'}")
        return None
    
    ts = time.time()
    energy_total_wh = summary.get('energy_total_wh', 0) or 0
    power_w = summary.get('power_w', 0) or 0
    car_state = summary.get('car_state', 0) or 0
    session_wh = summary.get('energy_session_wh', 0) or 0
    temperature_c = summary.get('temperature_c', 0) or 0
    phase_mode = summary.get('phase_mode_raw', 0) or 0
    
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        conn.execute("""
            INSERT OR REPLACE INTO wattpilot_readings 
                (ts, energy_total_wh, power_w, car_state, session_wh, temperature_c, phase_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ts, energy_total_wh, power_w, car_state, session_wh, temperature_c, phase_mode))
        conn.commit()
        
        kwh = energy_total_wh / 1000.0
        logger.info(f"Wattpilot: {kwh:.3f} kWh (Zähler), {power_w:.0f} W, "
                     f"Auto={car_state}, Temp={temperature_c}°C")
    except Exception as e:
        logger.error(f"DB-Schreibfehler: {e}")
    finally:
        conn.close()
    
    return summary


def aggregate_daily_wattpilot():
    """
    Berechnet tägliche Wattpilot-Aggregate aus wattpilot_readings.
    
    Tages-Verbrauch = eto(Tagesende) - eto(Tagesanfang)
    """
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    
    try:
        # Finde Bereich der vorhandenen Messwerte
        cursor.execute("SELECT MIN(ts), MAX(ts) FROM wattpilot_readings")
        row = cursor.fetchone()
        if not row or row[0] is None:
            logger.info("Keine Wattpilot-Messwerte vorhanden")
            return
        
        min_ts, max_ts = row
        
        # Tagesstart des ältesten Messwerts
        start_day = (int(min_ts) // 86400) * 86400
        current_day = (int(time.time()) // 86400) * 86400
        
        count = 0
        for day_ts in range(start_day, current_day + 86400, 86400):
            next_day = day_ts + 86400
            
            # Erster und letzter Zählerstand des Tages
            cursor.execute("""
                SELECT 
                    MIN(energy_total_wh),
                    MAX(energy_total_wh),
                    (SELECT energy_total_wh FROM wattpilot_readings 
                     WHERE ts >= ? AND ts < ? ORDER BY ts ASC LIMIT 1),
                    (SELECT energy_total_wh FROM wattpilot_readings 
                     WHERE ts >= ? AND ts < ? ORDER BY ts DESC LIMIT 1),
                    MAX(power_w),
                    SUM(CASE WHEN car_state = 2 THEN 1 ELSE 0 END),
                    COUNT(*)
                FROM wattpilot_readings
                WHERE ts >= ? AND ts < ?
            """, (day_ts, next_day, day_ts, next_day, day_ts, next_day))
            
            row = cursor.fetchone()
            if not row or row[6] == 0:
                continue
            
            min_eto, max_eto, start_eto, end_eto, max_power, charging_readings, total_readings = row
            
            # Tagesverbrauch = Delta des Zählerstands
            if start_eto is not None and end_eto is not None:
                energy_wh = end_eto - start_eto
            else:
                energy_wh = (max_eto or 0) - (min_eto or 0)
            
            # Negativer Wert abfangen (Zähler-Reset o.ä.)
            if energy_wh < 0:
                energy_wh = 0
            
            # Lade-Stunden aus ECHTEN Timestamps berechnen (nicht POLL_INTERVAL annehmen!)
            # WICHTIG: Echter Zyklus ist ~12.1s (nicht 10s) wegen WebSocket-Retries
            # Bei Retry-Overhead würde Annahme von 10s die Ladezeit um ~21% unterschätzen!
            if charging_readings > 0:
                # Echte Zeit zwischen erster und letzter Ladung ermitteln
                cursor.execute("""
                    SELECT MIN(ts), MAX(ts)
                    FROM wattpilot_readings
                    WHERE ts >= ? AND ts < ? AND car_state = 2
                """, (day_ts, next_day))
                
                first_charging_ts, last_charging_ts = cursor.fetchone()
                
                if first_charging_ts and last_charging_ts and first_charging_ts != last_charging_ts:
                    # Zeit zwischen erster und letzter Ladung + 1 Intervall
                    # (+ POLL_INTERVAL weil letzte Messung auch eine Zeitspanne repräsentiert)
                    charging_duration_s = (last_charging_ts - first_charging_ts) + POLL_INTERVAL
                    charging_hours = charging_duration_s / 3600.0
                else:
                    # Nur eine Messung oder alle zur gleichen Zeit → 1 Intervall
                    charging_hours = POLL_INTERVAL / 3600.0
            else:
                charging_hours = 0.0
            
            # Lade-Sessions: zähle Übergänge von nicht-laden zu laden
            cursor.execute("""
                SELECT car_state FROM wattpilot_readings
                WHERE ts >= ? AND ts < ?
                ORDER BY ts ASC
            """, (day_ts, next_day))
            states = [r[0] for r in cursor.fetchall()]
            sessions = 0
            prev_state = 0
            for s in states:
                if s == 2 and prev_state != 2:
                    sessions += 1
                prev_state = s
            
            cursor.execute("""
                INSERT OR REPLACE INTO wattpilot_daily 
                    (ts, energy_wh, energy_start_wh, energy_end_wh, 
                     max_power_w, charging_hours, sessions)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (day_ts, round(energy_wh, 1), start_eto, end_eto,
                  max_power or 0, round(charging_hours, 2), sessions))
            count += 1
        
        conn.commit()
        logger.info(f"✓ {count} Wattpilot-Tagesaggregate berechnet")
        
    except Exception as e:
        logger.error(f"Wattpilot Tagesaggregation Fehler: {e}")
    finally:
        conn.close()


def cleanup_old_readings():
    """Lösche alte Einzelmessungen gemäß Retention-Policy."""
    try:
        limit = time.time() - (config.WATTPILOT_READINGS_RETENTION_DAYS * 86400)
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM wattpilot_readings WHERE ts < ?", (limit,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            logger.info(f"Wattpilot Cleanup: {deleted} alte Messwerte gelöscht")
    except Exception as e:
        logger.error(f"Cleanup Fehler: {e}")


def run_daemon():
    """Dauerhafter Polling-Betrieb mit Netzwerk-Resilienz.
    
    Bei anhaltenden Netzwerk-Ausfällen (Wattpilot offline) wird das
    Backoff-Intervall schrittweise erhöht (10s → 30s → 60s → 120s),
    um unnötige Log-Flut zu vermeiden. Bei Wiedererreichbarkeit
    wird sofort auf normalen Betrieb zurückgeschaltet.
    """
    create_pid_file()
    logger.info(f"=== Wattpilot Collector gestartet (Intervall: {POLL_INTERVAL}s, Retry: {RETRY_INTERVAL}s) ===")
    logger.info("WICHTIG: WebSocket erlaubt nur EINE Verbindung!")
    logger.info("         Externe Apps (go-e, Fronius) können Konflikte verursachen → Auto-Retry aktiv")
    init_db()
    
    tick = 0
    consecutive_failures = 0
    MAX_BACKOFF = 120  # Maximal 2 Minuten zwischen Versuchen bei Dauerausfall
    BACKOFF_STEPS = [POLL_INTERVAL, 30, 60, MAX_BACKOFF]
    last_online_log = 0  # Zeitpunkt des letzten "wieder online"-Logs
    
    while True:
        try:
            result = collect_reading()
            
            if result is not None:
                # Erfolgreich — Normal-Betrieb
                if consecutive_failures > 0:
                    offline_duration = consecutive_failures * POLL_INTERVAL
                    logger.info(f"✓ Wattpilot wieder erreichbar nach ~{offline_duration}s "
                                f"({consecutive_failures} fehlgeschlagene Versuche)")
                consecutive_failures = 0
                
                # Tagesaggregate alle 15 Minuten neu berechnen
                if tick % 30 == 0:  # 30 × 30s = 900s = 15min
                    aggregate_daily_wattpilot()
                
                # Cleanup einmal täglich
                if tick % 2880 == 0:  # 2880 × 30s = 86400s = 24h
                    cleanup_old_readings()
                
                tick += 1
                time.sleep(POLL_INTERVAL)
            else:
                # Fehlgeschlagen — Backoff erhöhen
                consecutive_failures += 1
                
                # Backoff-Intervall bestimmen
                backoff_idx = min(consecutive_failures - 1, len(BACKOFF_STEPS) - 1)
                sleep_time = BACKOFF_STEPS[backoff_idx]
                
                # Nur periodisch loggen (nicht jeden einzelnen Fehlversuch)
                if consecutive_failures <= 3 or consecutive_failures % 10 == 0:
                    logger.warning(f"Wattpilot nicht erreichbar ({consecutive_failures}x) "
                                   f"→ nächster Versuch in {sleep_time}s")
                
                time.sleep(sleep_time)
            
        except KeyboardInterrupt:
            logger.info("Wattpilot Collector beendet")
            break
        except Exception as e:
            logger.error(f"Unerwarteter Fehler: {e}", exc_info=True)
            consecutive_failures += 1
            time.sleep(30)


def run_once():
    """Einmaliger Lauf (für Cron)."""
    init_db()
    collect_reading()
    aggregate_daily_wattpilot()


if __name__ == '__main__':
    if '--once' in sys.argv:
        run_once()
    else:
        run_daemon()
