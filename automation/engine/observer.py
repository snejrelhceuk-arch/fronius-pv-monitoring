"""
observer.py — 3-Tier Beobachtungs-Service (Thin Shell)

Eigenständiger Prozess (systemd-Service), der alle Datenquellen nach
abgestuften Prioritäten beobachtet und den ObsState aufbaut.

Die eigentliche Logik liegt in den Collector-Modulen:
  collectors.tier1_checker      — Schwellenprüfung (Tier 1)
  collectors.battery_collector  — Modbus + HTTP (Tier 2)
  collectors.forecast_collector — Solar-Prognose (Tier 3)

HINWEIS: Im Produktivbetrieb wird statt dieses Observer-Services der
automation_daemon.py verwendet (pv-automation.service), der zusätzlich
Engine + Actuator enthält.  Dieser Observer bleibt als leichtgewichtige
Alternative für Diagnose/Test.

Siehe: doc/AUTOMATION_ARCHITEKTUR.md §4, §8
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime
from typing import Callable

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
from automation.engine.obs_state import (
    ObsState, init_ram_db, write_obs_state,
    write_heartbeat, load_param_matrix, RAM_DB_PATH,
)

# Collector-Klassen aus Subpackage (extrahiert)
from automation.engine.collectors.tier1_checker import Tier1Checker
from automation.engine.collectors.battery_collector import BatteryCollector
from automation.engine.collectors.forecast_collector import ForecastCollector

LOG = logging.getLogger('observer')



# ═════════════════════════════════════════════════════════════
# Observer Haupt-Service
# ═════════════════════════════════════════════════════════════

class Observer:
    """Hauptprozess: Koordiniert alle Tiers, baut ObsState, prüft Schwellen.

    Lifecycle:
      1. init_ram_db()
      2. Lade Configs in param_matrix
      3. Starte Tier-2 Polling-Threads
      4. Starte Tier-3 Timer-Threads
      5. Tier-1: Schwellenprüfung bei jedem ObsState-Update
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._running = False
        self._obs = ObsState()
        self._obs_lock = threading.Lock()
        self._db_conn = None
        self._tier1 = None
        self._collectors = []
        self._threads = []

    def _load_schutz_config(self) -> dict:
        """Lade Schutzregeln aus config/battery_control.json (bestehend)."""
        cfg_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_control.json')
        try:
            with open(cfg_path, 'r') as f:
                cfg = json.load(f)
            batt = cfg.get('batterie', {})
            limits = cfg.get('leistungsbegrenzung', {}).get('temperatur_limits', {})
            sicherheit = cfg.get('sicherheit', {})
            # Erste Warnstufe aus temperatur_limits (40°C → 50%)
            warn_temps = sorted([int(k) for k in limits.keys()])
            warn_c = warn_temps[-1] if warn_temps else 40  # Höchste definierte Temp
            return {
                'batt_temp_warn_c': warn_c,
                'batt_temp_alarm_c': 45,
                'batt_temp_reduce_c_rate': 0.3,
                'batt_kapazitaet_kwh': batt.get('kapazitaet_kwh', 20.48),
                'batt_soc_kritisch': cfg.get('soc_grenzen', {}).get('absolutes_minimum', 5),
                'netz_ueberlast_warn_w': 24000,
                'netz_ueberlast_alarm_w': 26000,
            }
        except Exception as e:
            LOG.warning(f"Schutz-Config nicht ladbar: {e} — verwende Defaults")
            return {}

    def start(self):
        """Initialisiere und starte alle Tiers."""
        LOG.info("=" * 60)
        LOG.info("Observer startet")
        LOG.info(f"  RAM-DB: {RAM_DB_PATH}")
        LOG.info(f"  Dry-Run: {self.dry_run}")
        LOG.info("=" * 60)

        self._running = True
        self._db_conn = init_ram_db()

        # Schutzregeln laden
        schutz_cfg = self._load_schutz_config()
        self._tier1 = Tier1Checker(actuator=None, schutz_cfg=schutz_cfg)

        # Batterie-Collector
        import config as app_config
        batt_collector = BatteryCollector(app_config.INVERTER_IP, app_config.MODBUS_PORT)
        self._collectors.append(batt_collector)

        # Config in RAM-DB laden
        cfg_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_control.json')
        load_param_matrix(self._db_conn, 'batterie', cfg_path)

        # Tier-2: Batterie-Modbus (5 s)
        t_modbus = threading.Thread(
            target=self._tier2_loop,
            args=('modbus_5s', 5, batt_collector.collect_modbus),
            daemon=True, name='tier2-modbus'
        )
        self._threads.append(t_modbus)

        # Tier-2: Batterie-HTTP (intern 30 s Rate-Limit)
        t_http = threading.Thread(
            target=self._tier2_loop,
            args=('http_30s', 10, batt_collector.collect_http),
            daemon=True, name='tier2-http'
        )
        self._threads.append(t_http)

        # Tier-3: Forecast (Trigger-basiert, alle 30s prüfen)
        forecast_collector = ForecastCollector()
        self._collectors.append(forecast_collector)
        t_forecast = threading.Thread(
            target=self._tier3_forecast_loop,
            args=(forecast_collector,),
            daemon=True, name='tier3-forecast'
        )
        self._threads.append(t_forecast)

        for t in self._threads:
            t.start()

        LOG.info(f"Observer gestartet: {len(self._threads)} Tier-2/3 Threads")

    def _tier2_loop(self, name: str, interval: float,
                    collect_fn: Callable[[ObsState], None]):
        """Generischer Polling-Loop für einen Collector."""
        LOG.info(f"  Tier-2 '{name}' gestartet (alle {interval}s)")
        while self._running:
            try:
                with self._obs_lock:
                    self._obs.ts = datetime.now().isoformat()
                    collect_fn(self._obs)

                # Tier-1 Schwellenprüfung nach jedem Update
                with self._obs_lock:
                    tier1_actions = self._tier1.check(self._obs)

                # ObsState in RAM-DB schreiben
                with self._obs_lock:
                    write_obs_state(self._db_conn, self._obs)

                # Tier-1 Sofort-Aktionen
                if tier1_actions:
                    self._handle_tier1_actions(tier1_actions)

                # Heartbeat
                write_heartbeat(self._db_conn, f'observer.{name}')

            except Exception as e:
                LOG.error(f"Tier-2 '{name}' Fehler: {e}", exc_info=True)

            time.sleep(interval)

    def _tier3_forecast_loop(self, collector: ForecastCollector):
        """Tier-3 Loop für Forecast: prüft alle 30s ob Trigger fällig."""
        LOG.info("  Tier-3 'forecast' gestartet (Trigger: startup, sunrise, 10:00, 14:00)")
        while self._running:
            try:
                with self._obs_lock:
                    collector.collect(self._obs)

                # ObsState in RAM-DB schreiben (nur wenn sich Forecast geändert hat)
                with self._obs_lock:
                    if self._obs.forecast_ts:
                        write_obs_state(self._db_conn, self._obs)

                # Heartbeat
                write_heartbeat(self._db_conn, 'observer.forecast')

            except Exception as e:
                LOG.error(f"Tier-3 'forecast' Fehler: {e}", exc_info=True)

            time.sleep(30)  # Alle 30s prüfen ob Trigger fällig

    def _handle_tier1_actions(self, actions: list[dict]):
        """Tier-1 Sofort-Aktionen an Actuator dispatchen."""
        for action in actions:
            LOG.warning(f"TIER-1 AKTION: {action['aktor']}.{action['kommando']} "
                        f"— {action['grund']}")
            if self.dry_run:
                LOG.info(f"  [DRY-RUN] Würde ausführen: {action}")
            else:
                # TODO: An Actuator dispatchen (Phase 1: nur Logging)
                LOG.info(f"  [PHASE-1] Actuator noch nicht verbunden — nur Log")

    def stop(self):
        """Sauberes Shutdown."""
        LOG.info("Observer wird gestoppt...")
        self._running = False
        for t in self._threads:
            t.join(timeout=5)
        for c in self._collectors:
            if hasattr(c, 'close'):
                c.close()
        if self._db_conn:
            self._db_conn.close()
        LOG.info("Observer gestoppt.")

    def get_obs_state(self) -> ObsState:
        """Thread-safe Kopie des aktuellen ObsState."""
        with self._obs_lock:
            return ObsState.from_json(self._obs.to_json())


# ═════════════════════════════════════════════════════════════
# CLI Entry Point
# ═════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='PV-Automation Observer — 3-Tier Beobachtungsservice',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Keine Aktor-Aktionen, nur Logging')
    parser.add_argument('--once', action='store_true',
                        help='Einmal sammeln und ausgeben, dann beenden')
    parser.add_argument('--log-level', default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
        datefmt='%H:%M:%S',
    )

    observer = Observer(dry_run=args.dry_run)

    # Signal-Handler für sauberes Shutdown
    def _signal_handler(sig, frame):
        LOG.info(f"Signal {sig} empfangen — stoppe Observer")
        observer.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    observer.start()

    if args.once:
        # Einmal 10 Sekunden sammeln, dann Status ausgeben
        time.sleep(10)
        obs = observer.get_obs_state()
        print(json.dumps(json.loads(obs.to_json()), indent=2, ensure_ascii=False))
        observer.stop()
    else:
        # Dauerbetrieb
        LOG.info("Observer läuft — Ctrl+C oder SIGTERM zum Beenden")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()


if __name__ == '__main__':
    main()
