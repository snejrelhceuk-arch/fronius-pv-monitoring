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
import sys
import time
from datetime import datetime, date
from typing import Optional

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

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
        self._collect_battery_soc_config(obs)
        self._collect_wattpilot(obs)
        self._collect_battery_settings(obs)
        self._collect_pv_today(obs)
        self._collect_wp_today(obs)
        self._collect_fritzdect(obs)

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

    def _collect_battery_modbus(self, obs: ObsState):
        """StorCtl_Mod, OutWRte, InWRte direkt per Modbus M124 lesen."""
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
                    LOG.warning("Modbus-Verbindung für StorCtl fehlgeschlagen")
                    self._modbus_client = None
                    return
                time.sleep(0.1)

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
            LOG.warning(f"Modbus StorCtl collect: {e}")
            self._modbus_client = None

    # ── SOC_MIN/MAX/MODE aus Fronius HTTP API ────────────────

    _soc_config_cache_ts: float = 0
    _SOC_CONFIG_INTERVAL = 30

    def _collect_battery_soc_config(self, obs: ObsState):
        """SOC_MIN, SOC_MAX, SOC_MODE aus Fronius Batterie-Config API."""
        now = time.time()
        if now - DataCollector._soc_config_cache_ts < self._SOC_CONFIG_INTERVAL:
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

            DataCollector._soc_config_cache_ts = now

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

    # ── Fritz!DECT: Heizpatrone Live-Status ──────────────────

    _fritzdect_cache_ts: float = 0
    _fritzdect_cache_data: dict = None
    _FRITZDECT_POLL_INTERVAL = 60

    def _collect_fritzdect(self, obs: ObsState):
        """HP-Status von Fritz!Box → obs.heizpatrone_aktiv."""
        now = time.time()
        if (self._fritzdect_cache_data is not None
                and (now - self._fritzdect_cache_ts) < self._FRITZDECT_POLL_INTERVAL):
            info = self._fritzdect_cache_data
        else:
            info = None
            try:
                from automation.engine.aktoren.aktor_fritzdect import (
                    _load_fritz_config, _get_session_id, _aha_device_info
                )
                cfg = _load_fritz_config()
                host = cfg.get('fritz_ip', '192.168.178.1')
                ain = cfg.get('ain', '')
                user = cfg.get('fritz_user', '')
                pw = cfg.get('fritz_password', '')
                if ain and user and pw:
                    sid = _get_session_id(host, user, pw)
                    if sid:
                        info = _aha_device_info(host, ain, sid)
            except Exception as e:
                LOG.debug(f"Fritz!DECT collect: {e}")

            DataCollector._fritzdect_cache_ts = now
            DataCollector._fritzdect_cache_data = info

        if info and info.get('state') is not None:
            obs.heizpatrone_aktiv = str(info['state']).strip() == '1'
