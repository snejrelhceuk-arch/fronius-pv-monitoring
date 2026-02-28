"""
battery_collector.py — Tier-2 Batterie-Datensammlung

Liest Batterie-Daten via Modbus TCP (Model 124) und HTTP API.
  - Modbus (5 s):  SOC, StorCtl_Mod, Lade-/Entladerate, Ladestatus
  - HTTP   (30 s): Zelltemperaturen (Min/Max/Avg) vom BYD BMS

Siehe: doc/BATTERY_COUNTER_DISCOVERY.md
"""

from __future__ import annotations

import logging
import time
from automation.engine.obs_state import ObsState

LOG = logging.getLogger('battery_collector')


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
            from automation.battery_control import (
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
