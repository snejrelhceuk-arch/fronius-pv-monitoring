"""
soc_steuerung.py — SOC-Steuerungsregeln (P2, mixed Zyklen)

RegelMorgenSocMin      — SOC_MIN morgens öffnen (fast)
RegelNachmittagSocMax  — SOC_MAX nachmittags erhöhen (strategic)
RegelKomfortReset      — Täglicher Reset auf 25–75% (fast)

Siehe: doc/BATTERIE_STRATEGIEN.md
"""

from __future__ import annotations

import logging
from datetime import datetime
from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.regeln.soc_extern import soc_extern_tracker
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht,
)

LOG = logging.getLogger('engine')


# ═════════════════════════════════════════════════════════════
# MORGEN SOC_MIN (P2 — Steuerung, fast)
# ═════════════════════════════════════════════════════════════

class RegelMorgenSocMin(Regel):
    """SOC_MIN morgens öffnen: Batterie entladen + SOC_MAX=75% begrenzen.

    Trigger-Kette:
      Sunrise → ForecastCollector holt Prognose (Tier-3, ~0.6s)
             → ObsState.pv_at_sunrise_1h_w wird befüllt
             → Engine nächster 60s-Zyklus sieht Wert
             → pv_at_sunrise_1h_w >= 1500W?  → SOC_MIN=5%, SOC_MAX=75%

    Halte-Modus: Solange SOC > stress+2% im Zeitfenster →
      Einstellung beibehalten (hoher Score verhindert Rücksetzung).

    Parametermatrix: regelkreise.morgen_soc_min
    """

    name = 'morgen_soc_min'
    regelkreis = 'morgen_soc_min'
    engine_zyklus = 'fast'

    def _im_zeitfenster(self, obs: ObsState, matrix: dict) -> bool:
        """(Sunrise - Vorlauf) bis Sunrise + fenster_ende_h."""
        now = datetime.now()
        hr = now.hour + now.minute / 60.0
        sunrise = obs.sunrise or 7.0
        vorlauf_h = get_param(matrix, self.regelkreis, 'morgen_vorlauf_min', 15) / 60.0
        ende_h = get_param(matrix, self.regelkreis, 'fenster_ende_nach_sunrise_h', 3)
        return (sunrise - vorlauf_h) <= hr <= sunrise + ende_h

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0
        if not self._im_zeitfenster(obs, matrix):
            return 0

        # ── SOC-Extern-Toleranz ──
        soc_extern_tracker.aktualisiere(obs, matrix)
        if soc_extern_tracker.ist_toleriert(matrix):
            verbleibend = soc_extern_tracker.verbleibend_s(matrix)
            LOG.debug(f'{self.name}: SOC extern geändert '
                      f'({soc_extern_tracker.extern_grund}) '
                      f'→ toleriert ({verbleibend}s verbleibend)')
            return 0

        stress = get_param(matrix, self.regelkreis, 'stress_min_pct', 5)
        score = get_score_gewicht(matrix, self.regelkreis)

        # ── HALTE-MODUS: SOC_MIN bereits geöffnet ──
        if obs.soc_min is not None and obs.soc_min <= stress:
            if obs.batt_soc_pct is not None and obs.batt_soc_pct > stress + 2:
                halte_score = int(score * 0.95)
                LOG.debug(f"morgen_soc_min HALTE: SOC={obs.batt_soc_pct:.1f}%, "
                          f"SOC_MIN={obs.soc_min}% → Score {halte_score}")
                return halte_score
            return 0  # SOC am Boden → Regel nicht mehr nötig

        # ── VETO: Prognose-Qualität 'schlecht' → nicht öffnen ──
        if obs.forecast_quality == 'schlecht':
            LOG.debug("morgen_soc_min: forecast_quality=schlecht → kein Öffnen")
            return 0

        # ── TRIGGER: pv_at_sunrise_1h_w >= Schwelle ──
        schwelle = get_param(matrix, self.regelkreis, 'pv_schwelle_sunrise_1h_w', 1500)
        pv_sr1h = obs.pv_at_sunrise_1h_w
        if pv_sr1h is None or pv_sr1h < schwelle:
            LOG.debug(f"morgen_soc_min: PV@SR+1h={pv_sr1h or 0:.0f}W "
                      f"< {schwelle}W → kein Trigger")
            return 0

        # ── VERZÖGERUNG: 'mittel' → erst Sunrise + 1h (abzgl. Vorlauf) ──
        if obs.forecast_quality == 'mittel':
            now_h = datetime.now().hour + datetime.now().minute / 60.0
            sunrise = obs.sunrise or 7.0
            vorlauf_h = get_param(matrix, self.regelkreis, 'morgen_vorlauf_min', 15) / 60.0
            verzoegerung = get_param(matrix, self.regelkreis, 'mittel_verzoegerung_h', 1.0)
            trigger_h = (sunrise - vorlauf_h) + verzoegerung
            if now_h < trigger_h:
                LOG.debug(f"morgen_soc_min: forecast_quality=mittel → warte bis "
                          f"SR-{vorlauf_h*60:.0f}min+{verzoegerung:.0f}h "
                          f"({trigger_h:.2f}h, jetzt {now_h:.2f}h)")
                return 0

        return score

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        stress = get_param(matrix, self.regelkreis, 'stress_min_pct', 5)
        komfort_max = get_param(matrix, self.regelkreis, 'morgen_soc_max_pct', 75)

        # ── HALTE-MODUS: bereits geöffnet → keine neue Aktion ──
        if obs.soc_min is not None and obs.soc_min <= stress:
            return []

        # ── ÖFFNUNG: SOC_MODE=manual, SOC_MIN=5%, SOC_MAX=75% ──
        aktionen = []
        pv_sr1h = obs.pv_at_sunrise_1h_w or 0
        soc_str = f"{obs.batt_soc_pct:.0f}" if obs.batt_soc_pct is not None else "?"

        if obs.soc_mode != 'manual':
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_mode', 'wert': 'manual',
                'grund': 'Morgen-Öffnung: SOC_MODE → manual',
            })

        aktionen.append({
            'tier': 2, 'aktor': 'batterie',
            'kommando': 'set_soc_min', 'wert': stress,
            'grund': (f'Morgen-Öffnung: PV@SR+1h={pv_sr1h:.0f}W ≥ Schwelle '
                      f'→ SOC_MIN→{stress}% (SOC={soc_str}%)'),
        })

        if obs.soc_max is None or obs.soc_max != komfort_max:
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_max', 'wert': komfort_max,
                'grund': (f'Morgen-SOC_MAX-Begrenzung: '
                          f'{obs.soc_max or "?"}%→{komfort_max}% '
                          f'(LFP-Schonung)'),
            })

        # Hinweis: registriere_aktion() erfolgt NACH Actuator-Erfolg in engine.py (K2)

        return aktionen


