"""
engine.py — Entscheidungs-Engine (Schicht S3)

Liest ObsState aus RAM-DB und SOC-Parametermatrix aus
config/soc_param_matrix.json.  Bewertet Regeln per Score-System
und erzeugt einen ActionPlan für den Actuator.

Zyklen:
  Fast-Cycle  (1 min)  — Sicherheit + Entladeraten
  Strat-Cycle (15 min) — SOC_MIN / SOC_MAX Steuerung, Zellausgleich

Tier-1 Alarm-Aktionen werden NICHT hier behandelt — die laufen
direkt im Observer → Actuator Bypass.

Siehe: doc/AUTOMATION_ARCHITEKTUR.md §5
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, date
from typing import Optional

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import automation.engine.obs_state as obs_mod
from automation.engine.obs_state import ObsState, read_obs_state
from automation.engine.actuator import Actuator
from automation.engine.param_matrix import (
    lade_matrix, get_param, ist_aktiv, get_score_gewicht,
    get_regelkreis, DEFAULT_MATRIX_PATH,
)

LOG = logging.getLogger('engine')


def _first_not_none(*values, default=None):
    """Erstes Element das nicht None ist (0 und 0.0 sind gültig!)."""
    for v in values:
        if v is not None:
            return v
    return default


# ═════════════════════════════════════════════════════════════
# Regel-Interface
# ═════════════════════════════════════════════════════════════

class Regel:
    """Basisklasse für Engine-Regeln.

    Jede Regel bewertet den ObsState und gibt 0..100 Score zurück.
    Die Regel mit dem höchsten Score gewinnt.
    """

    name: str = 'unbekannte_regel'
    regelkreis: str = ''           # Schlüssel in param_matrix → regelkreise
    beschreibung: str = ''
    aktor: str = 'batterie'
    engine_zyklus: str = 'fast'    # 'fast' oder 'strategic'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        """Score 0..100, höher = dringender. 0 = nicht anwendbar."""
        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        """Erzeuge Aktion(en) falls diese Regel gewinnt. Kann mehrere sein."""
        return []


# ═════════════════════════════════════════════════════════════
# SOC-SCHUTZ (P1 — Sicherheit, fast)
# ═════════════════════════════════════════════════════════════

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


# ═════════════════════════════════════════════════════════════
# TEMP-SCHUTZ (P1 — Sicherheit, fast)
# ═════════════════════════════════════════════════════════════

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


# ═════════════════════════════════════════════════════════════
# MORGEN SOC_MIN (P2 — Steuerung, strategic)
# ═════════════════════════════════════════════════════════════

class RegelMorgenSocMin(Regel):
    """SOC_MIN morgens öffnen: Batterie entladen + SOC_MAX=75% begrenzen.

    *** PROGNOSEGESTEUERTE MORGEN-ÖFFNUNG ***
    Ziel: Die ~2 kWh nutzbare Kapazität (25%→5%) morgens durch
    Hausverbrauch nutzen, GLEICHZEITIG SOC_MAX=75% halten damit
    PV die Batterie nicht sofort vollladt (LFP-Schonung).

    Timing-Logik (Sonnenaufgang + Wolken-Offset):
      ┌─────────────────┬───────────────┬────────────────────────┐
      │ Wolken-Prognose  │ Offset        │ Aktion                 │
      ├─────────────────┼───────────────┼────────────────────────┤
      │ klar (<30%)      │ SR + 10–30min │ manual 5%–75%          │
      │ mittel (30–70%)  │ SR + 30–60min │ manual 5%–75%          │
      │ bewölkt (>70%)   │ SR + 60–120min│ auto (Fronius entsch.) │
      └─────────────────┴───────────────┴────────────────────────┘

    Bestätigung: Aktivierung erst wenn Live-PV > Schwelle (100W).
    Dies stellt sicher, dass der Sonnenaufgang tatsächlich stattfand
    (nicht nur astronomisch, sondern auch meteorologisch).

    SOC_MAX = 75% wird explizit gesetzt, damit bei fehlenden
    Verbrauchern die Batterie nicht in <1h von PV voll geladen wird.
    Der Nachmittag-Algorithmus öffnet SOC_MAX=100% rechtzeitig.

    HALTE-MODUS: Solange SOC > 7% und wir im Zeitfenster sind,
    hält die Regel einen hohen Score (68) um Rücksetzung durch
    andere Regeln zu verhindern.

    Sonder-Logik bei hoher Ladeleistung: Wenn P_inBatt > 3kW für
    längere Zeit → SOC_MAX=75% reinforcen (falls es jemand erhöht hat).

    Parametermatrix: regelkreise.morgen_soc_min
    """

    name = 'morgen_soc_min'
    regelkreis = 'morgen_soc_min'
    # FAST-Zyklus: Haltemodus muss jede Minute geprüft werden
    engine_zyklus = 'fast'

    def _berechne_offset_min(self, obs: ObsState, matrix: dict) -> float:
        """Wolkenabhängiger Offset nach Sonnenaufgang [Minuten].

        Klar  (<30% Wolken):  10–30 min → PV kommt schnell
        Mittel (30–70%):      30–60 min → PV verzögert
        Bewölkt (>70%):       60–120 min → PV kommt spät/schwach

        Innerhalb jeder Stufe wird linear interpoliert.
        """
        wolken_klar = get_param(matrix, self.regelkreis, 'wolken_klar_pct', 30)
        wolken_schwer = get_param(matrix, self.regelkreis, 'wolken_schwer_pct', 70)

        # Beste Wolken-Quelle: Resttag > Aktuell > Tagesdurchschnitt
        cloud = obs.cloud_rest_avg_pct
        if cloud is None:
            cloud = obs.cloud_now_pct
        if cloud is None:
            cloud = obs.cloud_avg_pct
        if cloud is None:
            cloud = 50  # Konservativ: Mittel

        if cloud < wolken_klar:
            # Klar: 10–30 min
            return 10 + (cloud / wolken_klar) * 20
        elif cloud < wolken_schwer:
            # Mittel: 30–60 min
            anteil = (cloud - wolken_klar) / (wolken_schwer - wolken_klar)
            return 30 + anteil * 30
        else:
            # Bewölkt: 60–120 min
            anteil = min(1.0, (cloud - wolken_schwer) / (100 - wolken_schwer))
            return 60 + anteil * 60

    def _bestimme_modus(self, obs: ObsState, matrix: dict) -> str:
        """Bestimme ob 'manual' (5–75%) oder 'auto' gesetzt wird.

        Klar/Mittel → manual 5%–75% (Kontrolle über SOC_MAX)
        Bewölkt → auto (Fronius entscheidet, weniger Eingriff sinnvoll)
        """
        wolken_schwer = get_param(matrix, self.regelkreis, 'wolken_schwer_pct', 70)
        cloud = _first_not_none(obs.cloud_rest_avg_pct, obs.cloud_now_pct, obs.cloud_avg_pct, default=50)
        if cloud > wolken_schwer:
            return 'auto'
        return 'manual'

    def _aktivierungszeit_erreicht(self, obs: ObsState, matrix: dict) -> bool:
        """Prüfe ob Sonnenaufgang + wolkenabhängiger Offset erreicht ist."""
        now = datetime.now()
        hr = now.hour + now.minute / 60.0
        sunrise = obs.sunrise or 7.0

        offset_min = self._berechne_offset_min(obs, matrix)
        aktivierung = sunrise + offset_min / 60.0

        LOG.debug(f"morgen_soc_min: Aktivierung {aktivierung:.2f}h "
                  f"(Sunrise {sunrise:.2f} + {offset_min:.0f}min), "
                  f"jetzt {hr:.2f}h")
        return hr >= aktivierung

    def _pv_bestaetigt(self, obs: ObsState, matrix: dict) -> bool:
        """Prüfe ob Live-PV tatsächlich produziert (Bestätigung).

        PV > pv_bestaetigung_w (default 100W) = Sonne ist da.
        Dies löst nicht allein die Öffnung aus, aber bestätigt sie.
        """
        schwelle = get_param(matrix, self.regelkreis, 'pv_bestaetigung_w', 100)
        if obs.pv_total_w is not None and obs.pv_total_w >= schwelle:
            return True
        return False

    def _im_zeitfenster(self, obs: ObsState, matrix: dict) -> bool:
        """Prüfe ob wir im Morgen-Fenster sind (Sunrise bis Sunrise+3h)."""
        now = datetime.now()
        hr = now.hour + now.minute / 60.0
        sunrise = obs.sunrise or 7.0
        ende_offset = get_param(matrix, self.regelkreis, 'fenster_ende_nach_sunrise_h', 3)
        ende = sunrise + ende_offset
        # Frühestens ab Sonnenaufgang (nicht 5:00!)
        return sunrise <= hr <= ende

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        if not self._im_zeitfenster(obs, matrix):
            return 0

        # Prognose prüfen — an wirklich schlechten Tagen nicht öffnen
        min_pv = get_param(matrix, self.regelkreis, 'min_prognose_kwh', 5.0)
        if obs.forecast_kwh is not None and obs.forecast_kwh < min_pv:
            return 0

        komfort = get_param(matrix, self.regelkreis, 'komfort_min_pct', 25)
        stress = get_param(matrix, self.regelkreis, 'stress_min_pct', 5)
        komfort_max = get_param(matrix, self.regelkreis, 'morgen_soc_max_pct', 75)
        score = get_score_gewicht(matrix, self.regelkreis)  # 72

        # ── HALTE-MODUS: SOC_MIN bereits geöffnet ──
        if obs.soc_min is not None and obs.soc_min <= stress:
            if obs.batt_soc_pct is not None and obs.batt_soc_pct > stress + 2:
                halte_score = int(score * 0.95)  # 68
                # Bonus: Wenn Ladeleistung > 3kW → SOC_MAX=75% reinforcen
                if (obs.batt_power_w is not None and obs.batt_power_w > 3000
                        and obs.soc_max is not None and obs.soc_max > komfort_max):
                    LOG.info(f"morgen_soc_min HALTE + LADEKONTROLLE: "
                             f"P_in={obs.batt_power_w:.0f}W > 3kW, "
                             f"SOC_MAX={obs.soc_max}% > {komfort_max}% "
                             f"→ SOC_MAX reinforcen")
                    return score  # Vollen Score für Aktion
                LOG.debug(f"morgen_soc_min HALTE: SOC={obs.batt_soc_pct:.1f}%, "
                          f"SOC_MIN={obs.soc_min}% → Score {halte_score}")
                return halte_score
            return 0  # Batterie fast leer → Morgen-Phase beenden

        # ── ÖFFNUNGS-MODUS: Aktivierungszeit + PV-Bestätigung ──
        if not self._aktivierungszeit_erreicht(obs, matrix):
            return 0  # Noch zu früh nach Sonnenaufgang

        if not self._pv_bestaetigt(obs, matrix):
            # PV noch nicht da → kleiner Score (Vormerkung, aber kein Handeln)
            LOG.debug(f"morgen_soc_min: Aktivierungszeit erreicht, "
                      f"aber PV={obs.pv_total_w or 0:.0f}W < Schwelle → warte")
            return 0

        return score  # 72 → ÖFFNEN

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        stress = get_param(matrix, self.regelkreis, 'stress_min_pct', 5)
        komfort = get_param(matrix, self.regelkreis, 'komfort_min_pct', 25)
        komfort_max = get_param(matrix, self.regelkreis, 'morgen_soc_max_pct', 75)
        aktionen = []

        # ── HALTE + LADEKONTROLLE: P_in > 3kW und SOC_MAX zu hoch ──
        if (obs.soc_min is not None and obs.soc_min <= stress
                and obs.batt_power_w is not None and obs.batt_power_w > 3000
                and obs.soc_max is not None and obs.soc_max > komfort_max):
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_max', 'wert': komfort_max,
                'grund': (f'Morgen-Ladekontrolle: P_in={obs.batt_power_w:.0f}W > 3kW, '
                          f'SOC_MAX {obs.soc_max}%→{komfort_max}% '
                          f'(LFP-Schonung, Nachmittag öffnet später)'),
            })
            return aktionen

        # ── HALTE-MODUS: SOC_MIN schon offen → nur Score halten ──
        if obs.soc_min is not None and obs.soc_min <= stress:
            soc_str = f"{obs.batt_soc_pct:.1f}" if obs.batt_soc_pct is not None else "?"
            LOG.info(f"morgen_soc_min: HALTE SOC_MIN={obs.soc_min}% "
                     f"(SOC={soc_str}% → weiter entladen)")
            return []

        # ── ÖFFNUNGS-MODUS ──
        # Wolkenabhängig: manual (5–75%) oder auto
        cloud = _first_not_none(obs.cloud_rest_avg_pct, obs.cloud_now_pct, obs.cloud_avg_pct, default=50)
        wolken_schwer = get_param(matrix, self.regelkreis, 'wolken_schwer_pct', 70)
        modus = self._bestimme_modus(obs, matrix)
        offset = self._berechne_offset_min(obs, matrix)

        pv_str = f"{obs.forecast_kwh:.0f}" if obs.forecast_kwh else "?"
        soc_str = f"{obs.batt_soc_pct:.0f}" if obs.batt_soc_pct else "?"
        pv_live = f"{obs.pv_total_w:.0f}" if obs.pv_total_w else "0"

        if modus == 'auto':
            # Bewölkt: Fronius-Auto, SOC_MIN/MAX bleiben wie Fronius will
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_mode', 'wert': 'auto',
                'grund': (f'Morgen-Öffnung (bewölkt {cloud:.0f}%): '
                          f'SOC_MODE→auto nach SR+{offset:.0f}min, '
                          f'PV={pv_live}W, Prognose {pv_str} kWh'),
            })
        else:
            # Klar/Mittel: manual mit 5%–75%
            if obs.soc_mode != 'manual':
                aktionen.append({
                    'tier': 2, 'aktor': 'batterie',
                    'kommando': 'set_soc_mode', 'wert': 'manual',
                    'grund': 'Morgen-Öffnung: SOC_MODE → manual',
                })

            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_min', 'wert': stress,
                'grund': (f'Morgen-Öffnung (klar/mittel {cloud:.0f}%): '
                          f'SOC_MIN {komfort}%→{stress}% nach SR+{offset:.0f}min, '
                          f'SOC={soc_str}%, PV={pv_live}W, Prognose {pv_str} kWh'),
            })

            # SOC_MAX auf 75% begrenzen (auch wenn schon 75%)
            if obs.soc_max is None or obs.soc_max != komfort_max:
                aktionen.append({
                    'tier': 2, 'aktor': 'batterie',
                    'kommando': 'set_soc_max', 'wert': komfort_max,
                    'grund': (f'Morgen-SOC_MAX-Begrenzung: {obs.soc_max or "?"}%→{komfort_max}% '
                              f'(LFP-Schonung, verhindert Sofort-Volladung durch PV)'),
                })

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

    Algorithmus:
      1. clear-sky peak hour bestimmen (z.B. 12:30)
      2. Ab dem Peak im Stunden-Leistungsprofil (Prognose) den
         ersten Zeitpunkt finden, wo total_ac < schwelle_kw
      3. Falls Prognose 1h nach Peak im Mittel schon < schwelle_kw
         → direkt am Peak öffnen (schwacher Tag)
      4. Deadline: sunset − 1.5h als absolutes Sicherheitsnetz
      5. Wolken-Override: schwere Bewölkung → frühstmöglich

    Parametermatrix: regelkreise.nachmittag_soc_max
    """

    name = 'nachmittag_soc_max'
    regelkreis = 'nachmittag_soc_max'
    engine_zyklus = 'strategic'

    def _effektive_schwelle_w(self, obs: ObsState, matrix: dict) -> float:
        """Öffnungsschwelle unter Berücksichtigung aktiver Großverbraucher.

        Grundidee: Die Schwelle ist "freie PV-Leistung für Batterie".
        Wenn Großverbraucher (EV, WP) laufen, muss die PV-Leistung
        höher sein, bevor die Batterie nachgeladen werden kann.

        Verwendet 30-min Mittelwerte (bevorzugt) statt Snapshots:
        - WP taktet (Kompressor an/aus) → Snapshot 0 oder 3kW, Avg realistisch
        - EV Avg wirkt als Confidence-Fenster: gerade erst angesteckt →
          Avg niedrig, seit 30min am Laden → volles Gewicht

        effektive_schwelle = oeffnungsschwelle + verbraucher_avg30
        """
        basis_w = get_param(matrix, self.regelkreis, 'oeffnungsschwelle_kw', 7) * 1000

        verbraucher_w = 0.0
        # EV: 30-min Avg bevorzugt, Fallback auf Snapshot wenn charging
        if obs.ev_power_avg30_w and obs.ev_power_avg30_w > 1000:
            verbraucher_w += obs.ev_power_avg30_w
        elif obs.ev_charging and obs.ev_power_w:
            verbraucher_w += obs.ev_power_w
        # WP: 30-min Avg bevorzugt, Fallback auf Snapshot wenn aktiv
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
        """Bestimme die optimale Öffnungszeit basierend auf Clear-Sky-Peak.

        Returns: Dezimalstunde ab der SOC_MAX geöffnet werden soll.

        Algorithmus:
          1. Finde Clear-Sky-Peak (Stunde der max. CS-Leistung)
          2. Laufe im Forecast-Power-Profil ab Peak vorwärts
          3. Erste Stunde mit total_ac < effektive Schwelle → Öffnungszeit
             (Schwelle = oeffnungsschwelle_kw + aktive Verbraucher)
          4. Falls 1h nach Peak schon im Mittel < Schwelle → am Peak öffnen
          5. Fallback bei fehlenden Daten: Sunset − 3h
        """
        sunset = obs.sunset or 17.0
        schwelle_w = self._effektive_schwelle_w(obs, matrix)
        min_start = get_param(matrix, self.regelkreis, 'start_stunde', 11)
        deadline = sunset - get_param(matrix, self.regelkreis, 'max_stunden_vor_sunset', 1.5)

        peak_h = obs.clearsky_peak_h
        profil = obs.forecast_power_profile  # [{hour, total_ac_w}, ...]

        # ── Fallback: kein Peak oder kein Profil verfügbar ──
        if peak_h is None or not profil:
            fb = max(min_start, deadline - 1.0)
            LOG.info(f"nachmittag SOC_MAX: Kein Profil/Peak → Fallback {fb:.1f}h")
            return fb

        # ── Profil nach Stunde sortieren (Sicherheit) ──
        profil_sorted = sorted(profil, key=lambda p: p.get('hour', 0))

        # ── Stunden nach dem Peak filtern ──
        nach_peak = [p for p in profil_sorted if p['hour'] >= int(peak_h)]
        if not nach_peak:
            fb = max(min_start, deadline - 1.0)
            LOG.info(f"nachmittag SOC_MAX: Kein Profil nach Peak {peak_h:.1f}h → {fb:.1f}h")
            return fb

        # ── Check: Ist Prognose 1h nach Peak schon im Mittel < Schwelle? ──
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

        # ── Laufe ab Peak vorwärts: erste Stunde < Schwelle ──
        for p in nach_peak:
            if p.get('total_ac_w', 0) < schwelle_w:
                start = max(min_start, float(p['hour']))
                LOG.info(f"nachmittag SOC_MAX: Prognose {p.get('total_ac_w', 0) / 1000:.1f} kW "
                         f"< {schwelle_w / 1000:.0f} kW ab {p['hour']}h → Start {start:.1f}h "
                         f"(Peak {peak_h:.1f}h)")
                return start

        # ── Prognose bleibt den ganzen Tag über Schwelle → Deadline ──
        start = max(min_start, deadline)
        LOG.info(f"nachmittag SOC_MAX: Prognose bleibt >{schwelle_w / 1000:.0f} kW → "
                 f"Deadline-Start {start:.1f}h")
        return start

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        """Fuzzy-Score-Bewertung mit weichem Rampen-Anstieg.

        Architektur:
          - Vor dyn_start:  Score 0  (dyn_start selbst wird fuzzy berechnet
            aus ClearSky-Peak, Prognose-Leistungsprofil, Verbraucherkontext)
          - Ab dyn_start:   Rampe 60%→95% Score (linear bis Sunset)
          - Deadline:       voller Score (100%)

        Fuzzy-Qualität:
          - dyn_start ist nicht hart konfiguriert sondern dynamisch
            berechnet aus Peak + Leistungsprofil + Verbraucher
          - Score steigt stetig mit abnehmender Restzeit
          - Cascade-Mechanismus in Engine garantiert dass die Regel
            auch bei niedrigerem Score ausgeführt wird, wenn stärkere
            Regeln keine Aktionen erzeugen
        """
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        now = datetime.now()
        hr = now.hour + now.minute / 60.0

        # SOC_MAX schon voll?
        stress_max = get_param(matrix, self.regelkreis, 'stress_max_pct', 100)
        if obs.soc_max is not None and obs.soc_max >= stress_max:
            return 0

        score_max = get_score_gewicht(matrix, self.regelkreis)  # 55
        sunset = obs.sunset or 17.0

        # Nach Sunset: Fenster geschlossen → komfort_reset übernimmt
        if hr > sunset:
            return 0

        hours_left = max(0, sunset - hr)
        max_h = get_param(matrix, self.regelkreis, 'max_stunden_vor_sunset', 1.5)

        # ── Deadline: voller Score ──
        if hours_left <= max_h:
            return score_max

        # ── Dynamische Startzeit (fuzzy-berechnet) ──
        dyn_start = self._berechne_dynamische_startzeit(obs, matrix)

        # Vor der berechneten Startzeit → nicht aktiv
        if hr < dyn_start:
            return 0

        # ── Ab dyn_start: Rampe 60%→95% Score ──
        #    Proportional zu verbleibender Zeit bis Sunset
        total_window = max(0.1, sunset - dyn_start)
        elapsed_frac = min(1.0, (hr - dyn_start) / total_window)

        # 60% am Anfang → 95% am Ende (kurz vor Deadline)
        score_frac = 0.60 + 0.35 * elapsed_frac

        # Schwere Bewölkung → Score-Boost (+10%)
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

        # Logging-Details
        peak_str = f"Peak {peak_h:.1f}h" if peak_h else "Peak ?"
        dyn_start = self._berechne_dynamische_startzeit(obs, matrix)

        aktionen.append({
            'tier': 2, 'aktor': 'batterie',
            'kommando': 'set_soc_max', 'wert': stress,
            'grund': (f'Nachmittag: SOC_MAX {komfort}%→{stress}%, '
                      f'{sunset - now_h:.1f}h bis Sunset, '
                      f'{peak_str}, Öffnung ab {dyn_start:.1f}h'),
        })
        return aktionen


