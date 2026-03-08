"""
aktor_wattpilot.py — WattPilot-Aktor-Plugin für die Automation-Engine

Kapselt WattPilot (EV-Wallbox) Steuerungsbefehle hinter dem AktorBase-Interface.
Steuert Ladestrom (amp), Phasenmodus (psm) und Force-State (frc) per WebSocket.

Unterstützte Kommandos:
  set_max_current  — Ladestrom setzen [6–32A]  (6A = Minimum nach IEC 61851)
  set_current      — Alias für set_max_current (proportionale Reduktion)
  pause_charging   — EV-Ladung anhalten (frc=1)
  resume_charging  — EV-Ladung fortsetzen (frc=2)
  set_phase_mode   — Phasenmodus setzen (1=1-phasig, 2=3-phasig)
  set_power        — Leistungslimit (Tier-1 Netzüberlast)
  reduce_current   — Proportionale Stromreduktion (SLS-Schutz)

Benötigt: wattpilot_api.py mit set_value() (WebSocket setValue).

Siehe: doc/automation/SCHUTZREGELN.md SR-SLS-01
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from automation.engine.aktoren.aktor_batterie import AktorBase

LOG = logging.getLogger('aktor.wattpilot')

# Min/Max nach IEC 61851 und WattPilot Go 22J Hardware
MIN_CURRENT_A = 6
MAX_CURRENT_A = 32   # WattPilot Go 22J: 3×32A


def _get_client():
    """Lazy-Import des WattpilotClient (vermeidet Zirkular-Import)."""
    from wattpilot_api import WattpilotClient
    return WattpilotClient()


class AktorWattpilot(AktorBase):
    """WattPilot EV-Wallbox Steuerung via WebSocket setValue API.

    Steuert:
      - amp (Ladestrom 6–32A)
      - frc (Force State: 0=neutral, 1=aus, 2=ein)
      - psm (Phasenmodus: 1=1-phasig, 2=3-phasig)
    """

    name = 'wattpilot'
    MAX_RETRIES = 1
    RETRY_DELAY = 2.0

    _KOMMANDOS = {
        'set_max_current': '_cmd_set_max_current',
        'set_current':     '_cmd_set_max_current',   # Alias
        'set_power':       '_cmd_set_power',
        'reduce_current':  '_cmd_reduce_current',
        'reduce_power':    '_cmd_reduce_power',
        'pause_charging':  '_cmd_pause_charging',
        'resume_charging': '_cmd_resume_charging',
        'set_phase_mode':  '_cmd_set_phase_mode',
    }

    def ausfuehren(self, aktion: dict) -> dict:
        """Führe eine WattPilot-Aktion aus."""
        kommando = aktion.get('kommando', '')
        methode = self._KOMMANDOS.get(kommando)
        if not methode:
            return {'ok': False, 'kommando': kommando,
                    'detail': f"Unbekanntes Kommando: {kommando}"}

        # Interface-Kompatibilität: 'wert' (Engine) → 'parameter' (intern)
        params = aktion.get('parameter', {})
        if not params and 'wert' in aktion:
            params = {'wert': aktion['wert']}
        LOG.info(f"WattPilot {kommando}: {params} (dry_run={self.dry_run})")

        if self.dry_run:
            return {'ok': True, 'kommando': kommando, 'dry_run': True,
                    'detail': '[DRY-RUN]'}

        return getattr(self, methode)(params)

    def verifiziere(self, aktion: dict) -> dict:
        """Read-Back: Aktuellen Status lesen und mit Soll vergleichen."""
        kommando = aktion.get('kommando', '')
        try:
            client = _get_client()
            status = client.get_status_summary()
            if not status.get('online'):
                return {'ok': False, 'verifiziert': False,
                        'grund': f'WattPilot offline: {status.get("error_message")}'}

            # Je nach Kommando passenden Wert prüfen
            if kommando in ('set_max_current', 'set_current', 'set_power',
                            'reduce_current', 'reduce_power'):
                ist = status.get('charge_current_a', 0)
                soll = aktion.get('parameter', {}).get('ampere',
                       aktion.get('wert', ist))
                return {'ok': True, 'verifiziert': True,
                        'ist': ist, 'soll': soll,
                        'match': abs(ist - soll) <= 1}

            if kommando == 'pause_charging':
                frc = status.get('force_state', 0)
                return {'ok': True, 'verifiziert': True,
                        'ist': frc, 'soll': 1, 'match': frc == 1}

            if kommando == 'resume_charging':
                frc = status.get('force_state', 0)
                return {'ok': True, 'verifiziert': True,
                        'ist': frc, 'soll': 0, 'match': frc in (0, 2)}

            if kommando == 'set_phase_mode':
                psm = status.get('phase_mode_raw', 0)
                soll = aktion.get('parameter', {}).get('psm', psm)
                return {'ok': True, 'verifiziert': True,
                        'ist': psm, 'soll': soll, 'match': psm == soll}

            return {'ok': True, 'verifiziert': False,
                    'grund': f'Kein Read-Back für {kommando}'}

        except Exception as e:
            return {'ok': False, 'verifiziert': False, 'grund': str(e)}

    # ── Kommando-Implementierungen ───────────────────────────

    def _cmd_set_max_current(self, params: dict) -> dict:
        """Setze maximalen Ladestrom (6–32A)."""
        ampere = params.get('ampere', params.get('wert', MAX_CURRENT_A))
        ampere = max(MIN_CURRENT_A, min(MAX_CURRENT_A, int(ampere)))

        try:
            client = _get_client()
            result = client.set_value('amp', ampere)
            if result.get('ok'):
                LOG.info(f"WattPilot amp={ampere}A gesetzt: {result.get('detail')}")
            else:
                LOG.error(f"WattPilot amp={ampere}A FEHLER: {result.get('detail')}")
            result['kommando'] = 'set_max_current'
            result['ampere'] = ampere
            return result
        except Exception as e:
            LOG.error(f"WattPilot set_max_current({ampere}A) Exception: {e}")
            return {'ok': False, 'kommando': 'set_max_current',
                    'ampere': ampere, 'detail': str(e)}

    def _cmd_pause_charging(self, params: dict) -> dict:
        """EV-Ladung pausieren (frc=1)."""
        try:
            client = _get_client()
            result = client.set_value('frc', 1)
            LOG.info(f"WattPilot pause (frc=1): {result.get('detail')}")
            result['kommando'] = 'pause_charging'
            return result
        except Exception as e:
            LOG.error(f"WattPilot pause_charging Exception: {e}")
            return {'ok': False, 'kommando': 'pause_charging', 'detail': str(e)}

    def _cmd_resume_charging(self, params: dict) -> dict:
        """EV-Ladung fortsetzen (frc=0 = neutral, Wattpilot entscheidet selbst)."""
        try:
            client = _get_client()
            result = client.set_value('frc', 0)
            LOG.info(f"WattPilot resume (frc=0): {result.get('detail')}")
            result['kommando'] = 'resume_charging'
            return result
        except Exception as e:
            LOG.error(f"WattPilot resume_charging Exception: {e}")
            return {'ok': False, 'kommando': 'resume_charging', 'detail': str(e)}

    def _cmd_set_phase_mode(self, params: dict) -> dict:
        """Phasenmodus setzen (1=1-phasig, 2=3-phasig)."""
        psm = params.get('psm', params.get('wert', 2))
        psm = max(1, min(2, int(psm)))
        try:
            client = _get_client()
            result = client.set_value('psm', psm)
            LOG.info(f"WattPilot psm={psm}: {result.get('detail')}")
            result['kommando'] = 'set_phase_mode'
            result['psm'] = psm
            return result
        except Exception as e:
            LOG.error(f"WattPilot set_phase_mode({psm}) Exception: {e}")
            return {'ok': False, 'kommando': 'set_phase_mode',
                    'psm': psm, 'detail': str(e)}

    def _cmd_set_power(self, params: dict) -> dict:
        """Leistungslimit setzen (Tier-1 Netzüberlast).

        Konvertiert Watt in Ampere (3-phasig 230V) und begrenzt auf 6–32A.
        """
        watt = params.get('wert', 1400)
        # 3-phasig: A = W / (3 × 230V)
        ampere = max(MIN_CURRENT_A, min(MAX_CURRENT_A, int(watt / 690)))
        return self._cmd_set_max_current({'ampere': ampere})

    def _cmd_reduce_current(self, params: dict) -> dict:
        """Proportionale Stromreduktion (SLS-Schutz).

        Parameter:
          reduce_by_a — Um wie viel Ampere reduzieren
          ampere      — Alternativ: Absoluter Zielwert
        """
        ampere = params.get('ampere')
        if ampere is None:
            reduce_by = params.get('reduce_by_a', 0)
            # Aktuellen Strom lesen, dann reduzieren
            try:
                client = _get_client()
                status = client.get_status_summary()
                current_a = status.get('charge_current_a', 16)
                ampere = max(MIN_CURRENT_A, int(current_a - reduce_by))
            except Exception as e:
                LOG.warning(f"WattPilot Status-Lesen fehlgeschlagen: {e} → Fallback 6A")
                ampere = MIN_CURRENT_A

        ampere = max(MIN_CURRENT_A, min(MAX_CURRENT_A, int(ampere)))
        result = self._cmd_set_max_current({'ampere': ampere})
        result['kommando'] = 'reduce_current'
        return result

    def _cmd_reduce_power(self, params: dict) -> dict:
        """Leistung reduzieren (Legacy-Kompatibilität / Fallback).

        Reduziert auf Minimum (6A).
        """
        return self._cmd_set_max_current({'ampere': MIN_CURRENT_A})
