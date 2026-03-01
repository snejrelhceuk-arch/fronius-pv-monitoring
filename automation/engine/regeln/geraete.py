"""
geraete.py — Geräte-spezifische Regeln (P1-P2, fast-Zyklus)

RegelWattpilotBattSchutz — Batterieschutz bei EV-Ladung
RegelHeizpatrone         — Fritz!DECT Heizpatrone (Burst-Strategie)

Siehe: doc/WATTPILOT_ARCHITECTURE.md, automation/STRATEGIEN.md §2.6
"""

from __future__ import annotations

import logging
import time
from collections import deque
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

    Potenzial-gesteuert: Forecast-kWh bestimmt Freigabegrad.
    Kontextabhängig: SOC_MAX-Phase, Verbraucher, Tageszeit.

    Potenzial-Skala (konfigurierbar):
      < 15 kWh (mäßig)  — HP nur solo, kein Parallel-Betrieb
      15–30 kWh (ausreichend) — HP + WP ok, EV → HP pausiert
      ≥ 30 kWh (gut+)   — HP parallel mit allen Verbrauchern

    6 Phasen:
      Phase 0:  Morgen-Drain — Batterie schneller leeren bei wenig Verbrauch
      Phase 1:  Vormittags — gute Prognose → HP darf EV+Batt verzögern
      Phase 1b: Nulleinspeiser — SOC≈MAX, PV produziert, Batt idle → stille Kapazität
      Phase 2:  Mittags    — Batterie lädt kräftig → Burst wenn Prognose reicht
      Phase 3:  Nachmittag — nur bei deutlichem Überschuss, konservativ
      Phase 4:  Abend      — HARD BLOCK (Batterie für Nacht füllen)

    Notaus HART (immer sofort):
      - rest_h < 2h, WW-Temp ≥ 78°C, SOC ≤ 7%

    Notaus KONTEXTABHÄNGIG (Batterie entlädt):
      - Forecast ≥ 30 kWh: toleriert außer Phase 4
      - Forecast 15–30 kWh: toleriert wenn SOC_MAX ≤ 75% (Batt gedeckelt)
      - Forecast < 15 kWh: HP AUS bei jeder Entladung

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
        self._drain_modus: bool = False
        # Extern-Erkennung: HP wurde außerhalb der Engine eingeschaltet
        self._extern_ein_ts: float = 0       # Zeitpunkt der Extern-Erkennung
        self._letzter_hp_zustand: bool = False  # HP-Zustand im vorherigen Zyklus
        # Glättung: Netzbezug-Historie für 5-Min-Durchschnitt (Engine-Zyklus ~60s)
        self._grid_history: deque = deque(maxlen=5)

    # ── Potenzial-Klassifikation ─────────────────────────────

    def _potenzial(self, forecast_kwh: float, matrix: dict) -> str:
        """Tagespotenzial klassifizieren anhand konfigurierbarer Schwellen.

        Returns: 'niedrig' | 'maessig' | 'ausreichend' | 'gut'
        """
        gut = get_param(matrix, self.regelkreis, 'potenzial_gut_kwh', 30.0)
        ausreichend = get_param(matrix, self.regelkreis, 'potenzial_ausreichend_kwh', 20.0)
        maessig = get_param(matrix, self.regelkreis, 'potenzial_maessig_kwh', 15.0)

        if forecast_kwh >= gut:
            return 'gut'
        elif forecast_kwh >= ausreichend:
            return 'ausreichend'
        elif forecast_kwh >= maessig:
            return 'maessig'
        else:
            return 'niedrig'

    def _verbraucher_aktiv(self, obs: ObsState, matrix: dict) -> tuple[bool, bool]:
        """Prüfe ob Großverbraucher aktiv sind.

        Returns: (wp_aktiv, ev_aktiv)
        """
        wp_schwelle = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
        ev_schwelle = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
        wp_aktiv = (obs.wp_power_w or 0) >= wp_schwelle
        ev_aktiv = (obs.ev_power_w or 0) >= ev_schwelle
        return wp_aktiv, ev_aktiv

    def _hp_parallel_erlaubt(self, potenzial: str, wp_aktiv: bool,
                              ev_aktiv: bool) -> bool:
        """Darf HP parallel mit WP/EV laufen?

        Potenzial:
          gut (≥30 kWh):       HP + WP + EV alles gleichzeitig
          ausreichend (20-30): HP + WP ok, HP + EV → HP pausiert
          mäßig (15-20):       HP nur solo (kein WP, kein EV)
          niedrig (<15):       HP nicht automatisch (nur Extern)
        """
        if potenzial == 'gut':
            return True  # Alles parallel erlaubt
        if potenzial == 'ausreichend':
            return not ev_aktiv  # WP ok, EV → HP pausiert
        # mäßig oder niedrig: kein Parallelbetrieb
        return not (wp_aktiv or ev_aktiv)

    def _min_lade_nach_potenzial(self, potenzial: str, matrix: dict) -> float:
        """Potenzialabhängige Mindest-Ladeleistung für Burst-Start.

        Bei gutem Potenzial reicht weniger Batterie-Ladung als Trigger,
        weil der Burst-Timer und die Potenzial-Notaus die HP schützen.
        Grundlage: p_batt - HP_Last (~2kW) sollte positiv bleiben.

        Returns: Schwellwert in Watt
        """
        basis = get_param(matrix, self.regelkreis, 'min_ladeleistung_w', 5000)
        if potenzial == 'gut':
            return max(2000, basis * 0.5)    # 50% → 2500W
        elif potenzial == 'ausreichend':
            return max(2500, basis * 0.7)    # 70% → 3500W
        # mäßig/niedrig: volle Schwelle
        return basis

    def _grid_avg(self, obs: ObsState) -> float:
        """Geglätteter Netzbezug (5-Zyklen-Durchschnitt ≈ 5 Min).

        Verhindert Notaus durch kurzzeitige Leistungssprünge (±10kW).
        Nur positive Werte (Bezug) werden gemittelt; Einspeisung = 0.
        """
        gw = obs.grid_power_w
        if gw is not None:
            self._grid_history.append(max(0, gw))
        if not self._grid_history:
            return 0.0
        return sum(self._grid_history) / len(self._grid_history)

    def _batt_entladung_toleriert(self, potenzial: str, soc_max_eff: int,
                                   obs: ObsState) -> bool:
        """Wird Batterie-Entladung toleriert (HP darf trotzdem laufen)?

        Kontext-Logik:
          gut (≥ 30 kWh):       toleriert (ausreichend PV um nachzuladen)
          ausreichend/mäßig:    toleriert WENN SOC_MAX ≤ 75% (Batt gedeckelt,
                                füllen noch nicht nötig)
          niedrig:              nie toleriert
        """
        if potenzial == 'gut':
            return True
        if potenzial in ('ausreichend', 'maessig'):
            # Batterie ist noch gedeckelt → Entladung ist "normal"
            return soc_max_eff <= 75
        return False  # niedrig → keine Toleranz

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        """Score für HP-Steuerung.

        Drei Pfade:
          1. Notaus (HP AUS) — IMMER aktiv, auch bei aktiv=False
          2. Drain-EIN (Phase 0) — wenn aktiv, Batterie morgens leeren
          3. Burst-EIN (Phase 1-3) — nur bei aktiv=True (Strategie).
        """
        now_h = datetime.now().hour + datetime.now().minute / 60
        sunset = obs.sunset or 17.0
        rest_h = max(0, sunset - now_h)
        p_batt = obs.batt_power_w
        score = get_score_gewicht(matrix, self.regelkreis)

        # ── Extern-Erkennung ──
        # HP wurde EIN, aber nicht durch Engine (kein Burst/Drain aktiv)
        if obs.heizpatrone_aktiv and not self._letzter_hp_zustand:
            if self._burst_ende == 0 and not self._drain_modus:
                self._extern_ein_ts = time.time()
                LOG.info('HP extern eingeschaltet erkannt → Hysterese aktiv')
        if not obs.heizpatrone_aktiv:
            self._extern_ein_ts = 0
        self._letzter_hp_zustand = obs.heizpatrone_aktiv

        extern_respekt = get_param(matrix, self.regelkreis, 'extern_respekt_s', 3600)
        ist_extern = (self._extern_ein_ts > 0
                      and (time.time() - self._extern_ein_ts) < extern_respekt)

        # ── Notaus-Pfad: IMMER aktiv ──
        if obs.heizpatrone_aktiv:
            min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
            temp_max = get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78)
            soc_schutz_abs = get_param(matrix, 'soc_schutz', 'stop_entladung_unter_pct', 7)

            # ── HARTE Kriterien: IMMER sofort, auch bei Extern ──
            if rest_h < min_rest_h:
                return int(score * 1.5)
            if obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
                return int(score * 1.5)
            if (obs.batt_soc_pct or 0) <= soc_schutz_abs:
                return int(score * 1.5)

            # ── KONTEXTABHÄNGIGE Kriterien ──
            # Bei Extern-Hysterese: nur HARTE greifen (oben), Rest pausiert
            if ist_extern:
                LOG.debug(f'HP extern → weiche Notaus pausiert '
                          f'({int(extern_respekt - (time.time() - self._extern_ein_ts))}s verbleibend)')
            else:
                forecast_kwh = obs.forecast_kwh or 0
                potenzial = self._potenzial(forecast_kwh, matrix)
                soc_max_eff = obs.soc_max or 75
                wp_aktiv, ev_aktiv = self._verbraucher_aktiv(obs, matrix)

                # Drain-Modus hat eigene Schutzlogik
                if self._drain_modus:
                    drain_min_soc = get_param(matrix, self.regelkreis, 'drain_min_soc_pct', 10)
                    soc_now = obs.batt_soc_pct or 0
                    if soc_now <= drain_min_soc:
                        return int(score * 1.5)
                    d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
                    d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
                    d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
                    if ((obs.house_load_w or 0) >= d_haus * 1.2
                            or (obs.wp_power_w or 0) >= d_wp
                            or (obs.ev_power_w or 0) >= d_ev):
                        return int(score * 1.5)
                else:
                    # Batterie entlädt: potenzial- und kontextabhängig
                    if p_batt is not None and p_batt < 0:
                        if not self._batt_entladung_toleriert(potenzial, soc_max_eff, obs):
                            return int(score * 1.5)

                    # Verbraucher-Konkurrenz: potenzialabhängig
                    if not self._hp_parallel_erlaubt(potenzial, wp_aktiv, ev_aktiv):
                        return int(score * 1.2)

                    # Netzbezug (5-Min-Durchschnitt)
                    notaus_netz = get_param(matrix, self.regelkreis, 'notaus_netzbezug_w', 200)
                    grid_avg = self._grid_avg(obs)
                    if grid_avg > notaus_netz:
                        return int(score * 1.5)

                # Burst-Timer abgelaufen
                if self._burst_ende > 0 and time.time() >= self._burst_ende:
                    return int(score * 1.2)

            # Laufender Burst noch aktiv → Score halten (kein Abschalten)
            if not ist_extern and self._burst_ende > 0 and time.time() < self._burst_ende:
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

        forecast_kwh = obs.forecast_kwh or 0
        potenzial = self._potenzial(forecast_kwh, matrix)
        wp_aktiv, ev_aktiv = self._verbraucher_aktiv(obs, matrix)

        # Phase 0: Morgen-Drain — HP um Batterie schneller zu leeren
        #   Bedingungen: vor PV-Produktion, niedrige Verbraucher,
        #   SOC > Schwelle, gute/mittlere Prognose, Prognose > 4 kW
        drain_fenster = get_param(matrix, self.regelkreis, 'drain_fenster_ende_h', 10.0)
        if now_h < drain_fenster and (p_batt is None or p_batt < 500):
            drain_min_soc = get_param(matrix, self.regelkreis, 'drain_min_soc_pct', 10)
            d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
            d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
            d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
            d_prognose_kw = get_param(matrix, self.regelkreis, 'drain_min_prognose_kw', 4.0)

            haushalt_ok = (obs.house_load_w or 0) < d_haus
            wp_ok = (obs.wp_power_w or 0) < d_wp
            ev_ok = (obs.ev_power_w or 0) < d_ev
            soc_ok = soc > drain_min_soc
            forecast_ok = obs.forecast_quality in ('gut', 'mittel')

            # Prognose zeigt ≥ drain_min_prognose_kw in kommenden Stunden
            prognose_stark = False
            if obs.forecast_power_profile:
                now_h_int = int(now_h)
                for entry in obs.forecast_power_profile:
                    h = entry.get('hour', 0)
                    if h > now_h_int and entry.get('total_ac_w', 0) >= d_prognose_kw * 1000:
                        prognose_stark = True
                        break

            if all([haushalt_ok, wp_ok, ev_ok, soc_ok, forecast_ok, prognose_stark]):
                return score

        # Phase 1: Vormittags
        min_lade_morgens = get_param(matrix, self.regelkreis, 'min_ladeleistung_morgens_w', 3000)
        min_rest_kwh_morgens = get_param(matrix, self.regelkreis, 'min_rest_kwh_morgens', 20.0)
        min_rest_h_morgens = get_param(matrix, self.regelkreis, 'min_rest_h_morgens', 5.0)

        if rest_h > min_rest_h_morgens and rest_kwh > min_rest_kwh_morgens:
            if p_batt > min_lade_morgens:
                return score

        # Phase 1b: Nulleinspeiser-Überschuss — PV wird gedrosselt
        #   SOC ≈ SOC_MAX, Batterie idle, Grid ≈ 0 → Nulleinspeiser drosselt PV.
        #   pv_total_w zeigt nur gedrosselte AC-Leistung (≈ Haushalt), NICHT
        #   was die Module könnten. Daher Forecast-Profil als Proxy nutzen.
        #   HP einschalten erzeugt Nachfrage → WR lässt PV hochfahren.
        hp_last = 2000  # HP-Nennleistung ~2kW
        soc_nah_max = soc >= (soc_max_eff - 2)
        batt_idle = abs(p_batt) < 500
        grid_ok = abs(obs.grid_power_w or 0) < 300

        # Forecast für aktuelle Stunde: zeigt was PV KANN (nicht was WR liefert)
        forecast_jetzt_w = 0
        if obs.forecast_power_profile:
            now_h_int = int(now_h)
            for entry in obs.forecast_power_profile:
                if entry.get('hour', 0) == now_h_int:
                    forecast_jetzt_w = entry.get('total_ac_w', 0)
                    break
        pv_kann_hp = forecast_jetzt_w >= hp_last  # Forecast sagt: PV reicht für HP

        if soc_nah_max and batt_idle and pv_kann_hp and grid_ok and parallel_ok:
            if rest_kwh > reserve:  # Noch genug Tagesprognose für Rest
                return score

        # Phase 2+3: Mittags/Nachmittags
        min_lade = self._min_lade_nach_potenzial(potenzial, matrix)
        min_rest = get_param(matrix, self.regelkreis, 'min_rest_kwh', 12.0)
        reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)

        if rest_h < 3.0:
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_nachmittag_kwh', 3.0)

        parallel_ok = self._hp_parallel_erlaubt(potenzial, wp_aktiv, ev_aktiv)

        if p_batt > min_lade and parallel_ok:
            if rest_kwh > batt_rest_kwh + reserve:
                return score

        if rest_kwh > min_rest and p_batt > min_lade and parallel_ok:
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
            min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
            temp_max = get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78)

            # Extern-Erkennung auch im Aktion-Pfad nutzen
            extern_respekt = get_param(matrix, self.regelkreis, 'extern_respekt_s', 3600)
            ist_extern = (self._extern_ein_ts > 0
                          and (time.time() - self._extern_ein_ts) < extern_respekt)
            soc_schutz_abs = get_param(matrix, 'soc_schutz', 'stop_entladung_unter_pct', 7)

            # ── HARTE Kriterien: IMMER sofort ──
            if rest_h < min_rest_h:
                notaus_grund = f'HART: Phase 4 rest_h={rest_h:.1f} < {min_rest_h} → HARD BLOCK'
            elif obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
                notaus_grund = f'HART: Übertemperatur ({obs.ww_temp_c:.0f}°C ≥ {temp_max}°C)'
            elif soc <= soc_schutz_abs:
                notaus_grund = f'HART: SOC {soc:.0f}% ≤ Schutzgrenze {soc_schutz_abs}%'

            # ── KONTEXTABHÄNGIGE Kriterien: bei Extern-Hysterese pausiert ──
            elif ist_extern:
                LOG.debug(f'HP extern eingeschaltet → weiche Notaus-Kriterien pausiert '
                          f'({int(extern_respekt - (time.time() - self._extern_ein_ts))}s verbleibend)')
            else:
                forecast_kwh = obs.forecast_kwh or 0
                potenzial = self._potenzial(forecast_kwh, matrix)
                wp_aktiv, ev_aktiv = self._verbraucher_aktiv(obs, matrix)

                if self._drain_modus:
                    # Drain: Entladung gewollt — Drain-Schutzgrenzen prüfen
                    drain_min_soc = get_param(matrix, self.regelkreis, 'drain_min_soc_pct', 10)
                    if soc <= drain_min_soc:
                        notaus_grund = (f'Drain-Ende: SOC {soc:.0f}% ≤ '
                                        f'drain_min {drain_min_soc}%')
                    else:
                        d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
                        d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
                        d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
                        house_w = obs.house_load_w or 0
                        wp_w = obs.wp_power_w or 0
                        ev_w = obs.ev_power_w or 0
                        if house_w >= d_haus * 1.2:
                            notaus_grund = (f'Drain-Ende: Haushalt {house_w:.0f}W '
                                            f'≥ {d_haus}×1.2')
                        elif wp_w >= d_wp:
                            notaus_grund = f'Drain-Ende: WP {wp_w:.0f}W ≥ {d_wp}W'
                        elif ev_w >= d_ev:
                            notaus_grund = f'Drain-Ende: EV {ev_w:.0f}W ≥ {d_ev}W'
                else:
                    # Batterie entlädt: potenzial- und kontextabhängig
                    if p_batt < 0:
                        if not self._batt_entladung_toleriert(potenzial, soc_max_eff, obs):
                            notaus_grund = (f'Batterie entlädt ({p_batt:.0f}W) '
                                            f'bei Potenzial={potenzial}, SOC_MAX={soc_max_eff}%')

                    # Verbraucher-Konkurrenz
                    if not notaus_grund and not self._hp_parallel_erlaubt(potenzial, wp_aktiv, ev_aktiv):
                        notaus_grund = (f'Verbraucher-Konkurrenz: Potenzial={potenzial}, '
                                        f'WP={wp_aktiv}, EV={ev_aktiv}')

                    # Netzbezug (5-Min-Durchschnitt gegen Leistungssprünge)
                    if not notaus_grund:
                        notaus_netz = get_param(matrix, self.regelkreis, 'notaus_netzbezug_w', 200)
                        grid_avg = self._grid_avg(obs)
                        if grid_avg > notaus_netz:
                            notaus_grund = (f'Netzbezug Ø{grid_avg:.0f}W > '
                                            f'{notaus_netz}W (aktuell {obs.grid_power_w or 0:.0f}W)')

                # Burst-Timer abgelaufen
                if not notaus_grund and self._burst_ende > 0 and time.time() >= self._burst_ende:
                    notaus_grund = f'Burst-Timer abgelaufen ({int((time.time() - self._burst_start) / 60)} Min)'

            if notaus_grund:
                self._letzte_aus = time.time()
                self._burst_start = 0
                self._burst_ende = 0
                self._drain_modus = False
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
        burst_lang = get_param(matrix, self.regelkreis, 'burst_dauer_lang_s', 1800)
        burst_kurz = get_param(matrix, self.regelkreis, 'burst_dauer_kurz_s', 900)

        burst_dauer = 0
        grund = ''

        # Phase 0: Morgen-Drain — Batterie mit HP schneller leeren
        drain_fenster = get_param(matrix, self.regelkreis, 'drain_fenster_ende_h', 10.0)
        if now_h < drain_fenster and p_batt < 500:
            drain_min_soc = get_param(matrix, self.regelkreis, 'drain_min_soc_pct', 10)
            d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
            d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
            d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
            d_prognose_kw = get_param(matrix, self.regelkreis, 'drain_min_prognose_kw', 4.0)
            drain_burst = get_param(matrix, self.regelkreis, 'drain_burst_dauer_s', 2700)

            haushalt_ok = (obs.house_load_w or 0) < d_haus
            wp_ok = (obs.wp_power_w or 0) < d_wp
            ev_ok = (obs.ev_power_w or 0) < d_ev
            soc_ok = soc > drain_min_soc
            forecast_ok = (obs.forecast_quality or '') in ('gut', 'mittel')

            prognose_stark = False
            if obs.forecast_power_profile:
                now_h_int = int(now_h)
                for entry in obs.forecast_power_profile:
                    h = entry.get('hour', 0)
                    if h > now_h_int and entry.get('total_ac_w', 0) >= d_prognose_kw * 1000:
                        prognose_stark = True
                        break

            if all([haushalt_ok, wp_ok, ev_ok, soc_ok, forecast_ok, prognose_stark]):
                self._burst_start = time.time()
                self._burst_ende = time.time() + drain_burst
                self._drain_modus = True
                return [{
                    'tier': 2, 'aktor': 'fritzdect',
                    'kommando': 'hp_ein',
                    'grund': (f'HP EIN (Drain {drain_burst // 60:.0f} Min): '
                              f'Phase 0 (Morgen-Drain) SOC={soc:.0f}%, '
                              f'Haus={obs.house_load_w or 0:.0f}W, '
                              f'Prognose={obs.forecast_quality}'),
                }]

        # Phase 1
        if rest_h > min_rest_h_morgens and rest_kwh > min_rest_kwh_morgens:
            if p_batt > min_lade_morgens:
                burst_dauer = burst_lang
                grund = (f'Phase 1 (Vormittag): P_Batt={p_batt:.0f}W, '
                         f'rest_kwh={rest_kwh:.1f}, rest_h={rest_h:.1f}')

        # Phase 1b: Nulleinspeiser-Überschuss — PV wird gedrosselt
        forecast_kwh = obs.forecast_kwh or 0
        potenzial = self._potenzial(forecast_kwh, matrix)
        min_lade = self._min_lade_nach_potenzial(potenzial, matrix)
        wp_aktiv, ev_aktiv = self._verbraucher_aktiv(obs, matrix)
        parallel_ok = self._hp_parallel_erlaubt(potenzial, wp_aktiv, ev_aktiv)

        if not burst_dauer:
            hp_last = 2000
            soc_nah_max = soc >= (soc_max_eff - 2)
            batt_idle = abs(p_batt) < 500
            grid_ok = abs(obs.grid_power_w or 0) < 300
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)

            # Forecast für aktuelle Stunde als Proxy für verfügbare PV-Kapazität
            forecast_jetzt_w = 0
            if obs.forecast_power_profile:
                now_h_int = int(now_h)
                for entry in obs.forecast_power_profile:
                    if entry.get('hour', 0) == now_h_int:
                        forecast_jetzt_w = entry.get('total_ac_w', 0)
                        break
            pv_kann_hp = forecast_jetzt_w >= hp_last

            if soc_nah_max and batt_idle and pv_kann_hp and grid_ok and parallel_ok:
                if rest_kwh > reserve:
                    burst_dauer = burst_lang
                    grund = (f'Phase 1b (Nulleinspeiser): SOC={soc:.0f}%≈MAX({soc_max_eff}%), '
                             f'Forecast_jetzt={forecast_jetzt_w:.0f}W, P_Batt={p_batt:.0f}W, '
                             f'Potenzial={potenzial}')

        # Phase 2
        if not burst_dauer and p_batt > min_lade:
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)

            if rest_kwh > batt_rest_kwh + reserve and parallel_ok:
                burst_dauer = burst_lang if rest_kwh > min_rest_kwh_morgens else burst_kurz
                grund = (f'Phase 2 (Mittag): P_Batt={p_batt:.0f}W, '
                         f'rest_kwh={rest_kwh:.1f}, batt_rest={batt_rest_kwh:.1f}, '
                         f'Potenzial={potenzial}, min_lade={min_lade:.0f}W')

        # Phase 3
        min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
        if not burst_dauer and rest_h < 3.0 and rest_h >= min_rest_h:
            reserve_nm = get_param(matrix, self.regelkreis, 'batt_reserve_nachmittag_kwh', 3.0)
            if p_batt > min_lade and rest_kwh > batt_rest_kwh + reserve_nm:
                burst_dauer = burst_kurz
                grund = (f'Phase 3 (Nachmittag): P_Batt={p_batt:.0f}W, '
                         f'rest_kwh={rest_kwh:.1f}, reserve={reserve_nm:.1f}')

        if burst_dauer > 0:
            self._burst_start = time.time()
            self._burst_ende = time.time() + burst_dauer
            self._drain_modus = False  # Normal-Burst, kein Drain
            return [{
                'tier': 2, 'aktor': 'fritzdect',
                'kommando': 'hp_ein',
                'grund': f'HP EIN (Burst {burst_dauer // 60:.0f} Min): {grund}',
            }]

        return []