# ═════════════════════════════════════════════════════════════
# KOMFORT-RESET (P2 — Steuerung, fast)
# ═════════════════════════════════════════════════════════════

class RegelKomfortReset(Regel):
    """Täglicher Reset auf Komfort-SOC-Bereich (25–75%).

    *** FEHLENDE REGEL DER NEUEN ENGINE (recycelt aus battery_scheduler) ***

    Die Morgen-Regel öffnet SOC_MIN → 5% (Stress), die Nachmittag-Regel
    öffnet SOC_MAX → 100% (Stress).  DIESE Regel schließt beides zurück
    auf Komfort-Defaults (SOC_MIN=25%, SOC_MAX=75%, SOC_MODE=manual,
    StorCtl_Mod=0/auto).

    Timing:
      - Reset-Fenster: sunset + offset_h  bis  sunrise (nächster Tag)
      - Außerhalb dieses Fensters: Score 0 → Morgen/Nachmittag arbeiten
      - Im Fenster, SOC bereits bei Komfort: Score 0 → kein Spam

    Kein Konflikt mit abend_entladerate:
      - abend_entladerate steuert Modbus-Entladerate (set_discharge_rate)
      - komfort_reset steuert HTTP-API (set_soc_min/max/mode) + Modbus auto
      - Cascade: Beim ersten Zyklus gewinnt komfort_reset (höherer Score),
        im nächsten Zyklus ist SOC schon korrekt → Score 0 → abend gewinnt

    Richtungslogik SOC_MAX (recycelt aus battery_scheduler._verify_consistency):
      - SOC_MAX > komfort_max (z.B. 100%) = mehr Ladekapazität = Nutzer/Nachmittag
        wollte das → NICHT korrigieren (bis Reset-Fenster)
      - SOC_MAX < komfort_max = eingeschränkt = IMMER korrigieren

    Parametermatrix: regelkreise.komfort_reset
    """

    name = 'komfort_reset'
    regelkreis = 'komfort_reset'
    engine_zyklus = 'fast'

    def _im_reset_fenster(self, obs: ObsState, matrix: dict) -> bool:
        """Prüfe ob aktuelle Uhrzeit im Reset-Fenster liegt.

        Reset-Fenster: sunset + offset_h  →  sunrise  (über Mitternacht).
        """
        now = datetime.now()
        hr = now.hour + now.minute / 60.0
        sunset = obs.sunset or 17.0
        sunrise = obs.sunrise or 7.0
        offset = get_param(matrix, self.regelkreis, 'reset_nach_sunset_h', 1.0)
        start = sunset + offset

        # Fenster liegt über Mitternacht: start (z.B. 18:30) → sunrise (z.B. 7:00)
        if start >= 24:
            start -= 24
            return hr >= start or hr < sunrise
        if hr >= start:
            return True  # Abend-Teil (z.B. 18:30–24:00)
        if hr < sunrise:
            return True  # Nacht-Teil (0:00–sunrise)
        return False

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

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        if not self._im_reset_fenster(obs, matrix):
            return 0

        if not self._soc_weicht_ab(obs, matrix):
            return 0  # SOC schon bei Komfort → kein Handlungsbedarf

        return get_score_gewicht(matrix, self.regelkreis)  # 70

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        komfort_min = get_param(matrix, self.regelkreis, 'komfort_min_pct', 25)
        komfort_max = get_param(matrix, self.regelkreis, 'komfort_max_pct', 75)
        aktionen = []

        now_str = f"{datetime.now().hour}:{datetime.now().minute:02d}"

        # SOC_MODE → manual (wenn nicht schon)
        if obs.soc_mode != 'manual':
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_mode', 'wert': 'manual',
                'grund': f'Komfort-Reset {now_str}: SOC_MODE auto→manual',
            })

        # SOC_MIN → komfort (wenn abweicht)
        if obs.soc_min is not None and obs.soc_min != komfort_min:
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_min', 'wert': komfort_min,
                'grund': (f'Komfort-Reset {now_str}: SOC_MIN {obs.soc_min}%→{komfort_min}% '
                          f'(Tagesende, LFP-Schonung)'),
            })

        # SOC_MAX → komfort (wenn abweicht)
        if obs.soc_max is not None and obs.soc_max != komfort_max:
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_max', 'wert': komfort_max,
                'grund': (f'Komfort-Reset {now_str}: SOC_MAX {obs.soc_max}%→{komfort_max}% '
                          f'(Tagesende, LFP-Schonung)'),
            })

        # Modbus → auto (Limits aufheben, kein StorCtl_Mod bitfield)
        # Wird NUR gesetzt wenn aktuell Modbus-Limits aktiv sind
        if obs.storctl_mod is not None and obs.storctl_mod != 0:
            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'auto',
                'grund': (f'Komfort-Reset {now_str}: Modbus StorCtl_Mod '
                          f'{obs.storctl_mod}→0 (Limits aufheben)'),
            })

        if aktionen:
            LOG.info(f"Komfort-Reset: {len(aktionen)} Aktion(en) — "
                     f"SOC_MIN={obs.soc_min}→{komfort_min}, "
                     f"SOC_MAX={obs.soc_max}→{komfort_max}, "
                     f"Mode={obs.soc_mode}→manual")

        return aktionen


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
        """Aktuelle Tagesphase bestimmen. Returns (phase_name, rate_pct) or (None, None)."""
        now = datetime.now()
        hr = now.hour + now.minute / 60.0

        abend_ab = get_param(matrix, self.regelkreis, 'abend_start_h', 15)
        abend_bis = get_param(matrix, self.regelkreis, 'abend_ende_h', 0)
        nacht_ab = get_param(matrix, self.regelkreis, 'nacht_start_h', 0)
        nacht_bis = get_param(matrix, self.regelkreis, 'nacht_ende_h', 6)
        abend_rate = get_param(matrix, self.regelkreis, 'abend_rate_pct', 29)
        nacht_rate = get_param(matrix, self.regelkreis, 'nacht_rate_pct', 10)

        # Abend-Phase
        if hr >= abend_ab or (abend_bis > 0 and hr < abend_bis):
            return 'abend', abend_rate
        # Nacht-Phase
        if nacht_ab <= hr < nacht_bis:
            return 'nacht', nacht_rate
        return None, None

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # SOC-Notbremse hat höchsten Score
        kritisch = get_param(matrix, self.regelkreis, 'kritisch_soc_pct', 10)
        if obs.batt_soc_pct is not None and obs.batt_soc_pct < kritisch:
            return get_score_gewicht(matrix, self.regelkreis)

        phase, rate = self._get_phase(matrix)
        if phase is not None:
            return get_score_gewicht(matrix, self.regelkreis)

        # Tag-Phase: ggf. Automatik wiederherstellen
        if obs.storctl_mod is not None and obs.storctl_mod != 0:
            return int(get_score_gewicht(matrix, self.regelkreis) * 0.5)

        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        kritisch = get_param(matrix, self.regelkreis, 'kritisch_soc_pct', 10)

        # SOC-Notbremse
        if obs.batt_soc_pct is not None and obs.batt_soc_pct < kritisch:
            return [{
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'hold',
                'grund': f'SOC-Notbremse: {obs.batt_soc_pct:.1f}% < {kritisch}% → Hold',
            }]

        phase, rate = self._get_phase(matrix)
        if phase is not None:
            # Dedup: Bereits auf Zielrate → keine Aktion (vermeidet 500+ Log-Spam/Tag)
            if obs.discharge_rate_pct is not None and abs(obs.discharge_rate_pct - rate) < 3:
                return []
            return [{
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_discharge_rate',
                'wert': rate,
                'grund': f'{phase.upper()}-Phase: Entladerate auf {rate}%',
            }]

        # Tag → Automatik (dedup: nur wenn StorCtl_Mod != 0)
        if obs.storctl_mod is not None and obs.storctl_mod == 0:
            return []  # Bereits im Auto-Modus
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

        # ── Zyklustracking: Prüfe ob diesen Monat schon erledigt ──
        # Kanonische Quellen: battery_scheduler_state.json (last_balancing)
        # und battery_control.json (letzter_ausgleich) als Fallback.
        letzter = self._letzter_ausgleich()
        if letzter:
            try:
                last_date = datetime.strptime(letzter, '%Y-%m-%d').date()
                heute = date.today()
                if last_date.year == heute.year and last_date.month == heute.month:
                    return 0  # Diesen Monat schon erledigt
            except (ValueError, TypeError):
                pass

        min_pv = get_param(matrix, self.regelkreis, 'min_prognose_kwh', 50.0)
        frueh = get_param(matrix, self.regelkreis, 'fruehester_tag', 1)
        spaet = get_param(matrix, self.regelkreis, 'spaetester_tag', 28)
        tag = date.today().day

        if tag < frueh or tag > spaet:
            return 0

        # Prognose gut genug?
        if obs.forecast_kwh >= min_pv:
            return get_score_gewicht(matrix, self.regelkreis)

        # Notfall-Schwelle prüfen
        notfall = get_param(matrix, self.regelkreis, 'notfall_min_prognose_kwh', 25.0)
        if tag > spaet - 5 and obs.forecast_kwh >= notfall:
            return int(get_score_gewicht(matrix, self.regelkreis) * 0.8)

        return 0

    @staticmethod
    def _letzter_ausgleich() -> Optional[str]:
        """Lese letzten Zellausgleich aus State/Config (analog battery_scheduler.py)."""
        # Primär: Scheduler-State (wird nach jedem Ausgleich geschrieben)
        state_path = os.path.join(_PROJECT_ROOT, 'config', 'battery_scheduler_state.json')
        try:
            with open(state_path) as f:
                state = json.load(f)
            val = state.get('last_balancing')
            if val:
                return val
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

        # Fallback: battery_control.json
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
        return [
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


# ═════════════════════════════════════════════════════════════
# FORECAST-PLAUSIBILISIERUNG (P2 — Steuerung, strategic)
# ═════════════════════════════════════════════════════════════

class RegelForecastPlausi(Regel):
    """PV-Prognose an Realität anpassen.

    Vergleicht bisherige Erzeugung (pv_today_kwh) mit dem erwarteten
    Anteil der Tagesprognose.  Bei > 30% Abweichung → Reduktionsfaktor
    auf forecast_rest_kwh vorschlagen und SOC-Strategie anpassen.

    Nutzt stündliches Wolkenprofil (cloud_rest_avg_pct) als Bestätigung.

    Parametermatrix: regelkreise.forecast_plausibilisierung
    """

    name = 'forecast_plausi'
    regelkreis = 'forecast_plausibilisierung'
    engine_zyklus = 'strategic'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # Braucht IST/SOLL-Verhältnis
        if obs.pv_vs_forecast_pct is None or obs.forecast_rest_kwh is None:
            return 0

        # Erst nach Mindest-Betriebsstunden plausibilisieren
        min_h = get_param(matrix, self.regelkreis, 'min_betriebsstunden', 2.0)
        sunrise = obs.sunrise or 7.0
        now_h = datetime.now().hour + datetime.now().minute / 60.0
        if now_h - sunrise < min_h:
            return 0

        schwelle = get_param(matrix, self.regelkreis, 'abweichung_schwelle_pct', 70)
        if obs.pv_vs_forecast_pct < schwelle:
            score = get_score_gewicht(matrix, self.regelkreis)

            # Schwere Resttag-Bewölkung verstärkt den Score
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

        # Doppelte Reduktion bei schwerer Bewölkung
        eff_faktor = faktor
        if obs.cloud_rest_avg_pct is not None and obs.cloud_rest_avg_pct > cloud_schwer:
            eff_faktor = faktor * cloud_faktor

        rest_korrigiert = round((obs.forecast_rest_kwh or 0) * eff_faktor, 1)
        ist_pct = obs.pv_vs_forecast_pct or 0

        aktionen = []
        # Wenn korrigierte Rest-Prognose nicht reicht → SOC_MAX vorsorglich auf 100%
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
            # Nur loggen, keine Aktion nötig (Rest reicht noch)
            LOG.info(f"Forecast-Plausi: IST/SOLL {ist_pct:.0f}%, Rest {rest_korrigiert} kWh — keine Aktion")
        return aktionen


# ═════════════════════════════════════════════════════════════
# LADERATE DYNAMISCH (P2 — Steuerung, fast)
# ═════════════════════════════════════════════════════════════

class RegelLaderateDynamisch(Regel):
    """Laderate dynamisch steuern: WP-Last, PV-Verfügbarkeit, SOC-Bereich.

    Ergänzt temp_schutz (der nur Temperatur betrachtet) um:
    - WP-Gleichzeitigkeit: Laderate reduzieren wenn WP läuft (Netzlast)
    - PV-abhängig: Volle Laderate nur bei ausreichend PV
    - Komfort/Stress-Bereich: Im Komfort-Bereich schonender laden

    Parametermatrix: regelkreise.laderate_dynamisch
    """

    name = 'laderate_dynamisch'
    regelkreis = 'laderate_dynamisch'
    engine_zyklus = 'fast'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # Nur relevant wenn Batterie lädt (cha_state 4=CHARGING oder batt_power_w > 0)
        is_charging = False
        if obs.cha_state is not None and obs.cha_state == 4:
            is_charging = True
        elif obs.batt_power_w is not None and obs.batt_power_w > 100:
            is_charging = True

        if not is_charging:
            return 0

        score = get_score_gewicht(matrix, self.regelkreis)  # 45

        # WP-Gleichzeitigkeit → höherer Score
        if obs.wp_active:
            return int(score * 1.2)  # 54 — dringender weil Netzlast

        return score

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        komfort_rate = get_param(matrix, self.regelkreis, 'komfort_max_laderate_pct', 80)
        stress_rate = get_param(matrix, self.regelkreis, 'stress_max_laderate_pct', 100)
        wp_rate = get_param(matrix, self.regelkreis, 'wp_aktiv_reduktion_pct', 60)
        min_pv = get_param(matrix, self.regelkreis, 'pv_min_fuer_vollladung_w', 5000)

        # Bestimme Laderate
        rate = stress_rate  # Standard: voll

        # 1. WP läuft → drosseln (höchste Prio bei Laderate)
        if obs.wp_active:
            rate = min(rate, wp_rate)
            grund_detail = f'WP aktiv ({obs.wp_power_w or 0:.0f}W) → Laderate auf {rate}%'
        # 2. Im Komfort-Bereich LFP-schonend laden
        elif (obs.batt_soc_pct is not None and 25 <= obs.batt_soc_pct <= 75):
            rate = min(rate, komfort_rate)
            grund_detail = f'Komfort-Bereich (SOC {obs.batt_soc_pct:.0f}%) → Laderate {rate}%'
        # 3. PV zu schwach für volle Ladung
        elif obs.pv_total_w is not None and obs.pv_total_w < min_pv:
            # Proportional: bei 2500W von 5000W → 50% der max Rate
            pv_ratio = obs.pv_total_w / min_pv
            rate = max(30, int(stress_rate * pv_ratio))
            grund_detail = f'PV {obs.pv_total_w:.0f}W < {min_pv}W → Laderate {rate}%'
        else:
            grund_detail = f'Stress-Bereich, PV ausreichend → Laderate {rate}%'

        # Aktuelle Rate schon korrekt?
        if obs.charge_rate_pct is not None and abs(obs.charge_rate_pct - rate) < 5:
            return []  # Keine Änderung nötig

        return [{
            'tier': 2, 'aktor': 'batterie',
            'kommando': 'set_charge_rate',
            'wert': rate,
            'grund': f'Laderate dynamisch: {grund_detail}',
        }]


# ═════════════════════════════════════════════════════════════
# WATTPILOT BATTERIESCHUTZ (P1 — Sicherheit, fast)
# ═════════════════════════════════════════════════════════════

class RegelWattpilotBattSchutz(Regel):
    """Batterieschutz bei WattPilot-EV-Ladung.

    Logik (3 Stufen):
    1. SOC > drosselung_ab (50%): Wolke OK — Batterie hilft kurz mit → kein Eingriff
    2. SOC ≤ drosselung_ab (50%): Entladerate auf 0.3C (≈30%) reduzieren
    3. SOC ≤ SOC_MIN + puffer: SOC_MIN anheben → Netzladung erzwingen → Nutzerhinweis

    Wenn WattPilot nicht im Eco-Modus: Nutzer will schnell laden,
    Netzbezug ist akzeptiert → Hinweis aber kein Veto.

    Parametermatrix: regelkreise.wattpilot_battschutz
    """

    name = 'wattpilot_battschutz'
    regelkreis = 'wattpilot_battschutz'
    engine_zyklus = 'fast'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # Ist WattPilot aktiv?
        schwelle = get_param(matrix, self.regelkreis, 'ev_leistung_schwelle_w', 2000)
        ev_aktiv = False
        if obs.ev_charging:
            ev_aktiv = True
        elif obs.ev_power_w is not None and obs.ev_power_w > schwelle:
            ev_aktiv = True

        if not ev_aktiv:
            return 0

        # Entlädt die Batterie gerade? (batt_power_w < 0 = Entladung)
        if obs.batt_power_w is not None and obs.batt_power_w >= 0:
            return 0  # Batterie lädt oder idle — kein Schutz nötig

        score = get_score_gewicht(matrix, self.regelkreis)  # 60

        # Stufe 3: SOC nahe SOC_MIN → höchster Score
        puffer = get_param(matrix, self.regelkreis, 'soc_min_puffer_pct', 5)
        soc_min_eff = obs.soc_min or 10
        if obs.batt_soc_pct is not None and obs.batt_soc_pct <= soc_min_eff + puffer:
            return int(score * 1.3)  # 78 — kritisch, fast Schutz-Niveau

        # Stufe 2: SOC unter Drosselungs-Schwelle
        drosselung = get_param(matrix, self.regelkreis, 'soc_drosselung_ab_pct', 50)
        if obs.batt_soc_pct is not None and obs.batt_soc_pct <= drosselung:
            return score

        # Stufe 1: SOC > drosselung — kurze Wolke OK
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
            # SOC_MIN anheben damit Wechselrichter Batterie schützt
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
            # Nur ändern wenn aktuelle Rate höher
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
        self._burst_start: float = 0    # Zeitpunkt letztes Einschalten
        self._burst_ende: float = 0     # geplantes Burst-Ende (Epoch)
        self._letzte_aus: float = 0     # Zeitpunkt letztes Ausschalten

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        """Score für HP-Steuerung.

        Zwei Pfade:
          1. Notaus (HP AUS) — IMMER aktiv, auch bei aktiv=False
             Schützt gegen Batterie-Entladung/Netzbezug/Phase 4.
             Läuft im Engine fast-cycle (60s) — kein Tier-1 nötig.
          2. Burst-EIN — nur bei aktiv=True (Strategie).
        """
        now_h = datetime.now().hour + datetime.now().minute / 60
        sunset = obs.sunset or 17.0
        rest_h = max(0, sunset - now_h)
        p_batt = obs.batt_power_w
        score = get_score_gewicht(matrix, self.regelkreis)  # 40

        # ── Notaus-Pfad: IMMER aktiv (unabhängig von aktiv-Flag) ──
        if obs.heizpatrone_aktiv:
            notaus_netz = get_param(matrix, self.regelkreis, 'notaus_netzbezug_w', 200)
            notaus_soc_schwelle = get_param(matrix, self.regelkreis, 'notaus_soc_schwelle_pct', 90)
            notaus_entlade_hochsoc = get_param(matrix, self.regelkreis, 'notaus_entladung_hochsoc_w', -1000)
            min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
            temp_max = get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78)

            # Harte Abschalt-Bedingungen
            if rest_h < min_rest_h:
                return int(score * 1.5)  # 60 — Phase 4 HARD BLOCK

            # SOC-abhängige Entlade-Schwelle:
            #   SOC >= 90%: toleriere bis -1000W (konfigurierbar)
            #   SOC <  90%: jede Entladung → AUS
            if p_batt is not None and p_batt < 0:
                soc_now = obs.batt_soc_pct or 0
                if soc_now >= notaus_soc_schwelle:
                    # Hoch-SOC: toleranter Schwellwert
                    if p_batt < notaus_entlade_hochsoc:
                        return int(score * 1.5)
                else:
                    # Unter Schwelle: jede Entladung → AUS
                    return int(score * 1.5)
            if obs.grid_power_w is not None and obs.grid_power_w > notaus_netz:
                return int(score * 1.5)  # Netzbezug
            if obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
                return int(score * 1.5)  # Übertemperatur

            # Burst-Timer abgelaufen → ausschalten
            if self._burst_ende > 0 and time.time() >= self._burst_ende:
                return int(score * 1.2)

            # Burst läuft noch → weiter (auch ohne aktiv=True)
            if self._burst_ende > 0 and time.time() < self._burst_ende:
                return score

        # ── Burst-EIN-Pfad: nur bei aktiv=True ────────────────
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        rest_kwh = obs.forecast_rest_kwh
        soc = obs.batt_soc_pct
        soc_max_eff = obs.soc_max or 75

        # Kein Scoring ohne Basisdaten
        if p_batt is None or rest_kwh is None or soc is None:
            return 0

        min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)

        # Phase 4: HARD BLOCK — kein Burst starten
        if rest_h < min_rest_h:
            return 0

        # WP-Speicher Übertemperatur — kein Burst
        temp_max = get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78)
        if obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
            return 0

        # ── Hysterese: Mindestpause nach letztem Ausschalten ──
        min_pause = get_param(matrix, self.regelkreis, 'min_pause_s', 300)
        if (not obs.heizpatrone_aktiv and self._letzte_aus > 0
                and (time.time() - self._letzte_aus) < min_pause):
            return 0

        # ── batt_rest_kwh: wieviel fehlt bis Batterie voll? ──
        batt_rest_kwh = max(0, (soc_max_eff - soc) * 10.24 / 100)

        # EV-Ladung prüfen
        max_wp = get_param(matrix, self.regelkreis, 'max_wattpilot_w', 500)
        ev_aktiv = (obs.ev_power_w or 0) > max_wp

        # ── Phase 1: Vormittags (rest_h>5, gute Prognose) ────
        min_lade_morgens = get_param(matrix, self.regelkreis, 'min_ladeleistung_morgens_w', 3000)
        min_rest_kwh_morgens = get_param(matrix, self.regelkreis, 'min_rest_kwh_morgens', 20.0)
        min_rest_h_morgens = get_param(matrix, self.regelkreis, 'min_rest_h_morgens', 5.0)

        if rest_h > min_rest_h_morgens and rest_kwh > min_rest_kwh_morgens:
            if p_batt > min_lade_morgens:
                return score  # 40 — Burst erlaubt

        # ── Phase 2+3: Mittags/Nachmittags ────────────────────
        min_lade = get_param(matrix, self.regelkreis, 'min_ladeleistung_w', 5000)
        min_rest = get_param(matrix, self.regelkreis, 'min_rest_kwh', 12.0)
        reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)

        # Nachmittags spät: strengere Reserve
        if rest_h < 3.0:
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_nachmittag_kwh', 3.0)

        if p_batt > min_lade and not ev_aktiv:
            if rest_kwh > batt_rest_kwh + reserve:
                return score

        # Guter Tag (>min_rest_kwh) aber Batt lädt erst moderat (>min_lade)
        if rest_kwh > min_rest and p_batt > min_lade:
            return score

        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        """HP ein-/ausschalten: Notaus + Burst-Strategie.

        Notaus (AUS) läuft IMMER — schützt Batterie/Netz.
        Burst (EIN) nur bei aktiv=True.
        Beides im Engine fast-cycle (60s).
        """
        now_h = datetime.now().hour + datetime.now().minute / 60
        sunset = obs.sunset or 17.0
        rest_h = max(0, sunset - now_h)
        rest_kwh = obs.forecast_rest_kwh or 0
        p_batt = obs.batt_power_w or 0
        soc = obs.batt_soc_pct if obs.batt_soc_pct is not None else 50
        soc_max_eff = obs.soc_max if obs.soc_max is not None else 75

        # ── HP ist EIN → Notaus prüfen (IMMER, auch aktiv=False) ──
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

            # HP läuft ohne Notaus-Grund → keine Aktion
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

        # Phase 1: Vormittags mit guter Prognose
        if rest_h > min_rest_h_morgens and rest_kwh > min_rest_kwh_morgens:
            if p_batt > min_lade_morgens:
                burst_dauer = burst_lang
                grund = (f'Phase 1 (Vormittag): P_Batt={p_batt:.0f}W, '
                         f'rest_kwh={rest_kwh:.1f}, rest_h={rest_h:.1f}')

        # Phase 2: Mittags — Batterie lädt kräftig
        if not burst_dauer and p_batt > min_lade:
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)
            max_wp = get_param(matrix, self.regelkreis, 'max_wattpilot_w', 500)
            ev_aktiv = (obs.ev_power_w or 0) > max_wp

            if rest_kwh > batt_rest_kwh + reserve and not ev_aktiv:
                burst_dauer = burst_lang if rest_kwh > min_rest_kwh_morgens else burst_kurz
                grund = (f'Phase 2 (Mittag): P_Batt={p_batt:.0f}W, '
                         f'rest_kwh={rest_kwh:.1f}, batt_rest={batt_rest_kwh:.1f}')

        # Phase 3: Nachmittags spät — konservativ
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


