"""
observer.py — 3-Tier Beobachtungs-Service

Eigenständiger Prozess (systemd-Service), der alle Datenquellen nach
abgestuften Prioritäten beobachtet und den ObsState aufbaut.

Tiers:
  1 — INTERRUPT: Sicherheitskritisch (< 1 s), Sofort-Aktionen
  2 — DAEMON:    Steuerungsrelevant (5–30 s Polling)
  3 — CRON:      Träge Daten (1–15 min)

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
from typing import Optional, Callable

# Projekt-Root in sys.path, damit wir bestehende Module importieren können
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from automation.engine.obs_state import (
    ObsState, init_ram_db, write_obs_state, read_obs_state,
    write_heartbeat, load_param_matrix, RAM_DB_PATH,
)

LOG = logging.getLogger('observer')


# ═════════════════════════════════════════════════════════════
# Tier-1: Schwellenprüfung mit Sofort-Aktion
# ═════════════════════════════════════════════════════════════

class Tier1Checker:
    """Deterministisch, nicht verhandelbar, nicht deaktivierbar.

    Prüft bei jedem ObsState-Update ob Alarmschwellen überschritten sind.
    Setzt Flags im ObsState UND triggert ggf. Sofort-Aktionen via Actuator.
    """

    def __init__(self, actuator=None, schutz_cfg: dict = None):
        self.actuator = actuator
        self.cfg = schutz_cfg or {}
        # Batterie-spezifisch
        self._batt_temp_warn = self.cfg.get('batt_temp_warn_c', 40)
        self._batt_temp_alarm = self.cfg.get('batt_temp_alarm_c', 45)
        self._batt_temp_reduce_c_rate = self.cfg.get('batt_temp_reduce_c_rate', 0.3)
        self._batt_kapazitaet_kwh = self.cfg.get('batt_kapazitaet_kwh', 10.24)
        self._batt_soc_kritisch = self.cfg.get('batt_soc_kritisch', 5)
        self._netz_ueberlast_warn_w = self.cfg.get('netz_ueberlast_warn_w', 24000)
        self._netz_ueberlast_alarm_w = self.cfg.get('netz_ueberlast_alarm_w', 26000)
        # Zustand für Hysterese
        self._batt_temp_limited = False

    def check(self, obs: ObsState) -> list[dict]:
        """Prüfe alle Tier-1-Schwellen. Gibt Liste der ausgelösten Aktionen zurück."""
        actions = []

        # ── Batterie-Temperatur ──────────────────────────────
        actions.extend(self._check_batt_temp(obs))

        # ── Batterie SOC kritisch ────────────────────────────
        if obs.batt_soc_pct is not None and obs.batt_soc_pct < self._batt_soc_kritisch:
            obs.alarm_batt_kritisch = True
            actions.append({
                'tier': 1,
                'aktor': 'batterie',
                'kommando': 'stop_discharge',
                'grund': f'SOC kritisch: {obs.batt_soc_pct:.1f}% < {self._batt_soc_kritisch}%',
            })
        else:
            obs.alarm_batt_kritisch = False

        # ── Netz-Überlast ────────────────────────────────────
        if obs.grid_power_w is not None:
            if obs.grid_power_w > self._netz_ueberlast_alarm_w:
                obs.alarm_ueberlast = True
                actions.append({
                    'tier': 1,
                    'aktor': 'wattpilot',
                    'kommando': 'set_power',
                    'wert': 1400,  # Minimum
                    'grund': f'Netz-Überlast ALARM: {obs.grid_power_w:.0f}W > {self._netz_ueberlast_alarm_w}W',
                })
            elif obs.grid_power_w > self._netz_ueberlast_warn_w:
                obs.alarm_ueberlast = True
                actions.append({
                    'tier': 1,
                    'aktor': 'wattpilot',
                    'kommando': 'reduce_power',
                    'grund': f'Netz-Überlast WARNUNG: {obs.grid_power_w:.0f}W > {self._netz_ueberlast_warn_w}W',
                })
            else:
                obs.alarm_ueberlast = False

        return actions

    def _check_batt_temp(self, obs: ObsState) -> list[dict]:
        """Batterie-Temperatur-Schutzlogik mit Hysterese.

        Ab 40°C: Ladeleistung auf 0.3C reduzieren (= ~3 kW bei 10.24 kWh)
        Ab 45°C: Ladung komplett stoppen
        Hysterese: Erst bei < 38°C wieder normalisieren
        """
        actions = []
        temp = obs.batt_temp_max_c  # Wärmste Zelle ist maßgeblich

        if temp is None:
            # Kein Temperaturwert → keine Entscheidung, Flag beibehalten
            return actions

        if temp >= self._batt_temp_alarm:
            # ── ALARM: Ladung stoppen ────────────────────────
            obs.alarm_batt_temp = True
            self._batt_temp_limited = True
            actions.append({
                'tier': 1,
                'aktor': 'batterie',
                'kommando': 'set_charge_rate',
                'wert': 0,
                'grund': f'Batterie-Temp ALARM: {temp:.1f}°C ≥ {self._batt_temp_alarm}°C → Ladung STOP',
            })
            LOG.critical(f"TIER-1 ALARM: Batterie-Temp {temp:.1f}°C ≥ {self._batt_temp_alarm}°C → Ladung STOP")

        elif temp >= self._batt_temp_warn:
            # ── WARNUNG: Ladeleistung auf 0.3C reduzieren ────
            obs.alarm_batt_temp = True
            self._batt_temp_limited = True
            # 0.3C bei 10.24 kWh ≈ 3.07 kW → ~30% von WChaMax (10.24 kW)
            reduce_pct = int(self._batt_temp_reduce_c_rate /
                             (self._batt_kapazitaet_kwh / self._batt_kapazitaet_kwh) * 100)
            # Genauer: 0.3C = 0.3 × 10.24 kW = 3.072 kW, WChaMax = 10.24 kW → 30%
            reduce_pct = int(self._batt_temp_reduce_c_rate * 100)  # 0.3C → 30%
            actions.append({
                'tier': 1,
                'aktor': 'batterie',
                'kommando': 'set_charge_rate',
                'wert': reduce_pct,
                'grund': (f'Batterie-Temp WARNUNG: {temp:.1f}°C ≥ {self._batt_temp_warn}°C '
                          f'→ Ladeleistung auf {self._batt_temp_reduce_c_rate}C '
                          f'({reduce_pct}% ≈ {self._batt_kapazitaet_kwh * self._batt_temp_reduce_c_rate:.1f} kW)'),
            })
            LOG.warning(f"TIER-1: Batterie-Temp {temp:.1f}°C ≥ {self._batt_temp_warn}°C "
                        f"→ Laderate auf {reduce_pct}%")

        elif self._batt_temp_limited and temp < (self._batt_temp_warn - 2):
            # ── HYSTERESE: Normalisieren bei < 38°C ──────────
            obs.alarm_batt_temp = False
            self._batt_temp_limited = False
            actions.append({
                'tier': 1,
                'aktor': 'batterie',
                'kommando': 'set_charge_rate',
                'wert': 100,
                'grund': f'Batterie-Temp normalisiert: {temp:.1f}°C < {self._batt_temp_warn - 2}°C → Laderate 100%',
            })
            LOG.info(f"TIER-1: Batterie-Temp normalisiert: {temp:.1f}°C → Laderate zurück auf 100%")

        else:
            obs.alarm_batt_temp = False

        return actions


# ═════════════════════════════════════════════════════════════
# Tier-2 Collectors: Daemon-Poll (5–30 s)
# ═════════════════════════════════════════════════════════════

class BatteryCollector:
    """Liest Batterie-Daten via Modbus TCP (Model 124) und HTTP API.

    Tier 2 (5 s Modbus) + Tier 2 (30 s HTTP für Temperaturen).
    """

    def __init__(self, inverter_ip: str, modbus_port: int = 502):
        self.inverter_ip = inverter_ip
        self.modbus_port = modbus_port
        self._modbus_client = None
        self._last_http_fetch = 0
        self._http_interval = 30  # Sekunden

    def collect_modbus(self, obs: ObsState):
        """Modbus M124 Register lesen → ObsState aktualisieren."""
        try:
            from battery_control import (
                ModbusClient, REG,
                read_raw, read_int16_scaled as read_scaled,
            )

            if self._modbus_client is None:
                self._modbus_client = ModbusClient(self.inverter_ip, self.modbus_port)
                if not self._modbus_client.connect():
                    LOG.error("Modbus-Verbindung fehlgeschlagen")
                    self._modbus_client = None
                    return
                time.sleep(0.1)

            client = self._modbus_client

            # SOC
            soc, _, _ = read_scaled(client, REG['ChaState'], REG['ChaState_SF'])
            if soc is not None:
                obs.batt_soc_pct = soc

            # StorCtl_Mod
            storctl = read_raw(client, REG['StorCtl_Mod'])
            if storctl is not None:
                obs.storctl_mod = storctl

            # Lade-/Entladerate
            outwrte, _, _ = read_scaled(client, REG['OutWRte'], REG['InOutWRte_SF'])
            inwrte, _, _ = read_scaled(client, REG['InWRte'], REG['InOutWRte_SF'])
            if outwrte is not None:
                obs.discharge_rate_pct = outwrte
            if inwrte is not None:
                obs.charge_rate_pct = inwrte

            # Ladestatus
            cha_st = read_raw(client, REG['ChaSt'])
            if cha_st is not None:
                obs.cha_state = cha_st

        except Exception as e:
            LOG.error(f"Modbus-Collect Fehler: {e}")
            self._modbus_client = None

    def collect_http(self, obs: ObsState):
        """Fronius HTTP API für Temperaturen + BMS-Daten.

        Wird nur alle _http_interval Sekunden aufgerufen (Rate-Limiting).
        Quelle: http://{ip}/components/readable — Device 16580608 (BYD Battery)
        """
        now = time.time()
        if now - self._last_http_fetch < self._http_interval:
            return
        self._last_http_fetch = now

        try:
            import requests
            url = f'http://{self.inverter_ip}/components/readable'
            resp = requests.get(url, timeout=3)
            if resp.status_code != 200:
                LOG.warning(f"HTTP {resp.status_code} von {url}")
                return

            data = resp.json()
            batt_ch = (data.get('Body', {}).get('Data', {})
                       .get('16580608', {}).get('channels', {}))

            t = batt_ch.get('BAT_TEMPERATURE_CELL_F64')
            if t is not None:
                obs.batt_temp_c = round(t, 1)
            t = batt_ch.get('BAT_TEMPERATURE_CELL_MAX_F64')
            if t is not None:
                obs.batt_temp_max_c = round(t, 1)
            t = batt_ch.get('BAT_TEMPERATURE_CELL_MIN_F64')
            if t is not None:
                obs.batt_temp_min_c = round(t, 1)

        except Exception as e:
            LOG.warning(f"HTTP-Collect Fehler: {e}")

    def close(self):
        if self._modbus_client:
            self._modbus_client.close()
            self._modbus_client = None


# ═════════════════════════════════════════════════════════════
# Tier-3 Collector: Forecast (gezielt getriggert)
# ═════════════════════════════════════════════════════════════

class ForecastCollector:
    """Holt Solar-Prognose zu definierten Tageszeitpunkten.

    Trigger-Zeitpunkte:
      ① Sunrise        → Morgen-Entscheidung (SOC_MIN öffnen?)
      ② 10:00          → Tagesverlauf-Update (SOC_MAX anpassen)
      ③ 14:00          → Abend-Reserve-Planung
      + Initialer Fetch beim Observer-Start
      + Fallback alle 6h, falls Trigger verpasst

    Schreibt Ergebnisse in ObsState UND in forecast_daily (für
    Dashboard + battery_scheduler Kompatibilität).
    """

    # Feste Trigger-Uhrzeiten (Dezimalstunden) — sunrise wird dynamisch gesetzt
    FIXED_TRIGGERS = [10.0, 14.0]
    FALLBACK_INTERVAL_S = 6 * 3600  # 6h

    def __init__(self):
        self._sf = None               # SolarForecast Instanz (lazy)
        self._last_fetch_ts = 0       # Unix-Timestamp letzter Fetch
        self._sunrise_h = None        # Heutige Sunrise-Stunde (Dezimal)
        self._sunset_h = None
        self._triggers_today = set()  # Welche Trigger heute schon gelaufen
        self._last_date = None        # Für Tageswechsel-Erkennung
        self._hourly_profile = None   # Letztes hourly_profile (für _get_pv_at_hour)
        self._power_hourly = None     # Letzte power_hourly

    def _ensure_sf(self):
        """SolarForecast Singleton — lazy init."""
        if self._sf is None:
            from solar_forecast import SolarForecast
            self._sf = SolarForecast()
        return self._sf

    def collect(self, obs: ObsState):
        """Prüfe ob ein Fetch-Trigger fällig ist und aktualisiere ObsState.

        Wird vom Observer im Tier-3-Loop aufgerufen (z.B. alle 30s prüfen,
        aber nur bei Trigger tatsächlich fetchen).
        """
        now = datetime.now()
        now_h = now.hour + now.minute / 60.0
        today_str = now.strftime('%Y-%m-%d')

        # ── Tageswechsel: Trigger-Set zurücksetzen ──────────
        if self._last_date != today_str:
            self._triggers_today = set()
            self._last_date = today_str
            self._sunrise_h = None  # Sunrise neu berechnen

        # ── Sunrise bestimmen (1× pro Tag) ──────────────────
        if self._sunrise_h is None:
            self._fetch_sunrise_sunset(obs)

        # ── Trigger-Prüfung ─────────────────────────────────
        should_fetch = False
        trigger_name = None

        # Initialer Fetch (noch nie geholt)
        if self._last_fetch_ts == 0:
            should_fetch = True
            trigger_name = 'startup'

        # Sunrise-Trigger
        elif (self._sunrise_h is not None
              and now_h >= self._sunrise_h
              and 'sunrise' not in self._triggers_today):
            should_fetch = True
            trigger_name = 'sunrise'

        # Feste Trigger (10:00, 14:00)
        else:
            for trig_h in self.FIXED_TRIGGERS:
                key = f'fixed_{trig_h:.0f}'
                if now_h >= trig_h and key not in self._triggers_today:
                    should_fetch = True
                    trigger_name = key
                    break

        # Fallback: Alle 6h
        if (not should_fetch
                and time.time() - self._last_fetch_ts > self.FALLBACK_INTERVAL_S):
            should_fetch = True
            trigger_name = 'fallback_6h'

        if not should_fetch:
            return

        # ── Fetch durchführen ───────────────────────────────
        LOG.info(f"Tier-3 Forecast-Fetch ausgelöst: {trigger_name} "
                 f"(Uhrzeit {now.strftime('%H:%M')})")

        try:
            self._do_fetch(obs)
            if trigger_name:
                self._triggers_today.add(trigger_name)
            self._last_fetch_ts = time.time()
            LOG.info(f"  Forecast OK: {obs.forecast_kwh:.1f} kWh, "
                     f"PV@SR+1h={obs.pv_at_sunrise_1h_w or '?'}W, "
                     f"Qualität={obs.forecast_quality}")
        except Exception as e:
            LOG.error(f"Forecast-Fetch fehlgeschlagen: {e}", exc_info=True)

    def _fetch_sunrise_sunset(self, obs: ObsState):
        """Sunrise/Sunset aus SolarForecast holen und in ObsState setzen."""
        try:
            sf = self._ensure_sf()
            strategy = sf.get_strategy_inputs()
            if strategy.get('valid'):
                self._sunrise_h = strategy.get('sunrise_hour', 7.0)
                self._sunset_h = strategy.get('sunset_hour', 17.0)
                obs.sunrise = self._sunrise_h
                obs.sunset = self._sunset_h
                now_h = datetime.now().hour + datetime.now().minute / 60.0
                obs.is_day = self._sunrise_h <= now_h <= self._sunset_h
                LOG.info(f"  Sunrise={self._sunrise_h:.2f}h, "
                         f"Sunset={self._sunset_h:.2f}h")
        except Exception as e:
            LOG.warning(f"Sunrise/Sunset nicht ermittelbar: {e}")

    def _do_fetch(self, obs: ObsState):
        """Vollständiger Forecast-Fetch → ObsState + forecast_daily DB."""
        sf = self._ensure_sf()
        # Force frische Daten (Cache invalidieren)
        sf._forecast_data = None

        strategy = sf.get_strategy_inputs()
        hourly = sf.get_hourly_forecast()
        power_hourly = sf.get_hourly_power_forecast()

        # ── ObsState aktualisieren ──────────────────────────
        if strategy.get('valid'):
            obs.forecast_kwh = strategy.get('expected_kwh', 0)
            obs.cloud_avg_pct = strategy.get('cloud_cover_avg', 50)
            obs.forecast_quality = strategy.get('quality')
            obs.sunrise = strategy.get('sunrise_hour')
            obs.sunset = strategy.get('sunset_hour')
            self._sunrise_h = obs.sunrise
            self._sunset_h = obs.sunset

            now_h = datetime.now().hour + datetime.now().minute / 60.0
            obs.is_day = (self._sunrise_h or 7) <= now_h <= (self._sunset_h or 17)

        obs.forecast_ts = datetime.now().isoformat()

        # ── PV@Sunrise+1h berechnen ─────────────────────────
        self._hourly_profile = None
        self._power_hourly = power_hourly
        if self._sunrise_h is not None:
            target_h = self._sunrise_h + 1.0
            pv_at_sr1 = self._get_pv_at_hour(hourly, power_hourly, target_h)
            obs.pv_at_sunrise_1h_w = pv_at_sr1

        # ── forecast_daily in DB schreiben (Kompatibilität) ─
        self._store_forecast_daily(sf, hourly, power_hourly)

    def _get_pv_at_hour(self, hourly, power_hourly, target_hour):
        """PV-Leistung [W] zu bestimmter Stunde aus Forecast-Daten.

        Identische Logik wie battery_scheduler._get_pv_at_hour().
        """
        # ★ Bevorzugt: hourly (GHI-basiert, Feld 'ghi' → PV-Schätzung)
        #   Aber hourly enthält 'shortwave_radiation', kein 'p'.
        #   Wir brauchen die aufbereiteten datapoints mit Feld 'p' aus
        #   dem forecast_daily hourly_profile.
        #   → power_hourly (Geometrie-Engine) hat 'total_ac' pro Stunde.

        # Versuch 1: power_hourly (stündlich, Feld 'total_ac')
        if power_hourly:
            best_ac = None
            best_diff = 999
            for h in power_hourly:
                hr = h.get('hour')
                if hr is None:
                    t = h.get('time', '')
                    try:
                        hr = int(t[11:13]) + int(t[14:16]) / 60.0
                    except (ValueError, IndexError):
                        continue
                diff = abs(float(hr) - target_hour)
                if diff < best_diff:
                    best_diff = diff
                    best_ac = h.get('total_ac', 0)
            if best_ac is not None and best_diff < 0.75:
                return best_ac

        # Versuch 2: hourly (Open-Meteo roh, Feld 'shortwave_radiation')
        # → Grobe Schätzung: GHI [W/m²] × 37.59 kWp × 0.15 Eff ≈ PV [W]
        if hourly:
            best_ghi = None
            best_diff = 999
            for h in hourly:
                t = h.get('time', '')
                try:
                    hr = int(t[11:13]) + int(t[14:16]) / 60.0
                except (ValueError, IndexError):
                    continue
                diff = abs(hr - target_hour)
                if diff < best_diff:
                    best_diff = diff
                    best_ghi = h.get('shortwave_radiation', 0)
            if best_ghi is not None and best_diff < 0.75:
                # Grobe Umrechnung: GHI → PV (vereinfacht)
                return best_ghi * 37.59 * 0.15

        return None

    def _store_forecast_daily(self, sf, hourly, power_hourly):
        """Schreibe aufbereitete Prognose in forecast_daily (Haupt-DB).

        Damit Dashboard und battery_scheduler aktuelle Daten haben.
        Schreibt direkt per SQL — keine Abhängigkeit von routes/.
        """
        try:
            import sqlite3 as _sql
            import config as app_config

            today_str = datetime.now().strftime('%Y-%m-%d')
            day_fc = sf.get_day_forecast()
            if not day_fc:
                return

            # hourly_profile bauen (5-Min oder stündlich, JSON mit ts/p/cc/temp/ghi)
            hourly_json = None
            if power_hourly:
                import json as _json
                points = []
                for p in power_hourly:
                    try:
                        hour_dt = datetime.strptime(p['time'], '%Y-%m-%dT%H:%M')
                        ts = int(time.mktime(hour_dt.timetuple()))
                    except (ValueError, KeyError):
                        continue
                    points.append({
                        'ts': ts,
                        'p': round(p.get('total_ac', 0), 1),
                        'cc': p.get('cloud_cover', 0) or 0,
                        'temp': p.get('temp', 0) or 0,
                        'ghi': p.get('ghi', 0) or 0,
                    })
                if points:
                    hourly_json = _json.dumps(points, separators=(',', ':'))

            # Cloud-Durchschnitt
            cloud_avg = None
            if hourly:
                clouds = [h.get('cloud_cover', 0) for h in hourly
                          if h.get('cloud_cover') is not None]
                if clouds:
                    cloud_avg = round(sum(clouds) / len(clouds), 1)

            conn = _sql.connect(app_config.DB_PATH, timeout=5.0)
            conn.execute("""
                INSERT OR REPLACE INTO forecast_daily
                (date, expected_kwh, quality, weather_text, weather_code,
                 sunrise, sunset, sunshine_hours, temp_min, temp_max,
                 cloud_cover_avg, precipitation_mm,
                 hourly_profile, forecast_method, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                today_str,
                day_fc.get('expected_kwh'),
                day_fc.get('quality'),
                day_fc.get('weather_text'),
                day_fc.get('weather_code'),
                day_fc.get('sunrise'),
                day_fc.get('sunset'),
                day_fc.get('sunshine_hours'),
                day_fc.get('temp_min'),
                day_fc.get('temp_max'),
                cloud_avg,
                day_fc.get('precipitation_mm'),
                hourly_json,
                'geometry' if power_hourly else 'ghi_factor',
                time.time(),
            ))
            conn.commit()
            conn.close()
            LOG.info(f"  forecast_daily geschrieben: {today_str} "
                     f"→ {day_fc.get('expected_kwh', '?')} kWh")
        except Exception as e:
            LOG.warning(f"forecast_daily Schreib-Fehler: {e}")


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
                'batt_kapazitaet_kwh': batt.get('kapazitaet_kwh', 10.24),
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
