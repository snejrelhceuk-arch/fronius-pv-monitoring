#!/usr/bin/env python3
"""
Fritz!DECT Data Collector - Heizpatrone + Klimaanlage

Separater Prozess: Pollt Fritz!DECT-Geräte alle 10 Sekunden und speichert
Leistungs- + Energiedaten in fritzdect_readings Tabelle (tmpfs-DB).

Wird als systemd-Service gestartet:
  systemctl start pv-fritzdect

Umgebung:
  - FRITZ_USER, FRITZ_PASSWORD aus .secrets
  - config/fritz_config.json mit AIN + polling_interval_s

Format fritzdect_readings:
  ts, device_id, ain, name, power_mw, power_w, state, energy_total_wh

Siehe: doc/automation/fritzdect/FRITZDECT_PERFORMANCE.md
"""

import sys
import logging
import sqlite3
import time
from pathlib import Path

# Setup Logging (→ systemd journal)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'
)
LOG = logging.getLogger('fritzdect_collector')

# Projekt-Root hinzufügen
_project_root = Path(__file__).parent
sys.path.insert(0, str(_project_root))

import config
from automation.engine.aktoren.aktor_fritzdect import (
    _load_fritz_config, _get_session_id, _aha_device_info
)

# ════════════════════════════════════════════════════════════════

class FritzDectCollector:
    """Grundgerüst für Fritz!DECT Datensammlung."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        self.polling_interval = 10  # Sekunden (wird aus Config geladen)
        self.error_count = 0
        self.max_error_count = 10  # Nur loggen wenn <10 Fehler
        
        LOG.info(f"Fritz!DECT Collector initialisiert (DB: {self.db_path})")
        self._ensure_db()
    
    def _ensure_db(self):
        """Prüfe dass fritzdect_readings Tabelle existiert."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            cursor = conn.cursor()
            
            # Prüf ob Tabelle existiert
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='fritzdect_readings'"
            )
            if not cursor.fetchone():
                LOG.warning("fritzdect_readings Tabelle nicht gefunden — "
                            "bitte db_init.py ausführen")
            
            conn.close()
        except Exception as e:
            LOG.warning(f"DB-Prüfung: {e}")
    
    def _get_connection(self):
        """Öffne Verbindung zur tmpfs-DB."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=5.0)
            return conn
        except Exception as e:
            LOG.error(f"DB-Verbindung fehlgeschlagen: {e}")
            return None
    
    def poll_devices(self):
        """Hole alle confgierten Fritz!DECT-Geräte und speichere Daten."""
        now = int(time.time())
        
        try:
            cfg = _load_fritz_config()
            host = cfg.get('fritz_ip', '192.168.178.1')
            user = cfg.get('fritz_user', '')
            pw = cfg.get('fritz_password', '')
            self.polling_interval = cfg.get('polling_interval_s', 10)
            
            if not user or not pw:
                if self.error_count == 0:
                    LOG.warning("Fritz!DECT Credentials nicht in .secrets")
                self.error_count += 1
                return
            
            # Session-ID holen
            sid = _get_session_id(host, user, pw)
            if not sid:
                if self.error_count < self.max_error_count:
                    LOG.warning("Fritz!Box Session-ID konnte nicht geholt werden")
                self.error_count += 1
                return
            
            # Konfigurierte Geräte polling
            geraete_cfg = cfg.get('geraete', [])
            saved_count = 0
            
            for gerät in geraete_cfg:
                if not gerät.get('active', True):
                    continue
                
                dev_id = gerät.get('id', '')
                ain = gerät.get('ain', '')
                name = gerät.get('name', '')
                
                if not dev_id or not ain:
                    continue
                
                # Geräteinfo abrufen
                info = _aha_device_info(host, ain, sid)
                if not info:
                    continue
                
                # In DB speichern
                if self._save_reading(now, dev_id, ain, name, info):
                    saved_count += 1
            
            if saved_count > 0:
                self.error_count = 0  # Reset bei Erfolg
                LOG.debug(f"✓ {saved_count} Gerät(e) gespeichert")
        
        except Exception as e:
            self.error_count += 1
            if self.error_count < self.max_error_count:
                LOG.error(f"Poll-Fehler: {e}")
    
    def _save_reading(self, ts: int, dev_id: str, ain: str, name: str, 
                      info: dict) -> bool:
        """Speichere ein Geräte-Reading in fritzdect_readings."""
        try:
            power_mw = info.get('power_mw')
            power_w = (power_mw / 1000.0) if power_mw is not None else None
            state = int(info.get('state', 0)) if info.get('state') else None
            energy_wh = info.get('energy_wh')
            
            conn = self._get_connection()
            if not conn:
                return False
            
            try:
                conn.execute("""
                    INSERT INTO fritzdect_readings 
                    (ts, device_id, ain, name, power_mw, power_w, state, energy_total_wh)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (ts, dev_id, ain, name, power_mw, power_w, state, energy_wh))
                
                conn.commit()
                return True
            finally:
                conn.close()
        
        except Exception as e:
            if self.error_count < self.max_error_count:
                LOG.debug(f"Save-Fehler ({dev_id}): {e}")
            return False
    
    def cleanup_old_readings(self, retention_days: int = 7):
        """Lösche alte Readings (älter als retention_days)."""
        try:
            cutoff_ts = int(time.time()) - (retention_days * 86400)
            conn = self._get_connection()
            if not conn:
                return
            
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM fritzdect_readings WHERE ts < ?",
                    (cutoff_ts,)
                )
                deleted = cursor.rowcount
                conn.commit()
                
                if deleted > 0:
                    LOG.info(f"Gelöscht: {deleted} alte Readings (>7 Tage)")
            finally:
                conn.close()
        
        except Exception as e:
            LOG.debug(f"Cleanup-Fehler: {e}")
    
    def run(self):
        """Hauptloop: Polle alle 10 Sekunden."""
        LOG.info(f"Starte Hauptloop (interval: {self.polling_interval}s)")
        
        cleanup_counter = 0
        
        try:
            while True:
                time_start = time.time()
                
                # Poll
                self.poll_devices()
                
                # Cleanup jede Stunde (3600s / 10s = 360 Zyklen)
                cleanup_counter += 1
                if cleanup_counter >= 360:
                    self.cleanup_old_readings(retention_days=7)
                    cleanup_counter = 0
                
                # Sleep bis zum nächsten Zyklus
                elapsed = time.time() - time_start
                sleep_time = max(0.1, self.polling_interval - elapsed)
                time.sleep(sleep_time)
        
        except KeyboardInterrupt:
            LOG.info("Collector durch Benutzer beendet")
        except Exception as e:
            LOG.error(f"Unerwarteter Fehler: {e}", exc_info=True)

# ════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    collector = FritzDectCollector()
    collector.run()
