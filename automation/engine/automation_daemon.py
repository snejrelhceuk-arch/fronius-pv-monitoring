#!/usr/bin/env python3
"""
automation_daemon.py — S4 Engine-Daemon (Observer→Engine→Actuator Loop)

Eigenständiger Prozess der alle Schichten orchestriert:
  - Liest Sensor-Daten aus der bestehenden Collector-DB (raw_data, wattpilot_readings)
  - Liest Forecast-/Geometrie-Daten aus solar_forecast
  - Befüllt ObsState und schreibt in RAM-DB
  - Tier-1: Schwellenprüfung bei jedem Update (Sofort-Aktionen)
  - Engine: Score-basierte Regelauswertung (fast=1min, strategic=15min)
  - Actuator: Ausführung + Persist-DB-Logging (automation_log)

Aufruf:
  cd /srv/pv-system
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
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ── Projekt-Root ─────────────────────────────────────────────
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import config as app_config
from automation.engine.obs_state import (
    ObsState, init_ram_db, write_obs_state, read_obs_state,
    write_heartbeat, RAM_DB_PATH,
)
from automation.engine.observer import Tier1Checker
from automation.engine.actuator import Actuator
from automation.engine.engine import Engine
from automation.engine.param_matrix import DEFAULT_MATRIX_PATH

LOG = logging.getLogger('automation_daemon')

# ── Konstanten ───────────────────────────────────────────────
FAST_INTERVAL = 60          # Sekunden — Engine fast-Zyklus
STRATEGIC_INTERVAL = 900    # Sekunden — Engine strategic-Zyklus (15 min)
OBS_COLLECT_INTERVAL = 10   # Sekunden — ObsState Datensammlung
PID_FILE = Path(__file__).parent.parent.parent / 'automation_daemon.pid'


# ═════════════════════════════════════════════════════════════
# DataCollector: Liest aus bestehender Collector-DB
# ═════════════════════════════════════════════════════════════

class DataCollector:
    """Liest Sensor-Daten aus der Collector-DB → ObsState.

    KEIN eigener Modbus-Zugriff — nutzt was collector.py + modbus_v3
    bereits in /dev/shm/fronius_data.db schreiben.
    """

    def __init__(self, db_path: str = None):
        self._db_path = db_path or app_config.DB_PATH
        self._forecast_cache = None
        self._forecast_cache_ts = 0

    def _get_conn(self) -> Optional[sqlite3.Connection]:
        """Öffne read-only Verbindung zur Collector-DB."""
        try:
            if not os.path.exists(self._db_path):
                return None
            conn = sqlite3.connect(
                f'file:{self._db_path}?mode=ro', uri=True, timeout=3.0
            )
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            LOG.warning(f"Collector-DB nicht lesbar: {e}")
            return None

    def collect(self, obs: ObsState):
        """Sammle ALLE verfügbaren Daten → ObsState."""
        obs.ts = datetime.now().isoformat()
        self._collect_raw_data(obs)
        self._collect_wattpilot(obs)
        self._collect_battery_settings(obs)
        self._collect_pv_today(obs)      # VOR forecast — braucht pv_today_kwh
        self._collect_wp_today(obs)
        self._collect_geometry(obs)
        self._collect_forecast(obs)      # NACH pv_today für Rest-Prognose + IST/SOLL

    # ── raw_data: PV, Netz, Batterie (aus Collector/Modbus) ──

    def _collect_raw_data(self, obs: ObsState):
        """Aktuellste raw_data-Zeile → ObsState Erzeuger/Netz/Batterie."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            now = int(time.time())
            row = conn.execute(
                "SELECT * FROM raw_data WHERE ts > ? ORDER BY ts DESC LIMIT 1",
                (now - 120,)
            ).fetchone()
            if not row:
                return

            d = dict(row)

            # ── Erzeuger ──
            p_dc1 = d.get('P_DC1', 0) or 0
            p_dc2 = d.get('P_DC2', 0) or 0
            p_f2 = d.get('P_F2', 0) or 0
            p_f3 = d.get('P_F3', 0) or 0
            obs.pv_f1_w = round(p_dc1 + p_dc2, 0)
            obs.pv_f2_w = round(p_f2, 0)
            obs.pv_f3_w = round(p_f3, 0)
            obs.pv_total_w = round(obs.pv_f1_w + obs.pv_f2_w + obs.pv_f3_w, 0)

            # ── Netz ──
            p_netz = d.get('P_Netz', 0) or 0
            obs.grid_power_w = round(p_netz, 0)

            # ── Batterie (Strom/Spannung aus API) ──
            i_batt = d.get('I_Batt_API', 0) or 0
            u_batt = d.get('U_Batt_API', 0) or 0
            obs.batt_power_w = round(i_batt * u_batt, 0)
            obs.batt_soc_pct = d.get('SOC_Batt') or obs.batt_soc_pct
            obs.cha_state = d.get('ChaSt_Batt') or obs.cha_state

            # ── Verbraucher ──
            p_wp = d.get('P_WP', 0) or 0
            obs.wp_power_w = abs(p_wp)
            obs.wp_active = obs.wp_power_w > 200  # Schwelle: 200W

            # ── Hausverbrauch (Bilanz) ──
            verbrauch = obs.pv_total_w - obs.batt_power_w + obs.grid_power_w
            obs.house_load_w = max(0, round(verbrauch, 0))

        except Exception as e:
            LOG.warning(f"raw_data collect: {e}")
        finally:
            conn.close()

    # ── WattPilot ────────────────────────────────────────────

    def _collect_wattpilot(self, obs: ObsState):
        """WattPilot Live-Daten aus wattpilot_readings."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            now = int(time.time())
            row = conn.execute(
                "SELECT power_w, car_state FROM wattpilot_readings "
                "WHERE ts > ? ORDER BY ts DESC LIMIT 1",
                (now - 120,)
            ).fetchone()
            if row:
                obs.ev_power_w = round(row[0] or 0, 0)
                car_state = row[1] or 0
                obs.ev_charging = (car_state == 2)
                obs.ev_state = {
                    0: 'unknown', 1: 'disconnected', 2: 'charging',
                    3: 'waiting', 4: 'complete', 5: 'error'
                }.get(car_state, 'unknown')
            else:
                obs.ev_power_w = 0
                obs.ev_charging = False
        except Exception as e:
            LOG.debug(f"wattpilot collect: {e}")
        finally:
            conn.close()

    # ── Batterie SOC/Mode Settings ───────────────────────────

    def _collect_battery_settings(self, obs: ObsState):
        """SOC_MIN/MAX/Mode aus Batterie-Config oder letzer bekannter Wert."""
        cfg_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_scheduler_state.json')
        try:
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r') as f:
                    state = json.load(f)
                # Diese Werte werden ggf. durch Observer-Modbus überschrieben
                if obs.soc_min is None:
                    obs.soc_min = state.get('current_soc_min')
                if obs.soc_max is None:
                    obs.soc_max = state.get('current_soc_max')
        except Exception as e:
            LOG.debug(f"battery_settings: {e}")

    # ── Solar Forecast ───────────────────────────────────────

    def _collect_forecast(self, obs: ObsState):
        """Prognose + Wolken aus solar_forecast (Cache: 15 min)."""
        now = time.time()
        if now - self._forecast_cache_ts < 900 and self._forecast_cache:
            self._apply_forecast_cache(obs)
            return

        try:
            from solar_forecast import SolarForecast
            sf = SolarForecast()

            # Tagesprognose [kWh]
            try:
                fc = sf.get_day_forecast()
                if fc and 'expected_kwh' in fc:
                    obs.forecast_kwh = round(fc['expected_kwh'], 1)
            except Exception:
                pass

            # Stündliche Wolken + Power-Forecast
            try:
                hourly = sf.get_hourly_forecast()
                if hourly:
                    now_h = datetime.now().hour
                    # Aktuelle Wolken
                    for h in hourly:
                        h_start = h.get('hour', 0)
                        if h_start == now_h:
                            obs.cloud_now_pct = h.get('cloud_cover')
                            break

                    # Tagesdurchschnitt + Resttag
                    all_clouds = [h.get('cloud_cover', 50) for h in hourly]
                    rest_clouds = [h.get('cloud_cover', 50) for h in hourly
                                   if h.get('hour', 0) >= now_h]
                    if all_clouds:
                        obs.cloud_avg_pct = round(sum(all_clouds) / len(all_clouds), 1)
                    if rest_clouds:
                        obs.cloud_rest_avg_pct = round(sum(rest_clouds) / len(rest_clouds), 1)
            except Exception:
                pass

            # Rest-Prognose + IST/SOLL
            if obs.forecast_kwh and obs.pv_today_kwh is not None:
                obs.forecast_rest_kwh = max(0, round(obs.forecast_kwh - obs.pv_today_kwh, 1))

                # IST/SOLL-Verhältnis: was hätten wir bis jetzt erzeugen sollen?
                try:
                    power_hourly = sf.get_hourly_power_forecast()
                    if power_hourly:
                        expected_so_far_kwh = 0.0
                        for hd in power_hourly:
                            h_hour = hd.get('hour', 0)
                            if h_hour < now_h:
                                # Summe über alle Strings
                                h_total = sum(v for k, v in hd.items()
                                              if k != 'hour' and isinstance(v, (int, float)))
                                expected_so_far_kwh += h_total / 1000.0  # W→kWh (1h)
                        if expected_so_far_kwh > 0.5:  # Nur wenn >0.5 kWh erwartet
                            obs.pv_vs_forecast_pct = round(
                                (obs.pv_today_kwh / expected_so_far_kwh) * 100, 1)
                except Exception:
                    pass

            # Cache speichern
            self._forecast_cache = {
                'forecast_kwh': obs.forecast_kwh,
                'cloud_now_pct': obs.cloud_now_pct,
                'cloud_avg_pct': obs.cloud_avg_pct,
                'cloud_rest_avg_pct': obs.cloud_rest_avg_pct,
            }
            self._forecast_cache_ts = now

        except ImportError:
            LOG.debug("solar_forecast nicht verfügbar")
        except Exception as e:
            LOG.warning(f"forecast collect: {e}")

    def _apply_forecast_cache(self, obs: ObsState):
        """Wende gecachte Forecast-Werte an."""
        c = self._forecast_cache
        if not c:
            return
        obs.forecast_kwh = c.get('forecast_kwh', obs.forecast_kwh)
        obs.cloud_now_pct = c.get('cloud_now_pct', obs.cloud_now_pct)
        obs.cloud_avg_pct = c.get('cloud_avg_pct', obs.cloud_avg_pct)
        obs.cloud_rest_avg_pct = c.get('cloud_rest_avg_pct', obs.cloud_rest_avg_pct)
        # Rest-Prognose immer frisch berechnen
        if obs.forecast_kwh and obs.pv_today_kwh is not None:
            obs.forecast_rest_kwh = max(0, round(obs.forecast_kwh - obs.pv_today_kwh, 1))

    # ── PV-Erzeugung heute ───────────────────────────────────

    def _collect_pv_today(self, obs: ObsState):
        """Bisherige PV-Erzeugung heute aus data_1min."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            today_start = int(time.mktime(date.today().timetuple()))
            row = conn.execute(
                "SELECT SUM(W_Ertrag) / 1000.0 FROM data_1min WHERE ts >= ?",
                (today_start,)
            ).fetchone()
            if row and row[0] is not None:
                obs.pv_today_kwh = round(row[0], 2)
        except Exception as e:
            LOG.debug(f"pv_today: {e}")
        finally:
            conn.close()

    # ── WP-Verbrauch heute ───────────────────────────────────

    def _collect_wp_today(self, obs: ObsState):
        """WP-Verbrauch heute über Zählerstand-Differenz."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            today_start = int(time.mktime(date.today().timetuple()))
            row = conn.execute(
                "SELECT SUM(W_Imp_WP_delta) / 1000.0 FROM data_1min WHERE ts >= ?",
                (today_start,)
            ).fetchone()
            if row and row[0] is not None:
                obs.wp_today_kwh = round(row[0], 2)
        except Exception as e:
            LOG.debug(f"wp_today: {e}")
        finally:
            conn.close()

    # ── Sonnenauf-/untergang ─────────────────────────────────

    def _collect_geometry(self, obs: ObsState):
        """Sunrise/Sunset aus solar_forecast (hat die Wetter-API Daten)."""
        try:
            from solar_forecast import SolarForecast
            sf = SolarForecast()
            sr_str, ss_str = sf.get_sunrise_sunset()
            if sr_str and ss_str:
                # "2026-02-22T07:06" → Dezimalstunde
                sr_parts = sr_str.split('T')[1].split(':') if 'T' in sr_str else None
                ss_parts = ss_str.split('T')[1].split(':') if 'T' in ss_str else None
                if sr_parts:
                    obs.sunrise = int(sr_parts[0]) + int(sr_parts[1]) / 60.0
                if ss_parts:
                    obs.sunset = int(ss_parts[0]) + int(ss_parts[1]) / 60.0
                if obs.sunrise and obs.sunset:
                    now_h = datetime.now().hour + datetime.now().minute / 60.0
                    obs.is_day = obs.sunrise <= now_h <= obs.sunset
        except Exception as e:
            LOG.debug(f"geometry: {e}")

            # Fallback: geometry_config.json
            try:
                cfg_path = os.path.join(_PROJECT_ROOT, 'config', 'geometry_config.json')
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r') as f:
                        geo = json.load(f)
                    if obs.sunrise is None:
                        obs.sunrise = geo.get('sunrise_decimal_h')
                    if obs.sunset is None:
                        obs.sunset = geo.get('sunset_decimal_h')
            except Exception:
                pass


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
        self._obs = ObsState()
        self._tier1 = None
        self._actuator = None
        self._engine = None

        # Timing
        self._last_fast = 0
        self._last_strategic = 0
        self._cycle_count = 0

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

        # Actuator (Persist-DB = Haupt-DB für automation_log — dort liest die Web-API)
        self._actuator = Actuator(
            dry_run=self.dry_run,
            persist_db_path=app_config.DB_PATH,
        )

        # Engine
        self._engine = Engine(
            actuator=self._actuator,
            dry_run=self.dry_run,
            matrix_path=DEFAULT_MATRIX_PATH,
        )

        self._running = True
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
                'batt_kapazitaet_kwh': batt.get('kapazitaet_kwh', 10.24),
                'batt_soc_kritisch': cfg.get('soc_grenzen', {}).get('absolutes_minimum', 5),
            }
        except Exception as e:
            LOG.warning(f"Schutz-Config: {e} → Defaults")
            return {}

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

        # 1. Daten sammeln → ObsState
        try:
            self._collector.collect(self._obs)
        except Exception as e:
            LOG.error(f"Collector Fehler: {e}")
            return

        # 2. Tier-1 Schwellenprüfung
        tier1_actions = self._tier1.check(self._obs)

        # 3. ObsState in RAM-DB schreiben
        try:
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

        # 5. Engine fast-Zyklus (alle 60 s)
        if now - self._last_fast >= FAST_INTERVAL:
            try:
                results = self._engine.zyklus('fast')
                if results:
                    LOG.info(f"Engine-fast: {len(results)} Aktion(en)")
                self._last_fast = now
            except Exception as e:
                LOG.error(f"Engine fast-Zyklus: {e}")

        # 6. Engine strategic-Zyklus (alle 15 min)
        if now - self._last_strategic >= STRATEGIC_INTERVAL:
            try:
                results = self._engine.zyklus('strategic')
                if results:
                    LOG.info(f"Engine-strategic: {len(results)} Aktion(en)")
                self._last_strategic = now
            except Exception as e:
                LOG.error(f"Engine strategic-Zyklus: {e}")

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

        from automation.engine.engine import (
            RegelSocSchutz, RegelTempSchutz, RegelAbendEntladerate,
            RegelMorgenSocMin, RegelNachmittagSocMax, RegelZellausgleich,
            RegelForecastPlausi, RegelLaderateDynamisch, RegelWattpilotBattSchutz,
        )

        regeln = [
            RegelSocSchutz(), RegelTempSchutz(), RegelAbendEntladerate(),
            RegelMorgenSocMin(), RegelNachmittagSocMax(), RegelZellausgleich(),
            RegelForecastPlausi(), RegelLaderateDynamisch(), RegelWattpilotBattSchutz(),
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
            except Exception:
                pass

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

    # PID-File schreiben
    PID_FILE.write_text(str(os.getpid()))

    # Signal-Handler
    daemon = AutomationDaemon(dry_run=args.dry_run, once=args.once)

    def _signal_handler(sig, frame):
        LOG.info(f"Signal {sig} → Shutdown")
        daemon._running = False

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    daemon.run()


if __name__ == '__main__':
    main()
