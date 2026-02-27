"""
aktor_wattpilot.py — WattPilot-Aktor-Plugin für die Automation-Engine

Kapselt WattPilot (EV-Wallbox) Steuerungsbefehle hinter dem AktorBase-Interface.
Aktuell Stub: Loggt Aktionen, führt sie im dry_run-Modus aus.

Unterstützte Kommandos:
  set_max_current  — Maximaler Ladestrom [6–16A]  (6A = Minimum nach IEC 61851)
  pause_charging   — EV-Ladung anhalten
  resume_charging  — EV-Ladung fortsetzen

Benötigt: wattpilot_api.py für echte Steuerung (Phase 2).

Siehe: doc/AUTOMATION_ARCHITEKTUR.md §6 (Aktoren)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

# Projekt-Root in sys.path
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from automation.engine.aktoren.aktor_batterie import AktorBase

LOG = logging.getLogger('aktor.wattpilot')

# Min/Max nach IEC 61851
MIN_CURRENT_A = 6
MAX_CURRENT_A = 16


class AktorWattpilot(AktorBase):
    """WattPilot EV-Wallbox Steuerung.

    Phase 1 (aktuell): Stub — loggt Aktionen, dry_run=True.
    Phase 2 (TODO):    Reale Steuerung via wattpilot_api.py WebSocket.
    """

    name = 'wattpilot'
    MAX_RETRIES = 1
    RETRY_DELAY = 2.0

    _KOMMANDOS = {
        'set_max_current': '_cmd_set_max_current',
        'pause_charging': '_cmd_pause_charging',
        'resume_charging': '_cmd_resume_charging',
    }

    def ausfuehren(self, aktion: dict) -> dict:
        """Führe eine WattPilot-Aktion aus."""
        kommando = aktion.get('kommando', '')
        methode = self._KOMMANDOS.get(kommando)
        if not methode:
            return {'ok': False, 'kommando': kommando,
                    'fehler': f"Unbekanntes Kommando: {kommando}"}

        params = aktion.get('parameter', {})
        LOG.info(f"WattPilot {kommando}: {params} (dry_run={self.dry_run})")

        if self.dry_run:
            return {'ok': True, 'kommando': kommando, 'dry_run': True}

        return getattr(self, methode)(params)

    def verifiziere(self, aktion: dict) -> dict:
        """Read-Back (Phase 2: via wattpilot_api Status-Check)."""
        return {'ok': True, 'verifiziert': False, 'grund': 'Stub — kein Read-Back'}

    # ── Kommando-Implementierungen ───────────────────────────

    def _cmd_set_max_current(self, params: dict) -> dict:
        """Setze maximalen Ladestrom (6–16A)."""
        ampere = params.get('ampere', MAX_CURRENT_A)
        ampere = max(MIN_CURRENT_A, min(MAX_CURRENT_A, int(ampere)))

        # TODO Phase 2: wattpilot_api.set_max_current(ampere)
        LOG.warning(f"WattPilot set_max_current({ampere}A) — STUB, nicht ausgeführt")
        return {'ok': True, 'kommando': 'set_max_current',
                'stub': True, 'ampere': ampere}

    def _cmd_pause_charging(self, params: dict) -> dict:
        """EV-Ladung pausieren."""
        # TODO Phase 2: wattpilot_api.pause()
        LOG.warning("WattPilot pause_charging — STUB, nicht ausgeführt")
        return {'ok': True, 'kommando': 'pause_charging', 'stub': True}

    def _cmd_resume_charging(self, params: dict) -> dict:
        """EV-Ladung fortsetzen."""
        # TODO Phase 2: wattpilot_api.resume()
        LOG.warning("WattPilot resume_charging — STUB, nicht ausgeführt")
        return {'ok': True, 'kommando': 'resume_charging', 'stub': True}
