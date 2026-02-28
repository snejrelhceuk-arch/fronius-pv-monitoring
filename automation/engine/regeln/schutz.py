"""
schutz.py — Sicherheitsregeln (P1, fast-Zyklus)

RegelSocSchutz   — Harte SOC-Grenzen: Stop bei <5%, Drosseln bei <10%
RegelTempSchutz  — Graduelle Laderate-Reduktion nach Zelltemperatur

Siehe: doc/SCHUTZREGELN.md SR-BAT-01, SR-BAT-02
"""

from __future__ import annotations

import logging
from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht, get_regelkreis,
)

LOG = logging.getLogger('engine')


class RegelSocSchutz(Regel):
    """Harte SOC-Grenzen: Stop bei <5%, Drosseln bei <10%.

    Parametermatrix: regelkreise.soc_schutz
    """

    name = 'soc_schutz'
    regelkreis = 'soc_schutz'
    engine_zyklus = 'fast'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis) or obs.batt_soc_pct is None:
            return 0
        stop = get_param(matrix, self.regelkreis, 'stop_entladung_unter_pct', 5)
        drossel = get_param(matrix, self.regelkreis, 'drosselung_unter_pct', 10)
        if obs.batt_soc_pct < stop:
            return get_score_gewicht(matrix, self.regelkreis)  # 90
        if obs.batt_soc_pct < drossel:
            return int(get_score_gewicht(matrix, self.regelkreis) * 0.7)
        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        stop = get_param(matrix, self.regelkreis, 'stop_entladung_unter_pct', 5)
        drossel = get_param(matrix, self.regelkreis, 'drosselung_unter_pct', 10)
        drossel_wert = get_regelkreis(matrix, self.regelkreis).get(
            'parameter', {}).get('drosselung_unter_pct', {}).get('aktor_wert', 50)

        soc = obs.batt_soc_pct
        if soc is None:
            return []  # Kein SOC verfügbar → keine Aktion

        if soc < stop:
            return [{
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'stop_discharge',
                'grund': f'SOC-Schutz: {soc:.1f}% < {stop}% → Entladung STOP',
            }]
        return [{
            'tier': 2, 'aktor': 'batterie',
            'kommando': 'set_discharge_rate',
            'wert': drossel_wert,
            'grund': f'SOC-Schutz: {obs.batt_soc_pct:.1f}% < {drossel}% → Entladerate {drossel_wert}%',
        }]


class RegelTempSchutz(Regel):
    """Graduelle Laderate-Reduktion nach Zelltemperatur.

    Parametermatrix: regelkreise.temp_schutz
    """

    name = 'temp_schutz'
    regelkreis = 'temp_schutz'
    engine_zyklus = 'fast'

    # Temperatur-Stufen (fest an die Parameter-Keys gebunden)
    STUFEN = [(40, 'stufe_40c_pct'), (35, 'stufe_35c_pct'),
              (30, 'stufe_30c_pct'), (25, 'stufe_25c_pct')]

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis) or obs.batt_temp_max_c is None:
            return 0
        for temp, key in self.STUFEN:
            if obs.batt_temp_max_c >= temp:
                pct = get_param(matrix, self.regelkreis, key, 100)
                if pct < 100:
                    return get_score_gewicht(matrix, self.regelkreis)
                break
        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        if obs.batt_temp_max_c is None:
            return []  # Keine Temperatur verfügbar → keine Aktion
        for temp, key in self.STUFEN:
            if obs.batt_temp_max_c >= temp:
                pct = get_param(matrix, self.regelkreis, key, 100)
                return [{
                    'tier': 2, 'aktor': 'batterie',
                    'kommando': 'set_charge_rate',
                    'wert': pct,
                    'grund': f'Temp-Schutz: {obs.batt_temp_max_c:.1f}°C ≥ {temp}°C → Laderate {pct}%',
                }]
        return []