# ═════════════════════════════════════════════════════════════
# Engine
# ═════════════════════════════════════════════════════════════

class Engine:
    """Score-basierte Entscheidungs-Engine.

    Lifecycle:
      1. Lade Parametermatrix (config/soc_param_matrix.json)
      2. Lese ObsState aus RAM-DB
      3. Bewerte alle registrierten Regeln gegen Matrix + ObsState
      4. Regeln mit höchstem Score gewinnen → ActionPlan
      5. ActionPlan an Actuator dispatchen

    Zyklen:
      fast (1 min)      — soc_schutz, temp_schutz, abend_entladerate
      strategic (15 min) — morgen_soc_min, nachmittag_soc_max, zellausgleich
    """

    def __init__(self, actuator: Actuator, dry_run: bool = False,
                 matrix_path: str = DEFAULT_MATRIX_PATH):
        self.actuator = actuator
        self.dry_run = dry_run
        self._matrix_path = matrix_path
        self._matrix: dict = {}
        self._regeln: list[Regel] = []
        self._ram_db_conn = None
        self._lade_matrix()
        self._register_default_regeln()

    def _lade_matrix(self):
        """Lade Parametermatrix von Disk."""
        try:
            self._matrix = lade_matrix(self._matrix_path)
            LOG.info(f"Parametermatrix geladen: {self._matrix_path}")
        except Exception as e:
            LOG.error(f"Parametermatrix nicht ladbar: {e}")
            self._matrix = {'regelkreise': {}}

    def reload_matrix(self):
        """Parametermatrix neu laden (z.B. nach Config-Änderung)."""
        self._lade_matrix()
        LOG.info("Parametermatrix neu geladen")

    def _register_default_regeln(self):
        """Alle SOC-Regeln registrieren."""
        self._regeln = [
            RegelSocSchutz(),
            RegelTempSchutz(),
            RegelKomfortReset(),
            RegelAbendEntladerate(),
            RegelMorgenSocMin(),
            RegelNachmittagSocMax(),
            RegelZellausgleich(),
            RegelForecastPlausi(),
            RegelLaderateDynamisch(),
            RegelWattpilotBattSchutz(),
            RegelHeizpatrone(),
        ]
        LOG.info(f"Regeln registriert: {[r.name for r in self._regeln]}")

    def registriere_regel(self, regel: Regel):
        """Zusätzliche Regel registrieren."""
        self._regeln.append(regel)
        LOG.info(f"Regel '{regel.name}' registriert")

    def _get_ram_db(self) -> sqlite3.Connection:
        """Lazy-Init RAM-DB Verbindung (readonly)."""
        if self._ram_db_conn is None:
            db_path = obs_mod.RAM_DB_PATH
            if not os.path.exists(db_path):
                raise RuntimeError(f"RAM-DB nicht gefunden: {db_path}")
            self._ram_db_conn = sqlite3.connect(
                f'file:{db_path}?mode=ro', uri=True, timeout=3.0
            )
        return self._ram_db_conn

    # ── Haupt-Zyklus ─────────────────────────────────────────

    def zyklus(self, zyklus_typ: str = 'fast') -> list[dict]:
        """Ein Engine-Zyklus: Bewerte → Entscheide → Handle.

        Args:
            zyklus_typ: 'fast' (1 min) oder 'strategic' (15 min)

        Returns:
            Liste der ausgeführten Aktionen (Ergebnisse)
        """
        # 1. ObsState lesen
        try:
            conn = self._get_ram_db()
            obs = read_obs_state(conn)
        except Exception as e:
            LOG.error(f"ObsState nicht lesbar: {e}")
            self._ram_db_conn = None
            return []

        if obs is None:
            LOG.warning("Kein ObsState vorhanden — überspringe Zyklus")
            return []

        # 2. Alarm-Flags prüfen (Tier-1 hat Vorrang → Engine pausiert)
        if obs.alarm_batt_temp or obs.alarm_batt_kritisch:
            LOG.info(f"Tier-1 Alarm aktiv — Engine-Zyklus '{zyklus_typ}' übersprungen "
                     f"(batt_temp={obs.alarm_batt_temp}, batt_krit={obs.alarm_batt_kritisch})")
            return []

        # 3. Regeln bewerten (nur passende Zyklen)
        scores: list[tuple[int, Regel]] = []
        for regel in self._regeln:
            if zyklus_typ == 'fast' and regel.engine_zyklus == 'strategic':
                continue
            try:
                score = regel.bewerte(obs, self._matrix)
                if score > 0:
                    scores.append((score, regel))
                    LOG.debug(f"  Regel '{regel.name}': Score {score}")
            except Exception as e:
                LOG.error(f"  Regel '{regel.name}' Fehler: {e}")

        if not scores:
            LOG.debug(f"Zyklus '{zyklus_typ}': Keine Regel aktiv")
            return []

        # 4. Schutz-Regeln und Optimierungs-Regeln trennen
        #    Schutz-Regeln werden ALLE ausgeführt (parallel-safe: versch. Aktoren),
        #    Optimierung: nur der Gewinner pro Aktor-Cascade.
        #    Schutz = Name enthält 'schutz' ODER Regel nutzt fremden Aktor
        #    mit erhöhtem Score (= Notaus, z.B. heizpatrone→fritzdect).
        def _ist_schutz(score, regel):
            if 'schutz' in regel.name:
                return True
            # HP-Notaus: fritzdect-Aktor mit erhöhtem Score (>score_gewicht)
            if regel.aktor == 'fritzdect' and score > get_score_gewicht(self._matrix, regel.regelkreis):
                return True
            return False

        schutz_scores = [(s, r) for s, r in scores if _ist_schutz(s, r)]
        optim_scores  = [(s, r) for s, r in scores if not _ist_schutz(s, r)]

        ergebnisse = []

        # 4a. Alle aktiven Schutz-Regeln ausführen (absteigend nach Score)
        schutz_scores.sort(key=lambda x: x[0], reverse=True)
        for score, regel in schutz_scores:
            LOG.info(f"Zyklus '{zyklus_typ}': Schutz-Regel '{regel.name}' (Score {score})")
            try:
                aktionen = regel.erzeuge_aktionen(obs, self._matrix)
                if aktionen:
                    teil_ergebnisse = self.actuator.ausfuehren_plan(aktionen)
                    for e in teil_ergebnisse:
                        LOG.info(f"  → {e.get('kommando')} = {'OK' if e.get('ok') else 'FEHLER'}")
                    ergebnisse.extend(teil_ergebnisse)
            except Exception as e:
                LOG.error(f"Aktionen erzeugen fehlgeschlagen '{regel.name}': {e}")

        # 4b. Optimierungs-Regeln: Gewinner first, Cascade bei leerer Aktion
        #     Wenn der Score-Gewinner keine Aktionen erzeugt (z.B.
        #     forecast_plausi entscheidet "keine Aktion nötig"), wird der
        #     nächstbeste Kandidat versucht.  So blockiert eine Score-hohe
        #     aber passiv bleibende Regel nie eine niedrigere aktive Regel.
        if optim_scores:
            optim_scores.sort(key=lambda x: x[0], reverse=True)

            for winner_score, winner in optim_scores:
                LOG.info(f"Zyklus '{zyklus_typ}': Gewinner '{winner.name}' (Score {winner_score})")

                try:
                    aktionen = winner.erzeuge_aktionen(obs, self._matrix)
                except Exception as e:
                    LOG.error(f"Aktionen erzeugen fehlgeschlagen '{winner.name}': {e}")
                    continue

                if aktionen:
                    # 6. An Actuator dispatchen
                    teil_ergebnisse = self.actuator.ausfuehren_plan(aktionen)
                    for e in teil_ergebnisse:
                        LOG.info(f"  → {e.get('kommando')} = {'OK' if e.get('ok') else 'FEHLER'}")
                    ergebnisse.extend(teil_ergebnisse)
                    break  # Erster Gewinner mit Aktionen → fertig
                else:
                    LOG.info(f"  '{winner.name}' hat keine Aktionen → Cascade zum Nächsten")

        return ergebnisse

    # ── Cleanup ──────────────────────────────────────────────

    def close(self):
        if self._ram_db_conn:
            self._ram_db_conn.close()
            self._ram_db_conn = None
