"""
aktor_waermepumpe.py — Wärmepumpe Dimplex Aktor-Plugin

Kapselt WP-Modbus-Schreibbefehle hinter dem AktorBase-Interface.
Nutzt wp_modbus.write_register() (Whitelist-geschützt).

Unterstützte Kommandos:
  set_ww_soll    — WW-Solltemperatur (Register 5047, 10–85°C)
  set_heiz_soll  — Heizungs-Festwert (Register 5037, 18–60°C)

ABCD: Nur in C (Automation Engine) — D (Hardware) via Modbus RTU.
Siehe: doc/automation/WP_REGISTER.md §6.2, §6.3
"""

from __future__ import annotations

import logging
import time

from automation.engine.aktoren.aktor_batterie import AktorBase

LOG = logging.getLogger('aktor.waermepumpe')


class AktorWaermepumpe(AktorBase):
    """Wärmepumpe Dimplex — Modbus RTU Schreibzugriff."""

    name = 'waermepumpe'

    # Kommando → wp_modbus Register-Name
    _CMD_MAP = {
        'set_ww_soll': 'ww_soll',
        'set_heiz_soll': 'heiz_soll',
    }

    def ausfuehren(self, aktion: dict) -> dict:
        kommando = aktion.get('kommando', '')
        wert = aktion.get('wert')
        grund = aktion.get('grund', '')

        LOG.info(f"WP-Aktor: {kommando} (wert={wert}) — {grund}")

        if self.dry_run:
            LOG.info(f"  [DRY-RUN] Würde ausführen: {kommando}={wert}")
            return {'ok': True, 'kommando': kommando, 'detail': '[DRY-RUN]'}

        reg_name = self._CMD_MAP.get(kommando)
        if not reg_name:
            LOG.error(f"Unbekanntes WP-Kommando: {kommando}")
            return {'ok': False, 'kommando': kommando,
                    'detail': f'Unbekanntes Kommando: {kommando}'}

        ok = self._write_with_retry(reg_name, int(wert))
        return {
            'ok': ok,
            'kommando': kommando,
            'wert': wert,
            'detail': f"{'OK' if ok else 'FEHLER'}: {grund}",
        }

    def _write_with_retry(self, reg_name: str, value: int) -> bool:
        """Schreiben mit Retry (serielle Verbindung kann instabil sein)."""
        from wp_modbus import write_register
        for attempt in range(self.MAX_RETRIES + 1):
            if write_register(reg_name, value):
                return True
            if attempt < self.MAX_RETRIES:
                LOG.warning(f"  WP write {reg_name}={value}: Retry {attempt+1}")
                time.sleep(self.RETRY_DELAY)
        return False

    def verifiziere(self, aktion: dict) -> dict:
        """Read-Back: WW-Soll aus Modbus rücklesen und vergleichen."""
        kommando = aktion.get('kommando', '')
        wert = aktion.get('wert')

        try:
            from wp_modbus import get_wp_status
            # Cache invalidiert durch write_register, force fresh read
            time.sleep(0.5)
            wp = get_wp_status()
            if not wp:
                return {'ok': False, 'grund': 'WP-Modbus nicht lesbar'}

            if kommando == 'set_ww_soll':
                ist = wp.get('ww_soll')
                return {'ok': ist == int(wert), 'soll': wert, 'ist': ist}
            if kommando == 'set_heiz_soll':
                ist = wp.get('heiz_soll')
                return {'ok': ist == int(wert), 'soll': wert, 'ist': ist}
            return {'ok': True, 'grund': f'Keine Rücklese-Verifikation für {kommando}'}
        except Exception as e:
            LOG.warning(f"WP Verifikation fehlgeschlagen: {e}")
            return {'ok': False, 'grund': str(e)}
