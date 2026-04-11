"""
data_collector.py — Tier-2 Sensor-Daten aus Collector-DB

Liest aus der bestehenden Collector-DB (raw_data, data_1min,
wattpilot_readings) und ergänzt per Modbus/HTTP-API:
  - PV-Erzeuger (F1/F2/F3), Netz, Batterie-Leistung
  - StorCtl_Mod, InWRte, OutWRte (Modbus M124 direkt)
  - SOC_MIN/MAX/MODE (Fronius HTTP API)
  - WattPilot Live-Daten + 30-min Avg
  - WP-Verbrauch/PV-Erzeugung heute (Aggregation)
  - Fritz!DECT Heizpatrone-Status

Siehe: doc/SYSTEM_ARCHITECTURE.md §3
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, date
from typing import Optional

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
import config as app_config
from automation.engine.obs_state import ObsState

LOG = logging.getLogger('data_collector')


class DataCollector:
    """Liest Sensor-Daten aus der Collector-DB → ObsState.

    Primär read-only aus Collector-DB (/dev/shm/fronius_data.db).
    Ausnahme: StorCtl_Mod, InWRte, OutWRte werden direkt per Modbus
    gelesen, da der Collector diese Register nicht speichert.
    """

    def __init__(self, db_path: str = None):
        self._db_path = db_path or app_config.DB_PATH
        self._modbus_client = None
        self._modbus_last_poll: float = 0
        # W4: Cache-Variablen als Instanzvariablen (nicht class-level)
        self._soc_config_cache_ts: float = 0
        self._fritzdect_cache_ts: float = 0
        # _fritzdect_device_cache ist als class-Attribut definiert (siehe Methode)

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
        self._collect_battery_modbus(obs)
        self._collect_battery_http_temps(obs)
        self._collect_battery_soc_config(obs)
        self._collect_wattpilot(obs)
        self._collect_battery_settings(obs)
        self._collect_pv_today(obs)
        self._collect_wp_today(obs)
        self._collect_wp_last30h(obs)
        self._collect_fritzdect(obs)
        self._collect_wp_modbus(obs)

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
            # Phasenströme für SLS-Schutz (35A je Phase)
            phase_vals = []
            for attr, col in [('i_l1_netz_a', 'I_L1_Netz'),
                              ('i_l2_netz_a', 'I_L2_Netz'),
                              ('i_l3_netz_a', 'I_L3_Netz')]:
                val = d.get(col)
                if val is not None:
                    setattr(obs, attr, round(val, 2))
                    if val > 0:  # Nur Bezug zählt
                        phase_vals.append(val)
            if phase_vals:
                obs.i_max_netz_a = round(max(phase_vals), 2)

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

            # ── WP 30-min Mittelwert (aus data_1min) ──
            try:
                now_ts = int(time.time())
                wp_avg_row = conn.execute(
                    "SELECT AVG(ABS(P_WP_avg)) FROM data_1min WHERE ts > ?",
                    (now_ts - 1800,)
                ).fetchone()
                if wp_avg_row and wp_avg_row[0] is not None:
                    obs.wp_power_avg30_w = round(wp_avg_row[0], 0)
            except Exception as e:
                LOG.debug(f"WP avg30 query: {e}")

            # ── Hausverbrauch (Bilanz) ──
            verbrauch = obs.pv_total_w - obs.batt_power_w + obs.grid_power_w
            obs.house_load_w = max(0, round(verbrauch, 0))

        except Exception as e:
            LOG.warning(f"raw_data collect: {e}")
        finally:
            conn.close()

    # ── Batterie Modbus (StorCtl_Mod, Lade-/Entladerate) ────

    _modbus_fail_count: int = 0
    _MODBUS_MAX_FAIL_LOG = 5  # Log-Flood-Schutz: nur alle 5 Fehler loggen
    _MODBUS_POLL_INTERVAL = 30  # Sekunden — Steuerregister ändern sich selten
    _BATTERY_HTTP_TEMP_INTERVAL = 30  # Sekunden — Zelltemperaturen ändern sich träge

    def _collect_battery_modbus(self, obs: ObsState):
        """StorCtl_Mod, OutWRte, InWRte direkt per Modbus M124 lesen.

        Rate-Limited: alle 30s (statt bei jedem 10s-Zyklus).
        Steuerregister ändern sich nur durch Schreibzugriffe.
        """
        now = time.time()
        if now - self._modbus_last_poll < self._MODBUS_POLL_INTERVAL:
            return
        self._modbus_last_poll = now
        try:
            from automation.battery_control import (
                ModbusClient, REG,
                read_raw, read_int16_scaled as read_scaled,
            )

            if self._modbus_client is None:
                self._modbus_client = ModbusClient(
                    app_config.INVERTER_IP, app_config.MODBUS_PORT
                )
                if not self._modbus_client.connect():
                    self._modbus_fail_count += 1
                    if self._modbus_fail_count <= 1 or self._modbus_fail_count % self._MODBUS_MAX_FAIL_LOG == 0:
                        LOG.warning(f"Modbus-Verbindung für StorCtl fehlgeschlagen "
                                    f"(Versuch #{self._modbus_fail_count})")
                    self._modbus_client = None
                    return
                time.sleep(0.1)
                self._modbus_fail_count = 0  # Reset nach erfolgreicher Verbindung

            client = self._modbus_client

            # StorCtl_Mod (Bit 0=Charge-Limit, Bit 1=Discharge-Limit)
            storctl = read_raw(client, REG['StorCtl_Mod'])
            if storctl is not None:
                obs.storctl_mod = storctl
                obs.soc_mode = 'manual' if storctl > 0 else 'auto'

            # Lade-/Entladerate
            outwrte, _, _ = read_scaled(client, REG['OutWRte'], REG['InOutWRte_SF'])
            inwrte, _, _ = read_scaled(client, REG['InWRte'], REG['InOutWRte_SF'])
            if outwrte is not None:
                obs.discharge_rate_pct = outwrte
            if inwrte is not None:
                obs.charge_rate_pct = inwrte

        except Exception as e:
            self._modbus_fail_count += 1
            if self._modbus_fail_count <= 1 or self._modbus_fail_count % self._MODBUS_MAX_FAIL_LOG == 0:
                LOG.warning(f"Modbus StorCtl collect: {e} (Fehler #{self._modbus_fail_count})")
            # Socket sauber schließen vor Reset
            if self._modbus_client:
                try:
                    self._modbus_client.close()
                except Exception:
                    pass
            self._modbus_client = None

    # ── SOC_MIN/MAX/MODE aus Fronius HTTP API ────────────────

    def _collect_battery_http_temps(self, obs: ObsState):
        """BYD-Zelltemperaturen über /components/readable → ObsState.

        Nutzt dieselben Rohkanäle wie der frühere BatteryCollector, damit die
        Zelltemperaturen auch im Daemon-Pfad in obs_state verfügbar sind.
        """
        now = time.time()
        if not hasattr(self, '_battery_http_temp_cache_ts'):
            self._battery_http_temp_cache_ts = 0.0

        if now - self._battery_http_temp_cache_ts < self._BATTERY_HTTP_TEMP_INTERVAL:
            return

        try:
            import requests

            url = f'http://{app_config.INVERTER_IP}/components/readable'
            resp = requests.get(url, timeout=3)
            if resp.status_code != 200:
                LOG.debug(f"Batterie-HTTP-Temp: HTTP {resp.status_code} von {url}")
                return

            data = resp.json().get('Body', {}).get('Data', {})
            batt_key = next((key for key in data if 'Storage' in key or 'BYD' in key), None)
            if batt_key is None:
                batt_key = '16580608'

            batt_ch = (data.get(batt_key, {}) or {}).get('channels', {})

            temp_avg = batt_ch.get('BAT_TEMPERATURE_CELL_F64')
            temp_max = batt_ch.get('BAT_TEMPERATURE_CELL_MAX_F64')
            temp_min = batt_ch.get('BAT_TEMPERATURE_CELL_MIN_F64')

            if temp_avg is not None:
                obs.batt_temp_c = round(float(temp_avg), 1)
            if temp_max is not None:
                obs.batt_temp_max_c = round(float(temp_max), 1)
            if temp_min is not None:
                obs.batt_temp_min_c = round(float(temp_min), 1)

            self._battery_http_temp_cache_ts = now

        except Exception as e:
            LOG.debug(f"Batterie-HTTP-Temp: {e}")

    _SOC_CONFIG_INTERVAL = 30

    def _collect_battery_soc_config(self, obs: ObsState):
        """SOC_MIN, SOC_MAX, SOC_MODE aus Fronius Batterie-Config API."""
        now = time.time()
        if now - self._soc_config_cache_ts < self._SOC_CONFIG_INTERVAL:
            return

        try:
            from fronius_api import BatteryConfig
            bc = BatteryConfig()
            values = bc.get_values()

            soc_min_val = values.get('BAT_M0_SOC_MIN')
            soc_max_val = values.get('BAT_M0_SOC_MAX')
            soc_mode_val = values.get('BAT_M0_SOC_MODE')

            if soc_min_val is not None:
                obs.soc_min = int(soc_min_val)
            if soc_max_val is not None:
                obs.soc_max = int(soc_max_val)
            if soc_mode_val is not None:
                obs.soc_mode = str(soc_mode_val).lower()

            self._soc_config_cache_ts = now

        except Exception as e:
            LOG.debug(f"SOC-Config API: {e}")

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

            # ── EV 30-min Mittelwert ──
            ev_avg_row = conn.execute(
                "SELECT AVG(power_w) FROM wattpilot_readings WHERE ts > ?",
                (now - 1800,)
            ).fetchone()
            if ev_avg_row and ev_avg_row[0] is not None:
                obs.ev_power_avg30_w = round(ev_avg_row[0], 0)

        except Exception as e:
            LOG.debug(f"wattpilot collect: {e}")
        finally:
            conn.close()

    # ── Batterie SOC/Mode Settings ───────────────────────────

    def _collect_battery_settings(self, obs: ObsState):
        """SOC_MIN/MAX/Mode Fallback aus battery_scheduler_state.json."""
        cfg_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_scheduler_state.json')
        try:
            if os.path.exists(cfg_path):
                with open(cfg_path, 'r') as f:
                    state = json.load(f)
                if obs.soc_min is None:
                    obs.soc_min = state.get('current_soc_min')
                if obs.soc_max is None:
                    obs.soc_max = state.get('current_soc_max')
        except Exception as e:
            LOG.debug(f"battery_settings: {e}")

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

    def _collect_wp_last30h(self, obs: ObsState):
        """WP-Verbrauch der letzten 30 Stunden (für Pflichtlauf-Prüfung)."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            ts_30h_ago = int(time.time()) - 30 * 3600
            row = conn.execute(
                "SELECT SUM(W_Imp_WP_delta) / 1000.0 FROM data_1min WHERE ts >= ?",
                (ts_30h_ago,)
            ).fetchone()
            if row and row[0] is not None:
                obs.wp_last30h_kwh = round(row[0], 2)
        except Exception as e:
            LOG.debug(f"wp_last30h: {e}")
        finally:
            conn.close()

    # ── Fritz!DECT: Smart-Home-Geräte (Heizpatrone + Klimaanlage) ──

    _FRITZDECT_POLL_INTERVAL = 10  # Sekunden (optimiert für Echtzeiterfassung)
    _fritzdect_device_cache: dict = {}  # { 'ain_norm': info, ... }

    def _collect_fritzdect(self, obs: ObsState):
        """Alle konfigurierten Fritz!DECT-Geräte in EINEM Request erfassen.
        
        Holt Heizpatrone + Klimaanlage mit einem getdevicelistinfos()-Call
        und speichert Leistung + Status in ObsState.
        """
        now = time.time()
        
        # Cache-Check: Alle Daten auf einmal
        if (self._fritzdect_device_cache
                and (now - self._fritzdect_cache_ts) < self._FRITZDECT_POLL_INTERVAL):
            all_devices = self._fritzdect_device_cache
        else:
            all_devices = {}
            try:
                from automation.engine.aktoren.aktor_fritzdect import (
                    _load_fritz_config, _get_session_id, _aha_device_info
                )
                
                cfg = _load_fritz_config()
                host = cfg.get('fritz_ip', '192.168.178.1')
                user = cfg.get('fritz_user', '')
                pw = cfg.get('fritz_password', '')
                polling_interval = cfg.get('polling_interval_s', self._FRITZDECT_POLL_INTERVAL)
                
                # Aktualisiere Interval aus Config (erlaubt Anpassung ohne Code-Änderung)
                self._FRITZDECT_POLL_INTERVAL = polling_interval
                
                if user and pw:
                    sid = _get_session_id(host, user, pw)
                    if sid:
                        # EIN REQUEST für ALLE Geräte (sehr effizient!)
                        geraete_cfg = cfg.get('geraete', [])
                        for gerät in geraete_cfg:
                            if not gerät.get('active', True):
                                continue  # Überspringe inaktive Geräte
                            
                            ain = gerät.get('ain', '').replace(' ', '')
                            if not ain:
                                continue
                            
                            # Benutze _aha_device_info mit AIN — dieser holt aus der Liste
                            # (alternativ könnte man ALLE auf einmal parsen, aber das ist
                            # pro Gerät cleaner)
                            info = _aha_device_info(host, gerät.get('ain', ''), sid)
                            if info:
                                all_devices[ain] = info
                        
                        self._fritzdect_cache_ts = now
                        self._fritzdect_device_cache = all_devices
            except Exception as e:
                LOG.debug(f"Fritz!DECT collect: {e}")
        
        # Iteriere über konfigurierte Geräte und schreibe ins ObsState
        try:
            from automation.engine.aktoren.aktor_fritzdect import _load_fritz_config
            cfg = _load_fritz_config()
            geraete_cfg = cfg.get('geraete', [])
            
            for gerät in geraete_cfg:
                if not gerät.get('active', True):
                    continue
                
                dev_id = gerät.get('id', '').lower()
                ain = gerät.get('ain', '').replace(' ', '')
                info = all_devices.get(ain)
                
                if not info:
                    continue
                
                # State: '0' | '1'
                state_1 = str(info.get('state', '')).strip() == '1'
                power_w = round((info.get('power_mw') or 0) / 1000.0, 1)
                
                # Mapping zu ObsState (pro Gerät)
                if dev_id == 'heizpatrone':
                    obs.heizpatrone_aktiv = state_1
                    obs.heizpatrone_power_w = power_w
                    # energy_wh → today_kwh (wird später aus Aggregation gefüllt)
                
                elif dev_id == 'fussbodenheizung':
                    obs.fbh_aktiv = state_1

                elif dev_id == 'klimaanlage':
                    obs.klima_aktiv = state_1
                    obs.klima_power_w = power_w
                    # energy_wh → today_kwh (wird später aus Aggregation gefüllt)
                    # Temperatur falls vorhanden (Fritz!DECT liefert <temperature> in XML)
                    temp_c = None
                    if info and 'temperature' in info:
                        try:
                            temp_c = float(info['temperature'])
                        except Exception:
                            pass
                    obs.klima_temp_c = temp_c
                
                # In DB schreiben für Web-API (fritzdect_readings)
                self._save_fritzdect_reading(
                    int(now), dev_id, gerät.get('ain', ''),
                    info.get('name', ''), info
                )
        
        except Exception as e:
            LOG.debug(f"Fritz!DECT mapping: {e}")

    def _save_fritzdect_reading(self, ts: int, device_id: str, ain: str,
                                name: str, info: dict):
        """Speichere Fritz!DECT-Reading in fritzdect_readings (tmpfs-DB).
        
        Ermöglicht der Web-API, aktuelle Werte direkt aus DB zu lesen,
        ohne über obs_state gehen zu müssen.
        """
        try:
            import sqlite3
            db_path = '/dev/shm/fronius_data.db'
            power_mw = info.get('power_mw')
            power_w = (power_mw / 1000.0) if power_mw is not None else None
            state = int(info.get('state', 0)) if info.get('state') else None
            energy_wh = info.get('energy_wh')
            
            conn = sqlite3.connect(db_path, timeout=2)
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO fritzdect_readings
                    (ts, device_id, ain, name, power_mw, power_w, state, energy_total_wh)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (ts, device_id, ain, name, power_mw, power_w, state, energy_wh))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            LOG.debug(f"Fritz!DECT DB-Write ({device_id}): {e}")

    # ── Wärmepumpe Dimplex: Modbus-Temperaturen ─────────────

    _WP_MODBUS_INTERVAL = 30  # Sekunden (serielle Schnittstelle schonen)

    def _collect_wp_modbus(self, obs: ObsState):
        """WP-Temperaturen via Modbus RTU → ObsState.

        ABCD: Hardwarezugriff (/dev/ttyACM0) gehört in C (Automation),
        nicht in B (Web). Daher sammelt der DataCollector die Werte,
        und B liest sie aus obs_state.
        """
        now = time.time()
        if not hasattr(self, '_wp_modbus_cache_ts'):
            self._wp_modbus_cache_ts = 0

        if now - self._wp_modbus_cache_ts < self._WP_MODBUS_INTERVAL:
            return

        try:
            from wp_modbus import get_wp_status
            wp = get_wp_status()
            if not wp:
                return

            if wp.get('ww_ist') is not None:
                obs.ww_temp_c = wp['ww_ist']
            if wp.get('vorlauf') is not None:
                obs.wp_vorlauf_c = wp['vorlauf']
            if wp.get('ruecklauf') is not None:
                obs.wp_ruecklauf_c = wp['ruecklauf']
            if wp.get('ruecklauf_soll') is not None:
                obs.wp_ruecklauf_soll_c = wp['ruecklauf_soll']
            if wp.get('quelle_ein') is not None:
                obs.wp_quelle_ein_c = wp['quelle_ein']
            if wp.get('quelle_aus') is not None:
                obs.wp_quelle_aus_c = wp['quelle_aus']
            if wp.get('ww_soll') is not None:
                obs.wp_ww_soll_c = wp['ww_soll']
            if wp.get('heiz_soll') is not None:
                obs.wp_heiz_soll_c = wp['heiz_soll']
            if wp.get('aussen_temp') is not None:
                obs.wp_aussen_temp_c = wp['aussen_temp']

            self._wp_modbus_cache_ts = now

        except Exception as e:
            LOG.debug(f"WP-Modbus collect: {e}")
