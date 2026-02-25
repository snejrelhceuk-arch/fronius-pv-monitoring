"""
aktor_batterie.py — Batterie-Aktor-Plugin für die Automation-Engine

Kapselt alle Batterie-Steuerungsbefehle (Laderate, Entladerate, Hold,
Auto, SOC-Grenzen, Netzladung) hinter einem einheitlichen Plugin-Interface.

Eigenständig: Importiert battery_control.py und fronius_api.py aus dem
Projekt-Root, keine direkte Abhängigkeit zum laufenden battery_scheduler.

Siehe: doc/AUTOMATION_ARCHITEKTUR.md §6 (Aktoren)
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Optional

# Projekt-Root in sys.path
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

LOG = logging.getLogger('aktor.batterie')

# ═════════════════════════════════════════════════════════════
# Aktor-Interface (Base für alle Plugins)
# ═════════════════════════════════════════════════════════════

class AktorBase:
    """Basisklasse für alle Aktor-Plugins."""

    name: str = 'unbekannt'
    MAX_RETRIES: int = 2
    RETRY_DELAY: float = 1.5

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def ausfuehren(self, aktion: dict) -> dict:
        """Führe eine Aktion aus. Gibt Ergebnis-dict zurück."""
        raise NotImplementedError

    def verifiziere(self, aktion: dict) -> dict:
        """Read-Back: Prüfe ob die Aktion tatsächlich wirkt."""
        raise NotImplementedError


# ═════════════════════════════════════════════════════════════
# Batterie-Aktor
# ═════════════════════════════════════════════════════════════

class AktorBatterie(AktorBase):
    """Batterie-Steuerung via Modbus TCP (Model 124) + Fronius HTTP API.

    Unterstützte Kommandos:
      set_charge_rate     — Laderate [0-100%]
      set_discharge_rate  — Entladerate [0-100%]
      hold                — Batterie halten (0% Lade+Entlade)
      auto                — Automatik (StorCtl_Mod=0)
      set_soc_min         — SOC_MIN via HTTP API
      set_soc_max         — SOC_MAX via HTTP API
      set_soc_mode        — SOC_MODE ('auto'/'manual') via HTTP API
      stop_discharge      — Sofort: Entladerate=0%
      stop_charge         — Sofort: Laderate=0%
      grid_charge         — Netzladung ein/aus
    """

    name = 'batterie'

    def __init__(self, dry_run: bool = False):
        super().__init__(dry_run=dry_run)
        self._modbus_client = None
        self._http_api = None

    # ── Lazy Inits ───────────────────────────────────────────

    def _get_modbus(self):
        """Modbus-Client mit Lazy-Init."""
        if self._modbus_client is None:
            try:
                from battery_control import ModbusClient, IP_ADDRESS, PORT
                client = ModbusClient(IP_ADDRESS, PORT)
                if client.connect():
                    self._modbus_client = client
                    time.sleep(0.1)
                else:
                    LOG.error("Modbus-Verbindung fehlgeschlagen")
            except Exception as e:
                LOG.error(f"Modbus nicht verfügbar: {e}")
        return self._modbus_client

    def _get_http_api(self):
        """Fronius HTTP API mit Lazy-Init."""
        if self._http_api is None:
            try:
                from fronius_api import BatteryConfig
                self._http_api = BatteryConfig()
            except Exception as e:
                LOG.error(f"Fronius API nicht verfügbar: {e}")
        return self._http_api

    # ── Retry-Logik (übernommen aus battery_scheduler) ───────

    def _retry(self, op_name: str, get_fn, reset_attr: str, exec_fn) -> bool:
        """Generische Retry-Logik für Hardware-Zugriffe."""
        for attempt in range(self.MAX_RETRIES + 1):
            resource = get_fn()
            if not resource:
                if attempt < self.MAX_RETRIES:
                    LOG.warning(f"  {op_name}: nicht verbunden — Retry {attempt+1}")
                    setattr(self, reset_attr, None)
                    time.sleep(self.RETRY_DELAY)
                    continue
                return False
            try:
                result = exec_fn(resource)
                if result is None or result is True or result:
                    return True
                if attempt < self.MAX_RETRIES:
                    LOG.warning(f"  {op_name}: fehlgeschlagen — Retry {attempt+1}")
                    setattr(self, reset_attr, None)
                    time.sleep(self.RETRY_DELAY)
            except Exception as e:
                LOG.error(f"  {op_name}: {e}")
                if attempt < self.MAX_RETRIES:
                    setattr(self, reset_attr, None)
                    time.sleep(self.RETRY_DELAY)
        return False

    # ── Haupt-Dispatcher ─────────────────────────────────────

    def ausfuehren(self, aktion: dict) -> dict:
        """Führe eine Batterie-Aktion aus.

        Args:
            aktion: dict mit mindestens 'kommando', optional 'wert', 'grund'

        Returns:
            dict mit 'ok': bool, 'kommando': str, 'detail': str
        """
        kommando = aktion.get('kommando', '')
        wert = aktion.get('wert')
        grund = aktion.get('grund', '')

        LOG.info(f"Batterie-Aktor: {kommando} (wert={wert}) — {grund}")

        if self.dry_run:
            LOG.info(f"  [DRY-RUN] Würde ausführen: {kommando}={wert}")
            return {'ok': True, 'kommando': kommando, 'detail': '[DRY-RUN]'}

        handler = {
            'set_charge_rate': self._cmd_set_charge_rate,
            'set_discharge_rate': self._cmd_set_discharge_rate,
            'hold': self._cmd_hold,
            'auto': self._cmd_auto,
            'stop_discharge': self._cmd_stop_discharge,
            'stop_charge': self._cmd_stop_charge,
            'set_soc_min': self._cmd_set_soc_min,
            'set_soc_max': self._cmd_set_soc_max,
            'set_soc_mode': self._cmd_set_soc_mode,
            'grid_charge': self._cmd_grid_charge,
        }.get(kommando)

        if not handler:
            LOG.error(f"Unbekanntes Kommando: {kommando}")
            return {'ok': False, 'kommando': kommando, 'detail': 'Unbekanntes Kommando'}

        ok = handler(wert)
        return {
            'ok': ok,
            'kommando': kommando,
            'wert': wert,
            'detail': f"{'OK' if ok else 'FEHLER'}: {grund}",
        }

    # ── Modbus-Kommandos ─────────────────────────────────────

    def _cmd_set_charge_rate(self, percent) -> bool:
        """Laderate setzen [0-100%]."""
        from battery_control import set_charge_rate
        return self._retry(
            f'Laderate={percent}%', self._get_modbus, '_modbus_client',
            lambda c: set_charge_rate(c, percent)
        )

    def _cmd_set_discharge_rate(self, percent) -> bool:
        """Entladerate setzen [0-100%]."""
        from battery_control import set_discharge_rate
        return self._retry(
            f'Entladerate={percent}%', self._get_modbus, '_modbus_client',
            lambda c: set_discharge_rate(c, percent)
        )

    def _cmd_hold(self, _=None) -> bool:
        """Batterie halten."""
        from battery_control import hold_battery
        return self._retry(
            'Hold', self._get_modbus, '_modbus_client',
            lambda c: hold_battery(c)
        )

    def _cmd_auto(self, _=None) -> bool:
        """Automatik (StorCtl_Mod=0)."""
        from battery_control import auto_battery
        return self._retry(
            'Auto', self._get_modbus, '_modbus_client',
            lambda c: auto_battery(c)
        )

    def _cmd_stop_discharge(self, _=None) -> bool:
        """Tier-1 Sofort-Aktion: Entladerate=0%."""
        from battery_control import set_discharge_rate
        return self._retry(
            'STOP-Entladung', self._get_modbus, '_modbus_client',
            lambda c: set_discharge_rate(c, 0)
        )

    def _cmd_stop_charge(self, _=None) -> bool:
        """Tier-1 Sofort-Aktion: Laderate=0%."""
        from battery_control import set_charge_rate
        return self._retry(
            'STOP-Ladung', self._get_modbus, '_modbus_client',
            lambda c: set_charge_rate(c, 0)
        )

    # ── HTTP-API-Kommandos ───────────────────────────────────

    def _cmd_set_soc_min(self, value) -> bool:
        """SOC_MIN via HTTP API."""
        return self._retry(
            f'SOC_MIN={value}', self._get_http_api, '_http_api',
            lambda api: api.set_soc_min(value)
        )

    def _cmd_set_soc_max(self, value) -> bool:
        """SOC_MAX via HTTP API."""
        return self._retry(
            f'SOC_MAX={value}', self._get_http_api, '_http_api',
            lambda api: api.set_soc_max(value)
        )

    def _cmd_set_soc_mode(self, mode) -> bool:
        """SOC_MODE via HTTP API ('auto'/'manual')."""
        return self._retry(
            f'SOC_MODE={mode}', self._get_http_api, '_http_api',
            lambda api: api.set_soc_mode(mode)
        )

    def _cmd_grid_charge(self, enabled) -> bool:
        """Netzladung via Modbus."""
        from battery_control import set_grid_charge
        val = bool(enabled) if not isinstance(enabled, bool) else enabled
        return self._retry(
            f'Netzladung={"EIN" if val else "AUS"}',
            self._get_modbus, '_modbus_client',
            lambda c: set_grid_charge(c, val)
        )

    # ── Read-Back Verifikation ───────────────────────────────

    def verifiziere(self, aktion: dict) -> dict:
        """Lese aktuelle Werte zurück und prüfe ob Aktion wirkt.

        Returns:
            dict mit 'ok': bool, 'ist': <tatsächl. Wert>, 'soll': <Zielwert>
        """
        kommando = aktion.get('kommando', '')
        wert = aktion.get('wert')
        client = self._get_modbus()

        if not client:
            return {'ok': False, 'grund': 'Modbus nicht verbunden'}

        try:
            from battery_control import read_raw, read_int16_scaled, REG

            if kommando in ('set_charge_rate', 'stop_charge'):
                soll = wert if wert is not None else 0
                ist, _, _ = read_int16_scaled(client, REG['InWRte'], REG['InOutWRte_SF'])
                ok = ist is not None and abs(ist - soll) < 2
                return {'ok': ok, 'ist': ist, 'soll': soll, 'register': 'InWRte'}

            elif kommando in ('set_discharge_rate', 'stop_discharge'):
                soll = wert if wert is not None else 0
                ist, _, _ = read_int16_scaled(client, REG['OutWRte'], REG['InOutWRte_SF'])
                ok = ist is not None and abs(ist - soll) < 2
                return {'ok': ok, 'ist': ist, 'soll': soll, 'register': 'OutWRte'}

            elif kommando == 'hold':
                storctl = read_raw(client, REG['StorCtl_Mod'])
                ok = storctl is not None and (storctl & 0x03) == 0x03
                return {'ok': ok, 'ist': storctl, 'soll': 3, 'register': 'StorCtl_Mod'}

            elif kommando == 'auto':
                storctl = read_raw(client, REG['StorCtl_Mod'])
                ok = storctl is not None and storctl == 0
                return {'ok': ok, 'ist': storctl, 'soll': 0, 'register': 'StorCtl_Mod'}

            else:
                return {'ok': True, 'grund': f'Keine Verifikation für {kommando}'}

        except Exception as e:
            LOG.error(f"Verifikation fehlgeschlagen: {e}")
            return {'ok': False, 'grund': str(e)}

    # ── Cleanup ──────────────────────────────────────────────

    def close(self):
        if self._modbus_client:
            self._modbus_client.close()
            self._modbus_client = None
        self._http_api = None
