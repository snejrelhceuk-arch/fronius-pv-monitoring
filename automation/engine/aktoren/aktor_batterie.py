"""
aktor_batterie.py — Batterie-Aktor-Plugin für die Automation-Engine

Kapselt Batterie-Steuerungsbefehle (SOC-Grenzen, SOC-Mode, Netzladung)
hinter einem einheitlichen Plugin-Interface.

Eigenständig: Importiert battery_control.py und fronius_api.py aus dem
Projekt-Root, keine direkte Abhängigkeit zum laufenden battery_scheduler.

HINWEIS (2026-03-07): Laderate-/Entladerate-Kommandos (set_charge_rate,
set_discharge_rate, hold, auto, stop_*) wurden entfernt. Der GEN24 12.0
DC-DC-Wandler begrenzt den Batteriestrom auf ~22 A (≈9,5 kW).
Software-Ratenlimits via InWRte/OutWRte/StorCtl_Mod waren wirkungslos.
SOC_MIN/SOC_MAX via Fronius HTTP-API sind das korrekte Steuerungsinstrument.

Siehe: doc/AUTOMATION_ARCHITEKTUR.md §6 (Aktoren)
"""

from __future__ import annotations

import logging
import time

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
      set_soc_min         — SOC_MIN via HTTP API
      set_soc_max         — SOC_MAX via HTTP API
      set_soc_mode        — SOC_MODE ('auto'/'manual') via HTTP API
      grid_charge         — Netzladung ein/aus via Modbus

    Entfernt (2026-03-07) — GEN24 HW-Limit macht SW-Ratenlimits wirkungslos:
      set_charge_rate, set_discharge_rate, hold, auto, stop_discharge, stop_charge
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
                from automation.battery_control import ModbusClient, IP_ADDRESS, PORT
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
                # Explizite Prüfung: True oder truthy (aber nicht None)
                if result is True or (result is not None and result):
                    return True
                if result is None:
                    LOG.warning(f"  {op_name}: Ergebnis None — als Fehler gewertet")
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

        # Entfernte Kommandos: set_charge_rate, set_discharge_rate, hold,
        # auto, stop_discharge, stop_charge (GEN24 HW-Limit, 2026-03-07)
        handler = {
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

    # ── Entfernt (2026-03-07) ─────────────────────────────────────
    # _cmd_set_charge_rate, _cmd_set_discharge_rate, _cmd_hold,
    # _cmd_auto, _cmd_stop_discharge, _cmd_stop_charge
    # Grund: GEN24 12.0 DC-DC-Wandler begrenzt Batteriestrom auf ~22 A.
    # Software-Ratenlimits via InWRte/OutWRte/StorCtl_Mod wirkungslos.
    # ─────────────────────────────────────────────────────────────

    # ── HTTP-API-Kommandos ───────────────────────────────────

    def _ensure_manual_mode(self) -> bool:
        """SOC_MODE-Guard für SOC_MIN/SOC_MAX-Schreibvorgänge.

        Hintergrund (2026-04-26): Bei Fronius `SOC_MODE='auto'` sind die
        Hardware-Grenzen 5–100 % firmware-fix; HTTP-Schreibvorgänge auf
        SOC_MIN/SOC_MAX werden ohne Fehler akzeptiert, aber NICHT wirksam.
        Ohne diesen Guard schlägt die Verifikation immer fehl, ohne dass
        klar ist warum.

        Verhalten:
          - mode unbekannt / API-Fehler  → True (best effort, kein Block)
          - mode == 'manual'             → True (kein Eingriff nötig)
          - mode == 'auto'               → versucht set_soc_mode='manual';
                                            Erfolg → True, sonst False.

        Returns: True wenn der nachfolgende SOC-Schreibvorgang sinnvoll ist.
        """
        api = self._get_http_api()
        if not api:
            # Kein API → nichts zu tun, der eigentliche Schreibvorgang
            # wird denselben Fehler erneut sehen.
            return True
        try:
            api._cache_time = 0
            mode = str(api.get_values().get('BAT_M0_SOC_MODE') or '').lower()
        except Exception as e:
            LOG.warning(f"  SOC-Mode-Guard: Mode nicht lesbar ({e}) — "
                        f"führe Schreibvorgang trotzdem aus")
            return True
        if mode != 'auto':
            return True
        LOG.warning("  SOC-Mode-Guard: SOC_MODE=auto erkannt → "
                    "schalte zuerst auf 'manual' (sonst sind "
                    "SOC_MIN/SOC_MAX-Schreibvorgänge wirkungslos)")
        ok = self._retry(
            "SOC_MODE='manual' (auto-fix)", self._get_http_api, '_http_api',
            lambda a: self._write_ok(a.set_soc_mode('manual')),
        )
        if not ok:
            LOG.error("  SOC-Mode-Guard: Wechsel auf 'manual' fehlgeschlagen — "
                      "SOC_MIN/SOC_MAX-Schreibvorgang wird voraussichtlich "
                      "wirkungslos bleiben.")
        return ok

    @staticmethod
    def _write_ok(result) -> bool:
        """Erfolgsbewertung eines Fronius-`BatteryConfig.write()`-Returns.

        Vorher hat `_retry` jedes None als Fehler gewertet. `write()` liefert
        aber für No-Ops (Soll == Ist) ein leeres Ergebnis und ist damit kein
        HTTP-Fehler, sondern ein erfolgreich-aufgelöster Schreibwunsch.
        Dieses Helper-Verfahren erkennt:
          - None  → Fehler (echter API-Aufruf-Fehler)
          - Result mit .noop == True → Erfolg (kein HTTP nötig)
          - Result mit status_code in {200, 204} und ohne writeFailure → Erfolg
          - alles andere → Fehler
        """
        if result is None:
            return False
        if getattr(result, 'noop', False):
            return True
        status = getattr(result, 'status_code', None)
        if status not in (200, 204):
            return False
        try:
            body = result.json() if getattr(result, 'text', '') else {}
        except Exception:
            body = {}
        if body.get('writeFailure') or body.get('validationErrors'):
            return False
        return True

    def _cmd_set_soc_min(self, value) -> bool:
        """SOC_MIN via HTTP API."""
        if not self._ensure_manual_mode():
            return False
        return self._retry(
            f'SOC_MIN={value}', self._get_http_api, '_http_api',
            lambda api: self._write_ok(api.set_soc_min(value))
        )

    def _cmd_set_soc_max(self, value) -> bool:
        """SOC_MAX via HTTP API."""
        if not self._ensure_manual_mode():
            return False
        return self._retry(
            f'SOC_MAX={value}', self._get_http_api, '_http_api',
            lambda api: self._write_ok(api.set_soc_max(value))
        )

    def _cmd_set_soc_mode(self, mode) -> bool:
        """SOC_MODE via HTTP API ('auto'/'manual')."""
        return self._retry(
            f'SOC_MODE={mode}', self._get_http_api, '_http_api',
            lambda api: self._write_ok(api.set_soc_mode(mode))
        )

    def _cmd_grid_charge(self, enabled) -> bool:
        """Netzladung via Modbus."""
        from automation.battery_control import set_grid_charge
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

        # Mapping Kommando → Fronius-API-Schlüssel
        param_key = {
            'set_soc_min': 'BAT_M0_SOC_MIN',
            'set_soc_max': 'BAT_M0_SOC_MAX',
        }.get(kommando)

        if not param_key:
            # Kommandos ohne Read-Back (grid_charge, set_soc_mode)
            return {'ok': True, 'grund': f'Keine Verifikation für {kommando}'}

        try:
            time.sleep(0.5)
            api = self._get_http_api()
            if not api:
                return {'ok': False, 'grund': 'HTTP-API nicht verfügbar'}

            # Cache invalidieren für frischen Read-Back
            api._cache_time = 0
            values = api.get_values()
            ist = values.get(param_key)

            if ist is None:
                return {'ok': False, 'grund': f'{param_key} nicht in API-Antwort'}

            # Toleranz: Integer-Vergleich (SOC-Werte sind ganzzahlig)
            ok = int(ist) == int(wert)
            if not ok:
                LOG.warning(f"Verifikation {kommando}: SOLL={wert}, IST={ist}")
            else:
                LOG.debug(f"Verifikation {kommando}: OK (IST={ist})")

            return {'ok': ok, 'ist': ist, 'soll': wert}

        except Exception as e:
            LOG.warning(f"Verifikation {kommando} fehlgeschlagen: {e}")
            return {'ok': False, 'grund': str(e)}

    # ── Cleanup ──────────────────────────────────────────────

    def close(self):
        if self._modbus_client:
            self._modbus_client.close()
            self._modbus_client = None
        self._http_api = None