# ═════════════════════════════════════════════════════════════
# NACHMITTAG SOC_MAX (P2 — Steuerung, strategic)
# ═════════════════════════════════════════════════════════════

class RegelNachmittagSocMax(Regel):
    """SOC_MAX nachmittags erhöhen: Mehr Kapazität vor Abend.

    *** CLEAR-SKY-PEAK + LEISTUNGSSCHWELLEN-ALGORITHMUS ***
    Ziel: SOC_MAX=100% öffnen, wenn die PV-Leistung nachhaltig
    unter die Schwelle (default 7 kW) absinkt — ausgehend vom
    Clear-Sky-Peak.

    Parametermatrix: regelkreise.nachmittag_soc_max
    """

    name = 'nachmittag_soc_max'
    regelkreis = 'nachmittag_soc_max'
    engine_zyklus = 'strategic'

    def _effektive_schwelle_w(self, obs: ObsState, matrix: dict) -> float:
        """Öffnungsschwelle unter Berücksichtigung aktiver Großverbraucher."""
        basis_w = get_param(matrix, self.regelkreis, 'oeffnungsschwelle_kw', 7) * 1000

        verbraucher_w = 0.0
        if obs.ev_power_avg30_w and obs.ev_power_avg30_w > 1000:
            verbraucher_w += obs.ev_power_avg30_w
        elif obs.ev_charging and obs.ev_power_w:
            verbraucher_w += obs.ev_power_w
        if obs.wp_power_avg30_w and obs.wp_power_avg30_w > 500:
            verbraucher_w += obs.wp_power_avg30_w
        elif obs.wp_active and obs.wp_power_w:
            verbraucher_w += obs.wp_power_w

        eff = basis_w + verbraucher_w
        if verbraucher_w > 100:
            LOG.debug(f"nachmittag SOC_MAX: Schwelle {basis_w / 1000:.0f} kW "
                      f"+ Verbraucher {verbraucher_w / 1000:.1f} kW "
                      f"(WP avg30={obs.wp_power_avg30_w or 0:.0f}W, "
                      f"EV avg30={obs.ev_power_avg30_w or 0:.0f}W) = {eff / 1000:.1f} kW")
        return eff

    def _berechne_dynamische_startzeit(self, obs: ObsState, matrix: dict) -> float:
        """Bestimme optimale Öffnungszeit basierend auf Clear-Sky-Peak."""
        sunset = obs.sunset or 17.0
        schwelle_w = self._effektive_schwelle_w(obs, matrix)
        min_start = get_param(matrix, self.regelkreis, 'start_stunde', 11)
        deadline = sunset - get_param(matrix, self.regelkreis, 'max_stunden_vor_sunset', 1.5)

        peak_h = obs.clearsky_peak_h
        profil = obs.forecast_power_profile

        if peak_h is None or not profil:
            fb = max(min_start, deadline - 1.0)
            LOG.info(f"nachmittag SOC_MAX: Kein Profil/Peak → Fallback {fb:.1f}h")
            return fb

        profil_sorted = sorted(profil, key=lambda p: p.get('hour', 0))
        nach_peak = [p for p in profil_sorted if p['hour'] >= int(peak_h)]
        if not nach_peak:
            fb = max(min_start, deadline - 1.0)
            LOG.info(f"nachmittag SOC_MAX: Kein Profil nach Peak {peak_h:.1f}h → {fb:.1f}h")
            return fb

        peak_int = int(peak_h)
        stunde_nach_peak = [p for p in profil_sorted
                            if peak_int <= p['hour'] <= peak_int + 1]
        if stunde_nach_peak:
            avg_nach_peak = sum(p.get('total_ac_w', 0) for p in stunde_nach_peak) / len(stunde_nach_peak)
            if avg_nach_peak < schwelle_w:
                start = max(min_start, peak_h)
                LOG.info(f"nachmittag SOC_MAX: Schwacher Tag — 1h nach Peak "
                         f"∅{avg_nach_peak / 1000:.1f} kW < {schwelle_w / 1000:.0f} kW "
                         f"→ öffne bei Peak {start:.1f}h")
                return start

        for p in nach_peak:
            if p.get('total_ac_w', 0) < schwelle_w:
                start = max(min_start, float(p['hour']))
                LOG.info(f"nachmittag SOC_MAX: Prognose {p.get('total_ac_w', 0) / 1000:.1f} kW "
                         f"< {schwelle_w / 1000:.0f} kW ab {p['hour']}h → Start {start:.1f}h "
                         f"(Peak {peak_h:.1f}h)")
                return start

        start = max(min_start, deadline)
        LOG.info(f"nachmittag SOC_MAX: Prognose bleibt >{schwelle_w / 1000:.0f} kW → "
                 f"Deadline-Start {start:.1f}h")
        return start

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # ── SOC-Extern-Toleranz ──
        soc_extern_tracker.aktualisiere(obs, matrix)
        if soc_extern_tracker.ist_toleriert(matrix):
            verbleibend = soc_extern_tracker.verbleibend_s(matrix)
            LOG.debug(f'{self.name}: SOC extern geändert '
                      f'({soc_extern_tracker.extern_grund}) '
                      f'→ toleriert ({verbleibend}s verbleibend)')
            return 0

        now = datetime.now()
        hr = now.hour + now.minute / 60.0

        stress_max = get_param(matrix, self.regelkreis, 'stress_max_pct', 100)
        if obs.soc_max is not None and obs.soc_max >= stress_max:
            return 0

        score_max = get_score_gewicht(matrix, self.regelkreis)
        sunset = obs.sunset or 17.0

        if hr > sunset:
            return 0

        hours_left = max(0, sunset - hr)
        max_h = get_param(matrix, self.regelkreis, 'max_stunden_vor_sunset', 1.5)

        if hours_left <= max_h:
            return score_max

        dyn_start = self._berechne_dynamische_startzeit(obs, matrix)
        if hr < dyn_start:
            return 0

        total_window = max(0.1, sunset - dyn_start)
        elapsed_frac = min(1.0, (hr - dyn_start) / total_window)
        score_frac = 0.60 + 0.35 * elapsed_frac

        wolken = get_param(matrix, self.regelkreis, 'wolken_schwer_pct', 85)
        cloud_val = obs.cloud_rest_avg_pct if obs.cloud_rest_avg_pct is not None else obs.cloud_avg_pct
        if cloud_val is not None and cloud_val > wolken:
            score_frac = min(0.95, score_frac + 0.10)

        return int(score_max * score_frac)

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        komfort = get_param(matrix, self.regelkreis, 'komfort_max_pct', 75)
        stress = get_param(matrix, self.regelkreis, 'stress_max_pct', 100)
        aktionen = []

        if obs.soc_mode != 'manual':
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_mode', 'wert': 'manual',
                'grund': 'Nachmittag-SOC_MAX: SOC_MODE → manual',
            })

        sunset = obs.sunset or 17.0
        now_h = datetime.now().hour + datetime.now().minute / 60.0
        peak_h = obs.clearsky_peak_h

        peak_str = f"Peak {peak_h:.1f}h" if peak_h else "Peak ?"
        dyn_start = self._berechne_dynamische_startzeit(obs, matrix)

        aktionen.append({
            'tier': 2, 'aktor': 'batterie',
            'kommando': 'set_soc_max', 'wert': stress,
            'grund': (f'Nachmittag: SOC_MAX {komfort}%→{stress}%, '
                      f'{sunset - now_h:.1f}h bis Sunset, '
                      f'{peak_str}, Öffnung ab {dyn_start:.1f}h'),
        })

        # Hinweis: registriere_aktion() erfolgt NACH Actuator-Erfolg in engine.py (K2)

        return aktionen


