"""
geraete.py — Geräte-spezifische Regeln (P1-P2, fast-Zyklus)

RegelWattpilotBattSchutz — Batterieschutz bei EV-Ladung
RegelHeizpatrone         — Fritz!DECT Heizpatrone (Burst-Strategie)

Siehe: doc/WATTPILOT_ARCHITECTURE.md, automation/STRATEGIEN.md §2.6
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht,
)

LOG = logging.getLogger('engine')


# ═════════════════════════════════════════════════════════════
# WATTPILOT BATTERIESCHUTZ (P1 — Sicherheit, fast)
# ═════════════════════════════════════════════════════════════

class RegelWattpilotBattSchutz(Regel):
    """Batterieschutz bei WattPilot-EV-Ladung.

    Logik (3 Stufen):
    1. SOC > drosselung_ab (50%): Wolke OK — kein Eingriff
    2. SOC ≤ drosselung_ab (50%): Entladerate auf 0.3C (≈30%)
    3. SOC ≤ SOC_MIN + puffer: SOC_MIN anheben → Netzladung erzwingen

    Parametermatrix: regelkreise.wattpilot_battschutz
    """

    name = 'wattpilot_battschutz'
    regelkreis = 'wattpilot_battschutz'
    engine_zyklus = 'fast'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        schwelle = get_param(matrix, self.regelkreis, 'ev_leistung_schwelle_w', 2000)
        ev_aktiv = False
        if obs.ev_charging:
            ev_aktiv = True
        elif obs.ev_power_w is not None and obs.ev_power_w > schwelle:
            ev_aktiv = True

        if not ev_aktiv:
            return 0

        if obs.batt_power_w is not None and obs.batt_power_w >= 0:
            return 0

        score = get_score_gewicht(matrix, self.regelkreis)

        puffer = get_param(matrix, self.regelkreis, 'soc_min_puffer_pct', 5)
        soc_min_eff = obs.soc_min or 10
        if obs.batt_soc_pct is not None and obs.batt_soc_pct <= soc_min_eff + puffer:
            return int(score * 1.3)

        drosselung = get_param(matrix, self.regelkreis, 'soc_drosselung_ab_pct', 50)
        if obs.batt_soc_pct is not None and obs.batt_soc_pct <= drosselung:
            return score

        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        aktionen = []

        drosselung = get_param(matrix, self.regelkreis, 'soc_drosselung_ab_pct', 50)
        puffer = get_param(matrix, self.regelkreis, 'soc_min_puffer_pct', 5)
        soc_min_eff = obs.soc_min if obs.soc_min is not None else 10
        soc = obs.batt_soc_pct if obs.batt_soc_pct is not None else 50
        rate_red = get_param(matrix, self.regelkreis, 'entladerate_reduziert_pct', 30)
        soc_min_netz = get_param(matrix, self.regelkreis, 'soc_min_netz_pct', 25)

        eco_info = " (Eco-Modus)" if obs.ev_eco_mode else " (kein Eco → Schnellladung)"
        ev_w = obs.ev_power_w or 0

        # ── Stufe 3: SOC nahe SOC_MIN → Netzbezug erzwingen ─
        if soc <= soc_min_eff + puffer:
            if obs.soc_mode != 'manual':
                aktionen.append({
                    'tier': 2, 'aktor': 'batterie',
                    'kommando': 'set_soc_mode', 'wert': 'manual',
                    'grund': 'WattPilot-Schutz: SOC_MODE → manual',
                })
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_min', 'wert': soc_min_netz,
                'grund': (f'WattPilot-Schutz: SOC {soc:.0f}% nahe SOC_MIN '
                          f'{soc_min_eff}% → SOC_MIN auf {soc_min_netz}% '
                          f'(Netzbezug){eco_info}'),
                'hinweis': (f'WattPilot lädt mit {ev_w:.0f}W{eco_info} — '
                            f'Batterie geschützt, Ladung ab jetzt aus dem Netz'),
            })
            return aktionen

        # ── Stufe 2: Entladerate drosseln (0.3C) ────────────
        if soc <= drosselung:
            if obs.discharge_rate_pct is None or obs.discharge_rate_pct > rate_red + 5:
                aktionen.append({
                    'tier': 2, 'aktor': 'batterie',
                    'kommando': 'set_discharge_rate',
                    'wert': rate_red,
                    'grund': (f'WattPilot-Schutz: SOC {soc:.0f}% ≤ {drosselung}% '
                              f'→ Entladerate auf {rate_red}% (≈0.3C)'),
                })

        return aktionen


# ═════════════════════════════════════════════════════════════
# HEIZPATRONE (P2 — Steuerung, fast)
# ═════════════════════════════════════════════════════════════

class RegelHeizpatrone(Regel):
    """Heizpatrone (2 kW) via Fritz!DECT — prognosegesteuerte Burst-Strategie.

    Trigger: Batterie-Ladeleistung (nicht P_PV, da Nulleinspeiser abregelt).
    Planung: Forecast rest_kwh + rest_h.
    Schutz:  Netzbezug → AUS, Batterie-Entladung → AUS.

    4 Phasen:
      Phase 1: Vormittags — gute Prognose → HP darf EV+Batt verzögern
      Phase 2: Mittags    — Batterie lädt kräftig → Burst wenn Prognose reicht
      Phase 3: Nachmittag — nur bei deutlichem Überschuss, konservativ
      Phase 4: Abend      — HARD BLOCK (Batterie für Nacht füllen)

    Parametermatrix: regelkreise.heizpatrone
    Siehe: automation/STRATEGIEN.md §2.6
    """

    name = 'heizpatrone'
    regelkreis = 'heizpatrone'
    aktor = 'fritzdect'
    engine_zyklus = 'fast'

    def __init__(self):
        super().__init__()
        self._burst_start: float = 0
        self._burst_ende: float = 0
        self._letzte_aus: float = 0

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        """Score für HP-Steuerung.

        Zwei Pfade:
          1. Notaus (HP AUS) — IMMER aktiv, auch bei aktiv=False
          2. Burst-EIN — nur bei aktiv=True (Strategie).
        """
        now_h = datetime.now().hour + datetime.now().minute / 60
        sunset = obs.sunset or 17.0
        rest_h = max(0, sunset - now_h)
        p_batt = obs.batt_power_w
        score = get_score_gewicht(matrix, self.regelkreis)

        # ── Notaus-Pfad: IMMER aktiv ──
        if obs.heizpatrone_aktiv:
            notaus_netz = get_param(matrix, self.regelkreis, 'notaus_netzbezug_w', 200)
            notaus_soc_schwelle = get_param(matrix, self.regelkreis, 'notaus_soc_schwelle_pct', 90)
            notaus_entlade_hochsoc = get_param(matrix, self.regelkreis, 'notaus_entladung_hochsoc_w', -1000)
            min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
            temp_max = get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78)

            if rest_h < min_rest_h:
                return int(score * 1.5)

            if p_batt is not None and p_batt < 0:
                soc_now = obs.batt_soc_pct or 0
                if soc_now >= notaus_soc_schwelle:
                    if p_batt < notaus_entlade_hochsoc:
                        return int(score * 1.5)
                else:
                    return int(score * 1.5)
            if obs.grid_power_w is not None and obs.grid_power_w > notaus_netz:
                return int(score * 1.5)
            if obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
                return int(score * 1.5)

            if self._burst_ende > 0 and time.time() >= self._burst_ende:
                return int(score * 1.2)

            if self._burst_ende > 0 and time.time() < self._burst_ende:
                return score

        # ── Burst-EIN-Pfad: nur bei aktiv=True ──
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        rest_kwh = obs.forecast_rest_kwh
        soc = obs.batt_soc_pct
        soc_max_eff = obs.soc_max or 75

        if p_batt is None or rest_kwh is None or soc is None:
            return 0

        min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
        if rest_h < min_rest_h:
            return 0

        temp_max = get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78)
        if obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
            return 0

        min_pause = get_param(matrix, self.regelkreis, 'min_pause_s', 300)
        if (not obs.heizpatrone_aktiv and self._letzte_aus > 0
                and (time.time() - self._letzte_aus) < min_pause):
            return 0

        batt_rest_kwh = max(0, (soc_max_eff - soc) * 10.24 / 100)

        max_wp = get_param(matrix, self.regelkreis, 'max_wattpilot_w', 500)
        ev_aktiv = (obs.ev_power_w or 0) > max_wp

        # Phase 1: Vormittags
        min_lade_morgens = get_param(matrix, self.regelkreis, 'min_ladeleistung_morgens_w', 3000)
        min_rest_kwh_morgens = get_param(matrix, self.regelkreis, 'min_rest_kwh_morgens', 20.0)
        min_rest_h_morgens = get_param(matrix, self.regelkreis, 'min_rest_h_morgens', 5.0)

        if rest_h > min_rest_h_morgens and rest_kwh > min_rest_kwh_morgens:
            if p_batt > min_lade_morgens:
                return score

        # Phase 2+3: Mittags/Nachmittags
        min_lade = get_param(matrix, self.regelkreis, 'min_ladeleistung_w', 5000)
        min_rest = get_param(matrix, self.regelkreis, 'min_rest_kwh', 12.0)
        reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)

        if rest_h < 3.0:
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_nachmittag_kwh', 3.0)

        if p_batt > min_lade and not ev_aktiv:
            if rest_kwh > batt_rest_kwh + reserve:
                return score

        if rest_kwh > min_rest and p_batt > min_lade:
            return score

        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        """HP ein-/ausschalten: Notaus + Burst-Strategie."""
        now_h = datetime.now().hour + datetime.now().minute / 60
        sunset = obs.sunset or 17.0
        rest_h = max(0, sunset - now_h)
        rest_kwh = obs.forecast_rest_kwh or 0
        p_batt = obs.batt_power_w or 0
        soc = obs.batt_soc_pct if obs.batt_soc_pct is not None else 50
        soc_max_eff = obs.soc_max if obs.soc_max is not None else 75

        # ── HP ist EIN → Notaus prüfen ──
        if obs.heizpatrone_aktiv:
            notaus_grund = None
            notaus_netz = get_param(matrix, self.regelkreis, 'notaus_netzbezug_w', 200)
            notaus_soc_schwelle = get_param(matrix, self.regelkreis, 'notaus_soc_schwelle_pct', 90)
            notaus_entlade_hochsoc = get_param(matrix, self.regelkreis, 'notaus_entladung_hochsoc_w', -1000)
            min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
            temp_max = get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78)

            if rest_h < min_rest_h:
                notaus_grund = f'Phase 4: rest_h={rest_h:.1f} < {min_rest_h} → HARD BLOCK'
            elif p_batt < 0:
                soc_now = soc
                if soc_now >= notaus_soc_schwelle:
                    if p_batt < notaus_entlade_hochsoc:
                        notaus_grund = (f'Batterie entlädt ({p_batt:.0f}W < {notaus_entlade_hochsoc}W) '
                                        f'trotz SOC {soc_now:.0f}% ≥ {notaus_soc_schwelle}%')
                else:
                    notaus_grund = (f'Batterie entlädt ({p_batt:.0f}W) bei SOC '
                                    f'{soc_now:.0f}% < {notaus_soc_schwelle}%')
            elif obs.grid_power_w is not None and obs.grid_power_w > notaus_netz:
                notaus_grund = f'Netzbezug ({obs.grid_power_w:.0f}W > {notaus_netz}W)'
            elif obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
                notaus_grund = f'Übertemperatur ({obs.ww_temp_c:.0f}°C ≥ {temp_max}°C)'
            elif self._burst_ende > 0 and time.time() >= self._burst_ende:
                notaus_grund = f'Burst-Timer abgelaufen ({int((time.time() - self._burst_start) / 60)} Min)'

            if notaus_grund:
                self._letzte_aus = time.time()
                self._burst_start = 0
                self._burst_ende = 0
                return [{
                    'tier': 2, 'aktor': 'fritzdect',
                    'kommando': 'hp_aus',
                    'grund': f'HP AUS: {notaus_grund}',
                }]

            return []

        # ── HP ist AUS → prüfe ob Burst gestartet werden soll ─
        batt_rest_kwh = max(0, (soc_max_eff - soc) * 10.24 / 100)
        min_rest_h_morgens = get_param(matrix, self.regelkreis, 'min_rest_h_morgens', 5.0)
        min_rest_kwh_morgens = get_param(matrix, self.regelkreis, 'min_rest_kwh_morgens', 20.0)
        min_lade_morgens = get_param(matrix, self.regelkreis, 'min_ladeleistung_morgens_w', 3000)
        min_lade = get_param(matrix, self.regelkreis, 'min_ladeleistung_w', 5000)
        burst_lang = get_param(matrix, self.regelkreis, 'burst_dauer_lang_s', 1800)
        burst_kurz = get_param(matrix, self.regelkreis, 'burst_dauer_kurz_s', 900)

        burst_dauer = 0
        grund = ''

        # Phase 1
        if rest_h > min_rest_h_morgens and rest_kwh > min_rest_kwh_morgens:
            if p_batt > min_lade_morgens:
                burst_dauer = burst_lang
                grund = (f'Phase 1 (Vormittag): P_Batt={p_batt:.0f}W, '
                         f'rest_kwh={rest_kwh:.1f}, rest_h={rest_h:.1f}')

        # Phase 2
        if not burst_dauer and p_batt > min_lade:
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)
            max_wp = get_param(matrix, self.regelkreis, 'max_wattpilot_w', 500)
            ev_aktiv = (obs.ev_power_w or 0) > max_wp

            if rest_kwh > batt_rest_kwh + reserve and not ev_aktiv:
                burst_dauer = burst_lang if rest_kwh > min_rest_kwh_morgens else burst_kurz
                grund = (f'Phase 2 (Mittag): P_Batt={p_batt:.0f}W, '
                         f'rest_kwh={rest_kwh:.1f}, batt_rest={batt_rest_kwh:.1f}')

        # Phase 3
        if not burst_dauer and rest_h < 3.0 and rest_h >= min_rest_h:
            reserve_nm = get_param(matrix, self.regelkreis, 'batt_reserve_nachmittag_kwh', 3.0)
            if p_batt > min_lade and rest_kwh > batt_rest_kwh + reserve_nm:
                burst_dauer = burst_kurz
                grund = (f'Phase 3 (Nachmittag): P_Batt={p_batt:.0f}W, '
                         f'rest_kwh={rest_kwh:.1f}, reserve={reserve_nm:.1f}')

        if burst_dauer > 0:
            self._burst_start = time.time()
            self._burst_ende = time.time() + burst_dauer
            return [{
                'tier': 2, 'aktor': 'fritzdect',
                'kommando': 'hp_ein',
                'grund': f'HP EIN (Burst {burst_dauer // 60:.0f} Min): {grund}',
            }]

        return []
