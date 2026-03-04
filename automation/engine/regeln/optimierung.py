"""
optimierung.py — Optimierungsregeln (P2-P3, mixed Zyklen)

RegelAbendEntladerate   — Entladerate nach Tageszeit (fast)
RegelZellausgleich      — Monatlicher BYD-Zellbalancing (strategic)
RegelForecastPlausi     — Prognose an Realität anpassen (strategic)
RegelLaderateDynamisch  — Laderate je nach WP/PV/SOC steuern (fast)

Siehe: doc/BATTERIE_STRATEGIEN.md, doc/PARAMETER_MATRIZEN.md
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, date
from typing import Optional

from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.regeln.soc_extern import soc_extern_tracker
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht,
)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

LOG = logging.getLogger('engine')


# ═════════════════════════════════════════════════════════════
# ABEND-ENTLADERATE (P2 — Steuerung, fast)
# ═════════════════════════════════════════════════════════════

class RegelAbendEntladerate(Regel):
    """Entladerate nach Tageszeit begrenzen.

    Abend: 29%, Nacht: 10%, Tag: auto.
    SOC < kritisch → Hold.

    Parametermatrix: regelkreise.abend_entladerate
    """

    name = 'abend_entladerate'
    regelkreis = 'abend_entladerate'
    engine_zyklus = 'fast'

    def _get_phase(self, matrix: dict) -> tuple[Optional[str], Optional[int]]:
        """Aktuelle Tagesphase bestimmen."""
        now = datetime.now()
        hr = now.hour + now.minute / 60.0

        abend_ab = get_param(matrix, self.regelkreis, 'abend_start_h', 15)
        abend_bis = get_param(matrix, self.regelkreis, 'abend_ende_h', 0)
        nacht_ab = get_param(matrix, self.regelkreis, 'nacht_start_h', 0)
        nacht_bis = get_param(matrix, self.regelkreis, 'nacht_ende_h', 6)
        abend_rate = get_param(matrix, self.regelkreis, 'abend_rate_pct', 29)
        nacht_rate = get_param(matrix, self.regelkreis, 'nacht_rate_pct', 10)

        if hr >= abend_ab or (abend_bis > 0 and hr < abend_bis):
            return 'abend', abend_rate
        if nacht_ab <= hr < nacht_bis:
            return 'nacht', nacht_rate
        return None, None

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        kritisch = get_param(matrix, self.regelkreis, 'kritisch_soc_pct', 10)
        if obs.batt_soc_pct is not None and obs.batt_soc_pct < kritisch:
            return get_score_gewicht(matrix, self.regelkreis)

        phase, rate = self._get_phase(matrix)
        if phase is not None:
            return get_score_gewicht(matrix, self.regelkreis)

        if obs.storctl_mod is not None and obs.storctl_mod != 0:
            return int(get_score_gewicht(matrix, self.regelkreis) * 0.5)

        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        kritisch = get_param(matrix, self.regelkreis, 'kritisch_soc_pct', 10)

        if obs.batt_soc_pct is not None and obs.batt_soc_pct < kritisch:
            return [{
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'hold',
                'grund': f'SOC-Notbremse: {obs.batt_soc_pct:.1f}% < {kritisch}% → Hold',
            }]

        phase, rate = self._get_phase(matrix)
        if phase is not None:
            if obs.discharge_rate_pct is not None and abs(obs.discharge_rate_pct - rate) < 3:
                return []
            return [{
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_discharge_rate',
                'wert': rate,
                'grund': f'{phase.upper()}-Phase: Entladerate auf {rate}%',
            }]

        if obs.storctl_mod is not None and obs.storctl_mod == 0:
            return []
        return [{
            'tier': 2, 'aktor': 'batterie',
            'kommando': 'auto',
            'grund': 'TAG-Phase: Entladeraten-Limits aufheben',
        }]


# ═════════════════════════════════════════════════════════════
# ZELLAUSGLEICH (P3 — Wartung, strategic)
# ═════════════════════════════════════════════════════════════

class RegelZellausgleich(Regel):
    """Monatlicher Vollzyklus für BYD-Zellbalancing.

    Parametermatrix: regelkreise.zellausgleich
    """

    name = 'zellausgleich'
    regelkreis = 'zellausgleich'
    engine_zyklus = 'strategic'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0
        if obs.forecast_kwh is None:
            return 0

        # ── SOC-Extern-Toleranz ──
        soc_extern_tracker.aktualisiere(obs, matrix)
        if soc_extern_tracker.ist_toleriert(matrix):
            verbleibend = soc_extern_tracker.verbleibend_s(matrix)
            LOG.debug(f'{self.name}: SOC extern geändert '
                      f'({soc_extern_tracker.extern_grund}) '
                      f'→ toleriert ({verbleibend}s verbleibend)')
            return 0

        letzter = self._letzter_ausgleich()
        if letzter:
            try:
                last_date = datetime.strptime(letzter, '%Y-%m-%d').date()
                heute = date.today()
                if last_date.year == heute.year and last_date.month == heute.month:
                    return 0
            except (ValueError, TypeError):
                pass

        min_pv = get_param(matrix, self.regelkreis, 'min_prognose_kwh', 50.0)
        frueh = get_param(matrix, self.regelkreis, 'fruehester_tag', 1)
        spaet = get_param(matrix, self.regelkreis, 'spaetester_tag', 28)
        tag = date.today().day

        if tag < frueh or tag > spaet:
            return 0

        if obs.forecast_kwh >= min_pv:
            return get_score_gewicht(matrix, self.regelkreis)

        notfall = get_param(matrix, self.regelkreis, 'notfall_min_prognose_kwh', 25.0)
        if tag > spaet - 5 and obs.forecast_kwh >= notfall:
            return int(get_score_gewicht(matrix, self.regelkreis) * 0.8)

        return 0

    @staticmethod
    def _letzter_ausgleich() -> Optional[str]:
        """Lese letzten Zellausgleich aus State/Config."""
        state_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_scheduler_state.json')
        try:
            with open(state_path) as f:
                state = json.load(f)
            val = state.get('last_balancing')
            if val:
                return val
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

        cfg_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_control.json')
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            return cfg.get('zellausgleich', {}).get('letzter_ausgleich')
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        soc_min = get_param(matrix, self.regelkreis, 'soc_min_waehrend_pct', 5)
        soc_max = get_param(matrix, self.regelkreis, 'soc_max_waehrend_pct', 100)
        aktionen = [
            {
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_min', 'wert': soc_min,
                'grund': f'Zellausgleich: SOC_MIN → {soc_min}%',
            },
            {
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_max', 'wert': soc_max,
                'grund': f'Zellausgleich: SOC_MAX → {soc_max}% (Vollladung)',
            },
        ]
        # Engine-Aktionen registrieren (Extern-Erkennung)
        for a in aktionen:
            soc_extern_tracker.registriere_aktion(a.get('kommando', ''), a.get('wert'))
        return aktionen


# ═════════════════════════════════════════════════════════════
# FORECAST-PLAUSIBILISIERUNG (P2 — Steuerung, strategic)
# ═════════════════════════════════════════════════════════════

class RegelForecastPlausi(Regel):
    """PV-Prognose an Realität anpassen.

    Vergleicht bisherige Erzeugung mit dem erwarteten Anteil.
    Bei > 30% Abweichung → SOC-Strategie anpassen.

    Parametermatrix: regelkreise.forecast_plausibilisierung
    """

    name = 'forecast_plausi'
    regelkreis = 'forecast_plausibilisierung'
    engine_zyklus = 'strategic'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        if obs.pv_vs_forecast_pct is None or obs.forecast_rest_kwh is None:
            return 0

        # ── SOC-Extern-Toleranz ──
        soc_extern_tracker.aktualisiere(obs, matrix)
        if soc_extern_tracker.ist_toleriert(matrix):
            verbleibend = soc_extern_tracker.verbleibend_s(matrix)
            LOG.debug(f'{self.name}: SOC extern geändert '
                      f'({soc_extern_tracker.extern_grund}) '
                      f'→ toleriert ({verbleibend}s verbleibend)')
            return 0

        min_h = get_param(matrix, self.regelkreis, 'min_betriebsstunden', 2.0)
        sunrise = obs.sunrise or 7.0
        now_h = datetime.now().hour + datetime.now().minute / 60.0
        if now_h - sunrise < min_h:
            return 0

        schwelle = get_param(matrix, self.regelkreis, 'abweichung_schwelle_pct', 70)
        if obs.pv_vs_forecast_pct < schwelle:
            score = get_score_gewicht(matrix, self.regelkreis)

            cloud_schwer = get_param(matrix, self.regelkreis, 'cloud_rest_schwer_pct', 80)
            if obs.cloud_rest_avg_pct is not None and obs.cloud_rest_avg_pct > cloud_schwer:
                return score
            return int(score * 0.8)

        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        """Bei unplausibler Prognose: SOC_MAX vorsorglich erhöhen."""
        faktor = get_param(matrix, self.regelkreis, 'korrektur_faktor', 0.7)
        cloud_schwer = get_param(matrix, self.regelkreis, 'cloud_rest_schwer_pct', 80)
        cloud_faktor = get_param(matrix, self.regelkreis, 'cloud_reduktion_faktor', 0.6)

        eff_faktor = faktor
        if obs.cloud_rest_avg_pct is not None and obs.cloud_rest_avg_pct > cloud_schwer:
            eff_faktor = faktor * cloud_faktor

        rest_korrigiert = round((obs.forecast_rest_kwh or 0) * eff_faktor, 1)
        ist_pct = obs.pv_vs_forecast_pct or 0

        aktionen = []
        if rest_korrigiert < 5.0 and obs.soc_max is not None and obs.soc_max < 100:
            if obs.soc_mode != 'manual':
                aktionen.append({
                    'tier': 2, 'aktor': 'batterie',
                    'kommando': 'set_soc_mode', 'wert': 'manual',
                    'grund': f'Forecast-Korrektur: SOC_MODE → manual',
                })
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_max', 'wert': 100,
                'grund': (f'Forecast-Korrektur: IST/SOLL {ist_pct:.0f}%, '
                          f'Rest {rest_korrigiert} kWh (Faktor {eff_faktor:.2f}) → SOC_MAX 100%'),
            })
        else:
            LOG.info(f"Forecast-Plausi: IST/SOLL {ist_pct:.0f}%, Rest {rest_korrigiert} kWh — keine Aktion")

        # Engine-Aktionen registrieren (Extern-Erkennung)
        for a in aktionen:
            soc_extern_tracker.registriere_aktion(a.get('kommando', ''), a.get('wert'))

        return aktionen


# ═════════════════════════════════════════════════════════════
# LADERATE DYNAMISCH (P2 — Steuerung, fast)
# ═════════════════════════════════════════════════════════════

class RegelLaderateDynamisch(Regel):
    """Laderate dynamisch steuern: WP-Last, PV-Verfügbarkeit, SOC-Bereich.

    Parametermatrix: regelkreise.laderate_dynamisch
    """

    name = 'laderate_dynamisch'
    regelkreis = 'laderate_dynamisch'
    engine_zyklus = 'fast'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        is_charging = False
        if obs.cha_state is not None and obs.cha_state == 4:
            is_charging = True
        elif obs.batt_power_w is not None and obs.batt_power_w > 100:
            is_charging = True

        if not is_charging:
            return 0

        score = get_score_gewicht(matrix, self.regelkreis)

        if obs.wp_active:
            return int(score * 1.2)

        return score

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        komfort_rate = get_param(matrix, self.regelkreis, 'komfort_max_laderate_pct', 80)
        stress_rate = get_param(matrix, self.regelkreis, 'stress_max_laderate_pct', 100)
        wp_rate = get_param(matrix, self.regelkreis, 'wp_aktiv_reduktion_pct', 60)
        min_pv = get_param(matrix, self.regelkreis, 'pv_min_fuer_vollladung_w', 5000)

        rate = stress_rate

        if obs.wp_active:
            rate = min(rate, wp_rate)
            grund_detail = f'WP aktiv ({obs.wp_power_w or 0:.0f}W) → Laderate auf {rate}%'
        elif (obs.batt_soc_pct is not None and 25 <= obs.batt_soc_pct <= 75):
            rate = min(rate, komfort_rate)
            grund_detail = f'Komfort-Bereich (SOC {obs.batt_soc_pct:.0f}%) → Laderate {rate}%'
        elif obs.pv_total_w is not None and obs.pv_total_w < min_pv:
            pv_ratio = obs.pv_total_w / min_pv
            rate = max(30, int(stress_rate * pv_ratio))
            grund_detail = f'PV {obs.pv_total_w:.0f}W < {min_pv}W → Laderate {rate}%'
        else:
            grund_detail = f'Stress-Bereich, PV ausreichend → Laderate {rate}%'

        if obs.charge_rate_pct is not None and abs(obs.charge_rate_pct - rate) < 5:
            return []

        return [{
            'tier': 2, 'aktor': 'batterie',
            'kommando': 'set_charge_rate',
            'wert': rate,
            'grund': f'Laderate dynamisch: {grund_detail}',
        }]
