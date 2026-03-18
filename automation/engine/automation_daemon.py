#!/usr/bin/env python3
"""
automation_daemon.py — S4 Engine-Daemon (Observer→Engine→Actuator Loop)

Eigenständiger Prozess der alle Schichten orchestriert:
  - DataCollector: Sensor-Daten aus Collector-DB + Modbus + HTTP
  - ForecastCollector: Solar-Prognose trigger-basiert (Tier 3)
  - Tier-1: Schwellenprüfung bei jedem Update (Sofort-Aktionen)
  - Engine: Score-basierte Regelauswertung (fast=1min, strategic=15min)
  - Actuator: Ausführung + Persist-DB-Logging (automation_log)

Aufruf:
  cd <project-root>
  python3 -m automation.engine.automation_daemon
  python3 -m automation.engine.automation_daemon --dry-run
  python3 -m automation.engine.automation_daemon --once     # 1 Zyklus

Systemd-Service: pv-automation.service
Siehe: doc/AUTOMATION_ARCHITEKTUR.md §8 (Prozessdiagramm)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import sys
import threading
import time
import atexit
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ── Projekt-Root ─────────────────────────────────────────────
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
import config as app_config
from automation.engine.obs_state import (
    ObsState, init_ram_db, write_obs_state, read_obs_state,
    write_heartbeat, RAM_DB_PATH,
)
from automation.engine.collectors import DataCollector, Tier1Checker, ForecastCollector
from automation.engine.actuator import Actuator
from automation.engine.engine import Engine
from automation.engine.event_notifier import EventNotifier
from automation.engine.param_matrix import DEFAULT_MATRIX_PATH

LOG = logging.getLogger('automation_daemon')

# ── Konstanten ───────────────────────────────────────────────
FAST_INTERVAL = 60          # Sekunden — Engine fast-Zyklus
STRATEGIC_INTERVAL = 900    # Sekunden — Engine strategic-Zyklus (15 min)
OBS_COLLECT_INTERVAL = 10   # Sekunden — ObsState Datensammlung
PID_FILE = Path(__file__).parent.parent.parent / 'automation_daemon.pid'



# ═════════════════════════════════════════════════════════════
# Daemon-Hauptklasse
# ═════════════════════════════════════════════════════════════

class AutomationDaemon:
    """S4 Orchestrator: Observer + Engine + Actuator in einem Prozess.

    Lifecycle:
      1. init_ram_db()
      2. DataCollector → ObsState (alle 10s)
      3. Tier1Checker (bei jedem ObsState-Update)
      4. Engine.zyklus('fast') alle 60s
      5. Engine.zyklus('strategic') alle 15min
      6. Actuator: Ausführung + Persist-DB
    """

    def __init__(self, dry_run: bool = False, once: bool = False):
        self.dry_run = dry_run
        self.once = once
        self._running = False

        # Komponenten
        self._db_conn = None
        self._collector = DataCollector()
        self._forecast_collector = ForecastCollector()  # Vorlauf wird in start() gesetzt
        self._obs = ObsState()
        self._obs_lock = threading.Lock()
        self._tier1 = None
        self._actuator = None
        self._engine = None
        self._notifier = None
        self._forecast_thread = None

        # Timing
        self._last_fast = 0
        self._last_strategic = 0
        self._cycle_count = 0

        # Sunset-Erkennung für Tagesbericht
        self._war_tag: Optional[bool] = None  # is_day im vorherigen Zyklus

        # SIGHUP → Matrix-Reload
        self._reload_requested = False

    def start(self):
        """Initialisiere alle Komponenten."""
        LOG.info("=" * 60)
        LOG.info(f"Automation-Daemon startet (dry_run={self.dry_run})")
        LOG.info(f"  Collector-DB:  {app_config.DB_PATH}")
        LOG.info(f"  RAM-DB:        {RAM_DB_PATH}")
        LOG.info(f"  Matrix:        {DEFAULT_MATRIX_PATH}")
        LOG.info("=" * 60)

        # RAM-DB
        self._db_conn = init_ram_db()

        # Tier-1 Schutzregeln
        schutz_cfg = self._load_schutz_config()
        self._tier1 = Tier1Checker(actuator=None, schutz_cfg=schutz_cfg)

        # Actuator (Persist-DB = data.db auf Disk — dort liest die Web-API)
        # NICHT app_config.DB_PATH verwenden — das ist die RAM-Collector-DB!
        _persist_path = os.path.join(_PROJECT_ROOT, 'data.db')
        self._actuator = Actuator(
            dry_run=self.dry_run,
            persist_db_path=_persist_path,
        )

        # Engine
        self._engine = Engine(
            actuator=self._actuator,
            dry_run=self.dry_run,
            matrix_path=DEFAULT_MATRIX_PATH,
        )

        # Event-Notifier (E-Mail bei kritischen Events)
        self._notifier = EventNotifier()
        if self._notifier.aktive_events:
            LOG.info(f"  Event-Notifier: {len(self._notifier.aktive_events)} Events aktiv "
                     f"→ {getattr(app_config, 'NOTIFICATION_EMAIL', '?')}")
        else:
            LOG.info("  Event-Notifier: keine Events konfiguriert")

        # Morgen-Vorlauf aus Parametermatrix an ForecastCollector übergeben
        from automation.engine.param_matrix import get_param
        vorlauf = get_param(self._engine._matrix, 'morgen_soc_min',
                            'morgen_vorlauf_min', 15)
        self._forecast_collector.morgen_vorlauf_min = vorlauf
        LOG.info(f"  Morgen-Vorlauf: {vorlauf} min (Sunrise-Trigger vorgezogen)")

        self._running = True

        # ── HP-Startup-Schutz ──────────────────────────────────
        # Wenn der Daemon nach einem Crash neu startet und die HP noch
        # ein ist (Fritz!DECT-Steckdose behält Zustand), sofort abschalten.
        # Siehe: doc/TIEFENPRUEFUNG_2026-03-08.md §7.3
        self._hp_startup_check()

        # Tier-3: Forecast-Thread (trigger-basiert, prüft alle 30s)
        if not self.once:
            self._forecast_thread = threading.Thread(
                target=self._tier3_forecast_loop,
                daemon=True, name='tier3-forecast'
            )
            self._forecast_thread.start()
            LOG.info("  Tier-3 Forecast-Thread gestartet")

        # Matrix-mtime merken
        try:
            self._matrix_mtime = os.path.getmtime(DEFAULT_MATRIX_PATH)
        except OSError:
            self._matrix_mtime = 0

        LOG.info(f"Daemon bereit — {len(self._engine._regeln)} Regeln registriert")

    def _load_schutz_config(self) -> dict:
        """Lade Tier-1 Schwellwerte aus battery_control.json."""
        cfg_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_control.json')
        try:
            with open(cfg_path, 'r') as f:
                cfg = json.load(f)
            batt = cfg.get('batterie', {})
            return {
                'batt_temp_warn_c': 40,
                'batt_temp_alarm_c': 45,
                'batt_temp_reduce_c_rate': 0.3,
                'batt_kapazitaet_kwh': batt.get('kapazitaet_kwh', 20.48),
                'batt_soc_kritisch': cfg.get('soc_grenzen', {}).get('absolutes_minimum', 5),
            }
        except Exception as e:
            LOG.warning(f"Schutz-Config: {e} → Defaults")
            return {}

    # ── HP-Startup-Schutz ───────────────────────────────────

    def _hp_startup_check(self):
        """Prüfe HP-Status beim Start und schalte ggf. ab.

        Wenn der Daemon nach einem Crash neu startet, kann die HP noch
        ein sein (Fritz!DECT-Steckdose behält Zustand). Hier wird der
        Status geprüft und bei Bedarf sofort abgeschaltet.
        """
        try:
            from automation.engine.aktoren.aktor_fritzdect import (
                _load_fritz_config, _get_session_id, _aha_device_info
            )
            cfg = _load_fritz_config()
            host = cfg.get('fritz_ip', '192.168.178.1')
            ain = cfg.get('ain', '')
            user = cfg.get('fritz_user', '')
            pw = cfg.get('fritz_password', '')
            if not (ain and user and pw):
                LOG.debug("HP-Startup-Check: Fritz!DECT nicht konfiguriert")
                return

            sid = _get_session_id(host, user, pw)
            if not sid:
                LOG.warning("HP-Startup-Check: Fritz!Box nicht erreichbar")
                return

            info = _aha_device_info(host, ain, sid)
            if not info:
                LOG.warning("HP-Startup-Check: Gerät nicht gefunden")
                return

            if str(info.get('state', '0')).strip() == '1':
                LOG.warning("HP-Startup-Check: HP war EIN beim Daemon-Start → schalte AUS")
                if not self.dry_run:
                    self._actuator.ausfuehren({
                        'tier': 1,
                        'aktor': 'fritzdect',
                        'kommando': 'hp_aus',
                        'grund': 'HP-Startup-Schutz: HP war EIN nach Daemon-(Neu-)Start',
                    })
                else:
                    LOG.info("  [DRY-RUN] Würde HP abschalten")
            else:
                LOG.info("HP-Startup-Check: HP ist AUS — OK")

        except Exception as e:
            LOG.warning(f"HP-Startup-Check fehlgeschlagen: {e}")

    # ── Tier-3 Forecast ─────────────────────────────────────

    def _tier3_forecast_loop(self):
        """Tier-3 Loop: prüft alle 30s ob Forecast-Trigger fällig.

        Läuft als separater Thread — ForecastCollector entscheidet selbst
        ob ein Fetch nötig ist (startup, sunrise, 10:00, 14:00, fallback 6h).
        """
        LOG.info("  Tier-3 'forecast' gestartet (Trigger: startup, sunrise, 10:00, 14:00)")
        while self._running:
            try:
                with self._obs_lock:
                    self._forecast_collector.collect(self._obs)

                    # ObsState in RAM-DB schreiben wenn sich Forecast geändert hat
                    if self._obs.forecast_ts:
                        write_obs_state(self._db_conn, self._obs)

                    write_heartbeat(self._db_conn, 'daemon.forecast')

            except Exception as e:
                LOG.error(f"Tier-3 'forecast' Fehler: {e}", exc_info=True)

            time.sleep(30)

    # ── Haupt-Loop ───────────────────────────────────────────

    def run(self):
        """Endlos-Schleife: Collect → Check → Engine."""
        self.start()

        if self.once:
            self._run_cycle()
            self._print_status()
            self.stop()
            return

        try:
            while self._running:
                self._run_cycle()
                time.sleep(OBS_COLLECT_INTERVAL)
        except KeyboardInterrupt:
            LOG.info("Ctrl+C → Shutdown")
        finally:
            self.stop()

    def _run_cycle(self):
        """Ein Datensammel- und Entscheidungszyklus."""
        now = time.time()
        self._cycle_count += 1

        # 1. Daten sammeln → ObsState (thread-safe wg. Forecast-Thread)
        try:
            with self._obs_lock:
                self._collector.collect(self._obs)
        except Exception as e:
            LOG.error(f"Collector Fehler: {e}")
            return

        # 1b. Bei --once: Forecast synchron ausführen (kein Thread)
        if self.once:
            try:
                with self._obs_lock:
                    self._forecast_collector.collect(self._obs)
            except Exception as e:
                LOG.warning(f"Forecast-Collect: {e}")

        # 2. Tier-1 Schwellenprüfung
        with self._obs_lock:
            tier1_actions = self._tier1.check(self._obs)

        # 3. ObsState in RAM-DB schreiben
        try:
            with self._obs_lock:
                write_obs_state(self._db_conn, self._obs)
                write_heartbeat(self._db_conn, 'automation_daemon')
        except Exception as e:
            LOG.error(f"RAM-DB Schreibfehler: {e}")
            # Verbindung neu aufbauen
            try:
                self._db_conn = init_ram_db()
            except Exception:
                pass

        # 4. Tier-1 Sofort-Aktionen
        if tier1_actions:
            for action in tier1_actions:
                LOG.warning(f"TIER-1: {action['aktor']}.{action['kommando']} "
                            f"— {action['grund']}")
                if not self.dry_run:
                    self._actuator.ausfuehren(action)
                else:
                    LOG.info(f"  [DRY-RUN] {action}")

        # 4b. Event-Benachrichtigungen prüfen (1× pro Event pro Tag)
        if self._notifier:
            try:
                with self._obs_lock:
                    ausgeloest = self._notifier.prüfe_und_melde(self._obs)
                if ausgeloest:
                    LOG.info(f"Event-Benachrichtigung: {', '.join(ausgeloest)}")
            except Exception as e:
                LOG.error(f"Event-Notifier Fehler: {e}")

        # 5. Matrix-Reload bei SIGHUP
        if self._reload_requested:
            self._reload_requested = False
            try:
                self._engine.reload_matrix()
                LOG.info("SIGHUP: Parametermatrix neu geladen")
            except Exception as e:
                LOG.error(f"Matrix-Reload Fehler: {e}")

        # 6. Engine fast-Zyklus (alle 60 s)
        if now - self._last_fast >= FAST_INTERVAL:
            try:
                results = self._engine.zyklus('fast')
                if results:
                    LOG.info(f"Engine-fast: {len(results)} Aktion(en)")
                self._last_fast = now
            except Exception as e:
                LOG.error(f"Engine fast-Zyklus: {e}")

        # 7. Engine strategic-Zyklus (alle 15 min)
        if now - self._last_strategic >= STRATEGIC_INTERVAL:
            try:
                results = self._engine.zyklus('strategic')
                if results:
                    LOG.info(f"Engine-strategic: {len(results)} Aktion(en)")
                self._last_strategic = now
            except Exception as e:
                LOG.error(f"Engine strategic-Zyklus: {e}")

        # 7. Sunset-Erkennung → Tagesbericht senden
        with self._obs_lock:
            is_day_now = self._obs.is_day
        if self._notifier and is_day_now is not None:
            if self._war_tag is True and is_day_now is False:
                LOG.info("Sunset erkannt → Tagesbericht wird gesendet")
                try:
                    with self._obs_lock:
                        self._notifier.sende_sunset_bericht(self._obs)
                except Exception as e:
                    LOG.error(f"Sunset-Tagesbericht Fehler: {e}")
            self._war_tag = is_day_now

        # Heartbeat-Log (alle 5 min)
        if self._cycle_count % (300 // OBS_COLLECT_INTERVAL) == 0:
            LOG.info(f"Heartbeat: Zyklus #{self._cycle_count}, "
                     f"SOC={self._obs.batt_soc_pct}%, "
                     f"PV={self._obs.pv_total_w}W, "
                     f"Netz={self._obs.grid_power_w}W")

    def _print_status(self):
        """Status-Ausgabe (für --once Modus)."""
        obs = self._obs
        print(f"\n{'=' * 60}")
        print(f"  AUTOMATION DAEMON — Status")
        print(f"{'=' * 60}")
        print(f"  PV:      {obs.pv_total_w or 0:>7.0f} W  (heute: {obs.pv_today_kwh or 0:.1f} kWh)")
        print(f"  Netz:    {obs.grid_power_w or 0:>7.0f} W")
        print(f"  Batterie:{obs.batt_power_w or 0:>7.0f} W  SOC: {obs.batt_soc_pct or 0:.1f}%")
        print(f"  WP:      {obs.wp_power_w or 0:>7.0f} W  (aktiv: {obs.wp_active})")
        print(f"  EV:      {obs.ev_power_w or 0:>7.0f} W  (lädt: {obs.ev_charging})")
        print(f"  Haus:    {obs.house_load_w or 0:>7.0f} W")
        print(f"  Prognose: {obs.forecast_kwh or '?'} kWh, Rest: {obs.forecast_rest_kwh or '?'} kWh")
        print(f"  Wolken:   jetzt {obs.cloud_now_pct or '?'}%, Rest {obs.cloud_rest_avg_pct or '?'}%")
        print(f"  IST/SOLL: {obs.pv_vs_forecast_pct or '?'}%")
        print(f"  SOC-Range: {obs.soc_min or '?'}–{obs.soc_max or '?'}% (Mode: {obs.soc_mode or '?'})")
        print(f"  Sunrise:  {obs.sunrise or '?'}h  Sunset: {obs.sunset or '?'}h")
        print(f"{'=' * 60}")
        print(f"  ObsState JSON:")
        print(json.dumps(json.loads(obs.to_json()), indent=2, ensure_ascii=False))

    def stop(self):
        """Sauberes Shutdown."""
        LOG.info("Daemon wird gestoppt...")
        self._running = False
        # Forecast-Thread sauber beenden (max 5s warten)
        if self._forecast_thread and self._forecast_thread.is_alive():
            self._forecast_thread.join(timeout=5)
            if self._forecast_thread.is_alive():
                LOG.warning("Forecast-Thread reagiert nicht — wird beim Exit beendet")
        if self._engine:
            self._engine.close()
        if self._actuator:
            self._actuator.close()
        if self._db_conn:
            self._db_conn.close()
        # PID-File entfernen
        if PID_FILE.exists():
            PID_FILE.unlink(missing_ok=True)
        LOG.info("Daemon gestoppt.")

    # ── Vorausschau (für Web-API) ────────────────────────────

    def vorausschau(self) -> list[dict]:
        """Dry-Run Zyklus: Was würde die Engine JETZT tun?

        Führt bewerte() für alle Regeln aus, aber KEINE Aktionen.
        Gibt Liste von {regel, score, aktionen[]} zurück.
        """
        conn = self._db_conn or init_ram_db()
        obs = read_obs_state(conn)
        if obs is None:
            return []

        matrix = self._engine._matrix if self._engine else {}
        vorschau = []

        for regel in (self._engine._regeln if self._engine else []):
            try:
                score = regel.bewerte(obs, matrix)
                if score > 0:
                    aktionen = regel.erzeuge_aktionen(obs, matrix)
                    vorschau.append({
                        'regel': regel.name,
                        'score': score,
                        'zyklus': regel.engine_zyklus,
                        'aktionen': aktionen,
                    })
            except Exception as e:
                LOG.debug(f"Vorausschau {regel.name}: {e}")

        vorschau.sort(key=lambda x: x['score'], reverse=True)
        return vorschau


# ═════════════════════════════════════════════════════════════
# Standalone Vorausschau-Funktion (für Web-API ohne laufenden Daemon)
# ═════════════════════════════════════════════════════════════

def engine_vorausschau() -> list[dict]:
    """Statische Funktion: Liest ObsState aus RAM-DB, führt Dry-Run aus.

    Kann von der Web-API aufgerufen werden ohne laufenden Daemon.
    Liest nur RAM-DB + Parametermatrix, keine Hardware-Zugriffe.
    """
    try:
        if not os.path.exists(RAM_DB_PATH):
            return []

        conn = sqlite3.connect(
            f'file:{RAM_DB_PATH}?mode=ro', uri=True, timeout=3.0
        )
        obs = read_obs_state(conn)
        conn.close()

        if obs is None:
            return []

        from automation.engine.param_matrix import lade_matrix
        matrix = lade_matrix(DEFAULT_MATRIX_PATH)

        from automation.engine.regeln import (
            RegelSlsSchutz,
            RegelKomfortReset,
            RegelMorgenSocMin, RegelNachmittagSocMax, RegelZellausgleich,
            RegelForecastPlausi, RegelWattpilotBattSchutz,
            RegelHeizpatrone,
        )

        regeln = [
            RegelSlsSchutz(),
            RegelKomfortReset(),
            RegelMorgenSocMin(), RegelNachmittagSocMax(), RegelZellausgleich(),
            RegelForecastPlausi(), RegelWattpilotBattSchutz(),
            RegelHeizpatrone(),
        ]

        vorschau = []
        for regel in regeln:
            try:
                score = regel.bewerte(obs, matrix)
                if score > 0:
                    aktionen = regel.erzeuge_aktionen(obs, matrix)
                    vorschau.append({
                        'regel': regel.name,
                        'score': score,
                        'zyklus': regel.engine_zyklus,
                        'aktionen': [{
                            'kommando': a.get('kommando'),
                            'wert': a.get('wert'),
                            'grund': a.get('grund', ''),
                            'hinweis': a.get('hinweis', ''),
                        } for a in aktionen],
                    })
            except Exception as e:
                LOG.debug(f"Vorausschau {regel.name}: {e}")

        vorschau.sort(key=lambda x: x['score'], reverse=True)
        return vorschau

    except Exception as e:
        LOG.warning(f"engine_vorausschau: {e}")
        return []


# ═════════════════════════════════════════════════════════════
# CLI Entry Point
# ═════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='PV-Automation Daemon — S4 Engine-Loop',
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Keine Hardware-Aktionen, nur Logging + DB')
    parser.add_argument('--once', action='store_true',
                        help='Einmal sammeln + Engine-Zyklus, dann beenden')
    parser.add_argument('--vorausschau', action='store_true',
                        help='Nur Vorausschau anzeigen (Dry-Run aller Regeln)')
    parser.add_argument('--log-level', default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s %(name)-18s %(levelname)-8s %(message)s',
        datefmt='%H:%M:%S',
    )

    if args.vorausschau:
        # Nur Vorausschau — braucht keinen laufenden Daemon
        vorschau = engine_vorausschau()
        if not vorschau:
            print("Keine aktiven Regeln (RAM-DB leer oder keine Schwellen erreicht)")
            return
        print(f"\n{'=' * 60}")
        print(f"  ENGINE VORAUSSCHAU — {len(vorschau)} aktive Regel(n)")
        print(f"{'=' * 60}")
        for v in vorschau:
            print(f"\n  [{v['score']:>3}] {v['regel']} ({v['zyklus']})")
            for a in v['aktionen']:
                print(f"        → {a['kommando']} = {a.get('wert', '-')}")
                if a.get('grund'):
                    print(f"          {a['grund'][:80]}")
        return

    # PID-File Stale-Check und Schreiben
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            os.kill(old_pid, 0)  # Prüfe ob Prozess lebt
            print(f"FEHLER: Automation-Daemon läuft bereits (PID {old_pid})")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            LOG.warning(f"Stale PID-File entfernt (PID {PID_FILE.read_text().strip()})")
            PID_FILE.unlink(missing_ok=True)
        except PermissionError:
            print(f"FEHLER: Prozess PID {old_pid} existiert, aber keine Berechtigung")
            sys.exit(1)

    PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: PID_FILE.unlink(missing_ok=True))

    # Signal-Handler
    daemon = AutomationDaemon(dry_run=args.dry_run, once=args.once)

    def _signal_handler(sig, frame):
        LOG.info(f"Signal {sig} → Shutdown")
        daemon._running = False

    def _sighup_handler(sig, frame):
        LOG.info("SIGHUP → Matrix-Reload angefordert")
        daemon._reload_requested = True

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGHUP, _sighup_handler)

    daemon.run()


if __name__ == '__main__':
    main()