# ═════════════════════════════════════════════════════════════
# KOMFORT-RESET (P2 — Steuerung, fast)
# ═════════════════════════════════════════════════════════════

class RegelKomfortReset(Regel):
    """Täglicher Reset auf Komfort-SOC-Bereich (25–75%).

    Timing:
      - Abend-Fenster: sunset + offset_h  bis  sunrise → normaler Reset
      - Früh-Reset (nachmittags): SOC_MIN noch auf Stress (5%) UND
        Prognose reicht NICHT mehr aus um Batterie auf 25% zu laden
        → SOC_MIN sofort auf 25% (erzwingt Netzladung)
      - Erholung: Wenn forecast_rest_kwh > Schwelle (10 kWh),
        bleibt SOC_MIN bei 5% — PV kann Batterie noch aufladen
        (z.B. nach Gewitter-Dip)

    Parametermatrix: regelkreise.komfort_reset
    """

    name = 'komfort_reset'
    regelkreis = 'komfort_reset'
    engine_zyklus = 'fast'

    def __init__(self):
        self._frueh_reset_aktiv = False  # Hysterese-State für Früh-Reset (K4)

    def _im_reset_fenster(self, obs: ObsState, matrix: dict) -> bool:
        """Prüfe ob aktuelle Uhrzeit im Abend-Reset-Fenster liegt."""
        now = datetime.now()
        hr = now.hour + now.minute / 60.0
        sunset = obs.sunset or 17.0
        sunrise = obs.sunrise or 7.0
        offset = get_param(matrix, self.regelkreis, 'reset_nach_sunset_h', 0)
        start = sunset + offset

        if start >= 24:
            start -= 24
            return hr >= start or hr < sunrise
        if hr >= start:
            return True
        if hr < sunrise:
            return True
        return False

    def _morgenfenster_sperrt_reset(self, obs: ObsState) -> bool:
        """Sperrt Komfort-Reset bei guter Prognose ab Sunrise-1h.

        Verhindert Konflikte mit der Morgen-Öffnung (SOC_MIN=5%), damit
        SOC_MIN in der kritischen Vor-Sunrise-Phase nicht auf 25% zurückspringt.
        """
        if obs.forecast_quality != 'gut':
            return False

        sunrise = obs.sunrise
        if sunrise is None:
            return False

        now_h = datetime.now().hour + datetime.now().minute / 60.0
        return now_h > (sunrise - 1.0)

    def _frueh_reset_noetig(self, obs: ObsState, matrix: dict) -> bool:
        """Nachmittags: Prognose-Rest zu gering → SOC_MIN sofort auf 25%.

        Bedingungen:
          1. SOC_MIN auf Stress (5%) → Morgen-Öffnung war aktiv
          2. Nachmittag (nach frueh_reset_ab_h, vor Sunset)
          3. forecast_rest_kwh < erholung_schwelle_kwh
             → Zu wenig PV-Ertrag erwartet → sofort auf 25%

        Hysterese (K4): Verwendet zwei Schwellen um Flickern zu vermeiden:
          - ON:  forecast_rest < erholung_schwelle_kwh (10 kWh)
          - OFF: forecast_rest >= erholung_schwelle_kwh + hysterese_kwh (12 kWh)
          Sobald Früh-Reset aktiv, wird er erst ab höherer Schwelle aufgehoben.
        """
        # Nur relevant wenn SOC_MIN noch auf Stress-Level
        komfort_min = get_param(matrix, self.regelkreis, 'komfort_min_pct', 25)
        if obs.soc_min is None or obs.soc_min >= komfort_min:
            self._frueh_reset_aktiv = False  # Reset-State bei Komfort-Level
            return False

        # Zeitprüfung: erst ab nachmittags, vor Sunset
        now_h = datetime.now().hour + datetime.now().minute / 60.0
        ab_h = get_param(matrix, self.regelkreis, 'frueh_reset_ab_h', 13.0)
        sunset = obs.sunset or 17.0
        if now_h < ab_h or now_h > sunset:
            return False

        # Hysterese-Schwellen (K4)
        erholung = get_param(matrix, self.regelkreis, 'erholung_schwelle_kwh', 10.0)
        hysterese = get_param(matrix, self.regelkreis, 'erholung_hysterese_kwh', 2.0)
        rest_kwh = obs.forecast_rest_kwh

        if self._frueh_reset_aktiv:
            # Bereits im Früh-Reset → nur aufheben wenn ÜBER obere Schwelle
            obere_schwelle = erholung + hysterese
            if rest_kwh is not None and rest_kwh >= obere_schwelle:
                LOG.info(f"komfort_reset: Früh-Reset AUFGEHOBEN — forecast_rest="
                         f"{rest_kwh:.1f} kWh ≥ {obere_schwelle:.0f} kWh "
                         f"(Hysterese-Schwelle überschritten)")
                self._frueh_reset_aktiv = False
                return False
            # Unter oberer Schwelle → Früh-Reset bleibt aktiv
            LOG.debug(f"komfort_reset: Früh-Reset bleibt aktiv — forecast_rest="
                      f"{rest_kwh or 0:.1f} kWh < {obere_schwelle:.0f} kWh")
            return True
        else:
            # Noch kein Früh-Reset → erst auslösen wenn UNTER untere Schwelle
            if rest_kwh is not None and rest_kwh >= erholung:
                LOG.debug(f"komfort_reset: forecast_rest={rest_kwh:.1f} kWh "
                          f"≥ {erholung:.0f} kWh → Erholung möglich, kein Früh-Reset")
                return False

            # Prognose-Rest < Schwelle → Früh-Reset aktivieren
            LOG.info(f"komfort_reset FRÜH-RESET: forecast_rest="
                     f"{rest_kwh or 0:.1f} kWh < {erholung:.0f} kWh "
                     f"→ SOC_MIN jetzt auf {komfort_min}%")
            self._frueh_reset_aktiv = True
            return True

    def _soc_weicht_ab(self, obs: ObsState, matrix: dict) -> bool:
        """Prüfe ob SOC-Werte vom Komfort-Bereich abweichen."""
        komfort_min = get_param(matrix, self.regelkreis, 'komfort_min_pct', 25)
        komfort_max = get_param(matrix, self.regelkreis, 'komfort_max_pct', 75)

        if obs.soc_min is not None and obs.soc_min != komfort_min:
            return True
        if obs.soc_max is not None and obs.soc_max != komfort_max:
            return True
        if obs.soc_mode is not None and obs.soc_mode != 'manual':
            return True
        return False

    def _nachtladung_vermeidbar(self, obs: ObsState, matrix: dict) -> bool:
        """Prüft ob SOC_MIN-Reset auf 25% übersprungen werden kann.

        SOC_MIN bleibt nur dann bei 5% (kein Reset), wenn BEIDE Bedingungen
        erfüllt sind:
          1. Batterie hat noch genug Ladung (SOC > komfort_min) → kein
             Langzeit-Stress bei niedrigem SOC über Nacht
          2. Morgen-Prognose gut genug → PV morgen lädt natürlich auf

        Ist SOC bereits ≤ komfort_min, wird IMMER auf Komfort zurückgesetzt
        (Grid-Ladung), um stundenlangen Stress-Zustand zu vermeiden.

        Returns:
            True → SOC_MIN-Reset überspringen (SOC hoch + morgen genug PV).
        """
        komfort_min = get_param(matrix, self.regelkreis, 'komfort_min_pct', 25)
        if obs.soc_min is None or obs.soc_min >= komfort_min:
            return False  # SOC_MIN bereits auf Komfort → kein Thema

        # ── SOC-Prüfung: Batterie bereits im Stress-Bereich? ──
        # Wenn SOC ≤ komfort_min → Batterie ist leer, würde stundenlang
        # auf Stress-Level bleiben → IMMER auf Komfort zurücksetzen.
        soc = obs.batt_soc_pct
        if soc is not None and soc <= komfort_min:
            LOG.info(f"komfort_reset: SOC {soc:.0f}% ≤ {komfort_min}% "
                     f"→ bereits im Stress-Bereich, Komfort-Reset nötig")
            return False

        # ── Prognose-Prüfung: Morgen genug PV? ──
        schwelle = get_param(matrix, self.regelkreis, 'nachtlade_schwelle_kwh', 20.0)
        morgen_kwh = obs.forecast_tomorrow_kwh

        if morgen_kwh is not None and morgen_kwh >= schwelle:
            LOG.info(f"komfort_reset: SOC {soc:.0f}% > {komfort_min}%, "
                     f"Morgen-Prognose {morgen_kwh:.1f} kWh ≥ {schwelle:.0f} kWh "
                     f"→ SOC_MIN-Reset übersprungen (draint über Nacht)")
            return True

        if morgen_kwh is not None:
            LOG.debug(f"komfort_reset: Morgen-Prognose {morgen_kwh:.1f} kWh "
                      f"< {schwelle:.0f} kWh → Nachtladung nötig")
        else:
            LOG.debug("komfort_reset: Morgen-Prognose nicht verfügbar "
                      "→ sicherheitshalber Nachtladung")
        return False

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # ── SOC-Extern-Toleranz ──
        soc_extern_tracker.aktualisiere(obs, matrix)
        if soc_extern_tracker.ist_toleriert(matrix):
            verbleibend = soc_extern_tracker.verbleibend_s(matrix)
            LOG.debug(f'{self.name}: SOC extern geändert '
                      f'({soc_extern_tracker.extern_grund}) '
                      f'→ toleriert ({verbleibend}s verbleibend)')
            return 0

        if self._morgenfenster_sperrt_reset(obs):
            return 0

        score = get_score_gewicht(matrix, self.regelkreis)

        # ── Früh-Reset nachmittags (SOC niedrig + Prognose reicht nicht) ──
        if self._frueh_reset_noetig(obs, matrix):
            return score

        # ── Normaler Abend-Reset ──
        if not self._im_reset_fenster(obs, matrix):
            return 0
        if not self._soc_weicht_ab(obs, matrix):
            return 0
        return score

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        komfort_min = get_param(matrix, self.regelkreis, 'komfort_min_pct', 25)
        komfort_max = get_param(matrix, self.regelkreis, 'komfort_max_pct', 75)
        aktionen = []
        now_str = f"{datetime.now().hour}:{datetime.now().minute:02d}"

        if self._morgenfenster_sperrt_reset(obs):
            return []

        frueh = self._frueh_reset_noetig(obs, matrix)

        if obs.soc_mode != 'manual':
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_mode', 'wert': 'manual',
                'grund': f'Komfort-Reset {now_str}: SOC_MODE→manual',
            })

        if frueh:
            # Früh-Reset: nur SOC_MIN anheben (SOC_MAX bleibt wie es ist)
            soc_str = f"{obs.batt_soc_pct:.0f}" if obs.batt_soc_pct is not None else "?"
            rest_str = f"{obs.forecast_rest_kwh:.1f}" if obs.forecast_rest_kwh is not None else "?"
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_min', 'wert': komfort_min,
                'grund': (f'Früh-Reset {now_str}: SOC={soc_str}%, '
                          f'Prognose-Rest={rest_str} kWh reicht nicht '
                          f'für Ladung auf {komfort_min}% '
                          f'→ SOC_MIN {obs.soc_min}%→{komfort_min}%'),
            })
            return aktionen

        # Normaler Abend-Reset: SOC_MIN auf Komfort zurücksetzen,
        # AUSSER die Batterie hat noch genug Ladung UND morgen kommt PV.
        #
        # Batterie noch voll (SOC > 25%): SOC_MIN bei 5% lassen → draint
        #   über Nacht, trifft 5% erst früh → kurzer Stress, Morgen-Algo
        #   übernimmt.  Kein unnötiger Netzbezug heute Nacht.
        # Batterie bereits leer (SOC ≤ 25%): SOC_MIN auf 25% → Grid-Ladung
        #   über Nacht → verhindert stundenlangen Stress-Zustand.
        if obs.soc_min is not None and obs.soc_min != komfort_min:
            if self._nachtladung_vermeidbar(obs, matrix):
                morgen_str = f"{obs.forecast_tomorrow_kwh:.0f}" if obs.forecast_tomorrow_kwh is not None else "?"
                soc_str = f"{obs.batt_soc_pct:.0f}" if obs.batt_soc_pct is not None else "?"
                LOG.info(f"Komfort-Reset {now_str}: SOC_MIN-Reset übersprungen "
                         f"(SOC {soc_str}% > {komfort_min}%, "
                         f"Morgen-Prognose {morgen_str} kWh → draint über Nacht)")
            else:
                aktionen.append({
                    'tier': 2, 'aktor': 'batterie',
                    'kommando': 'set_soc_min', 'wert': komfort_min,
                    'grund': (f'Komfort-Reset {now_str}: SOC_MIN {obs.soc_min}%→{komfort_min}% '
                              f'(Tagesende, LFP-Schonung)'),
                })

        if obs.soc_max is not None and obs.soc_max != komfort_max:
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_max', 'wert': komfort_max,
                'grund': (f'Komfort-Reset {now_str}: SOC_MAX {obs.soc_max}%→{komfort_max}% '
                          f'(Tagesende, LFP-Schonung)'),
            })

        # Entfernt (2026-03-07): Komfort-Reset für StorCtl_Mod → auto
        # GEN24 DC-DC-Wandler begrenzt Batteriestrom auf ~22 A; Modbus-
        # Ratenlimits (InWRte/OutWRte/StorCtl_Mod) waren wirkungslos.

        if aktionen:
            LOG.info(f"Komfort-Reset: {len(aktionen)} Aktion(en) — "
                     f"SOC_MIN={obs.soc_min}→{komfort_min}, "
                     f"SOC_MAX={obs.soc_max}→{komfort_max}, "
                     f"Mode={obs.soc_mode}→manual")

        # Engine-Aktionen registrieren (Extern-Erkennung)
        for a in aktionen:
            soc_extern_tracker.registriere_aktion(a.get('kommando', ''), a.get('wert'))

        return aktionen
