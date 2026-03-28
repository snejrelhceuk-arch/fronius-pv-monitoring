"""
schutz.py — Sicherheitsregeln (P1, fast-Zyklus)

RegelSlsSchutz — SLS-Sicherungsschutz 35A am Zähler

HINWEIS (2026-03-07): RegelSocSchutz und RegelTempSchutz wurden entfernt.

Begründung:
  - Der GEN24 12.0 DC-DC-Wandler begrenzt den Batteriestrom hardwareseitig
    auf ~22 A (≈9,5 kW). Software-Ratenlimits via InWRte/OutWRte/StorCtl_Mod
    waren wirkungslos.
  - SOC_MIN via Fronius HTTP-API steuert die Entlade-Erlaubnis implizit.
    Der Wechselrichter stoppt die Entladung automatisch bei SOC_MIN.
  - BMS regelt Temperatur-Schutz selbständig (LFP-Zellchemie).
  - Tier-1 (tier1_checker.py) setzt weiterhin Alarm-Flags für Dashboard/Logging.

Historische Regeln:
  RegelSocSchutz   — Harte SOC-Grenzen via stop_discharge/set_discharge_rate
  RegelTempSchutz  — Graduelle Laderate-Reduktion via set_charge_rate

Siehe: doc/SCHUTZREGELN.md SR-BAT-01, SR-BAT-02
"""

from __future__ import annotations

import logging
import time

from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.param_matrix import (
    get_param, get_score_gewicht,
)

LOG = logging.getLogger('engine')


# ═════════════════════════════════════════════════════════════
# SLS-SCHUTZ (P1 — Sicherheit, fast)
# ═════════════════════════════════════════════════════════════

class RegelSlsSchutz(Regel):
    """SLS-Sicherungsschutz: Phasenströme am Netz-SmartMeter (F1) überwachen.

    Der SLS (Selektiver Leitungsschutzschalter) am Zählerplatz ist konfigurierbar
    (Standard 35A/3-phasig, mittelfristig 50A nach Anschlussänderung).
    Maximale Gesamtleistung: √3 × 400V × I_SLS.
    Der SLS ist träge — exakte Schwelle reicht, plus kleine Sicherheitsmarge.

    Szenario: 2 EVs laden mit WattPilot (bis 32A), dazu Haushaltslasten
    (WP, HP, Backofen etc.) → Summe kann SLS-Grenze pro Phase überschreiten.
    Die WattPiloten managen ihre 32A intern, aber nicht die Summe mit Haushalt.

    Messung:
      Phasenströme I_L1_Netz, I_L2_Netz, I_L3_Netz aus dem Fronius SmartMeter
      (Netz, am Zählerplatz F1). Liegen in raw_data und werden via
      DataCollector → ObsState.i_l1_netz_a/i_l2_netz_a/i_l3_netz_a bereitgestellt.

    Auslösung:
      max(I_L1, I_L2, I_L3) > sls_strom_max_a → proportional reduzieren.
      Fallback: grid_power_w > sls_leistung_max_w wenn Phasenströme
      nicht verfügbar (z.B. SmartMeter-Ausfall).

    Aktionen (proportional, nicht pauschal):
      1. HP AUS (falls wider Erwarten noch an) — via fritzdect
      2. Wattpilot-Strom um (Überschreitung + Sicherheitsmarge) reduzieren
         Beispiel: I_L1=38A, Grenze=35A, Marge=2A → Reduktion um 5A

    Konfigurierbare Parameter (via pv-config TUI):
      sls_strom_max_a         — SLS-Grenze pro Phase [30–63A], Default 35A
      sls_leistung_max_w      — Fallback Gesamtleistung [W]
      sls_sicherheitsmarge_a  — Sicherheitspuffer [1–5A], Default 2A

    Harte Schutzregel: immer aktiv, nicht deaktivierbar.
    Name enthält 'schutz' → Engine führt sie immer parallel aus.

    Parametermatrix: regelkreise.sls_schutz
    """

    name = 'sls_schutz'
    regelkreis = 'sls_schutz'
    aktor = 'wattpilot'   # Primärer Aktor (kann mehrere Aktoren nutzen)
    engine_zyklus = 'fast'

    def __init__(self):
        super().__init__()
        self._letztes_log: float = 0   # Throttle: max 1× pro 5 Min loggen

    # ── Hilfsmethode: Phasenströme auswerten ─────────────────

    def _phase_max(self, obs: ObsState) -> tuple[float | None, str]:
        """Höchsten Phasenstrom bestimmen.

        Returns: (max_strom_a, phase_name) oder (None, '') wenn keine Daten.
        Nur positive Werte (Bezug) zählen — Einspeisung ist kein SLS-Risiko.
        """
        phasen = [
            (obs.i_l1_netz_a, 'L1'),
            (obs.i_l2_netz_a, 'L2'),
            (obs.i_l3_netz_a, 'L3'),
        ]
        # Nur Bezug (positive Ströme) sind relevant
        bezug = [(abs(a), name) for a, name in phasen if a is not None and a > 0]
        if not bezug:
            return None, ''
        return max(bezug, key=lambda x: x[0])

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        """Score > 0 wenn ein Phasenstrom die SLS-Grenze überschreitet.

        Primär: max(I_L1, I_L2, I_L3) > 35A
        Fallback: grid_power_w > 24000W (wenn Phasenströme nicht verfügbar)
        Kein Warn-/Alarm-Split — der SLS löst ohne Vorwarnung aus.
        """
        score = get_score_gewicht(matrix, self.regelkreis)
        sls_a = get_param(matrix, self.regelkreis, 'sls_strom_max_a', 35.0)
        sls_w = get_param(matrix, self.regelkreis, 'sls_leistung_max_w', 24000)

        # Primär: Phasenströme
        i_max, phase = self._phase_max(obs)
        if i_max is not None:
            if i_max > sls_a:
                return int(score * 1.5)
            return 0

        # Fallback: Gesamtleistung (wenn keine Phase-Daten)
        gw = obs.grid_power_w
        if gw is not None and gw > sls_w:
            return int(score * 1.5)

        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        """Proportionale Lastbegrenzung bei SLS-Überstrom.

        Strategie: Nicht pauschale Abregelung auf Minimum, sondern nur um den
        Überlastungsstrom + Sicherheitsmarge reduzieren.

        sls_sicherheitsmarge_a (Default 2A) sorgt für kleinen Puffer.

        Kaskade:
          1. HP AUS (falls an) — via fritzdect
          2. Wattpilot proportional reduzieren — via wattpilot (reduce_current)
             Ziel-Ampere = aktuell_amp - (i_max - sls_grenze) - sicherheitsmarge
        """
        sls_a = get_param(matrix, self.regelkreis, 'sls_strom_max_a', 35.0)
        sls_w = get_param(matrix, self.regelkreis, 'sls_leistung_max_w', 24000)
        marge_a = get_param(matrix, self.regelkreis, 'sls_sicherheitsmarge_a', 2.0)
        aktionen = []

        # Bestimme Auslöse-Grund und Überschreitungsbetrag
        i_max, phase = self._phase_max(obs)
        gw = obs.grid_power_w or 0
        ueberschreitung_a = 0.0

        if i_max is not None and i_max > sls_a:
            ueberschreitung_a = i_max - sls_a
            grund_text = (f'SLS: {phase}={i_max:.1f}A > {sls_a:.0f}A '
                          f'(L1={obs.i_l1_netz_a or 0:.1f}A, '
                          f'L2={obs.i_l2_netz_a or 0:.1f}A, '
                          f'L3={obs.i_l3_netz_a or 0:.1f}A, '
                          f'P_Netz={gw:.0f}W)')
        else:
            # Fallback: Leistungsbasierte Schätzung
            if gw > sls_w:
                ueberschreitung_a = (gw - sls_w) / 230.0  # grobe Näherung
            grund_text = (f'SLS Fallback: P_Netz={gw:.0f}W > {sls_w}W '
                          f'(≈{gw / 400 / 1.73:.0f}A, keine Phasendaten)')

        # Reduktionsbetrag = Überschreitung + Sicherheitsmarge
        reduktion_a = ueberschreitung_a + marge_a

        # HP aus (Sicherheitshalber — ist typischerweise schon aus)
        if obs.heizpatrone_aktiv:
            aktionen.append({
                'tier': 1, 'aktor': 'fritzdect',
                'kommando': 'hp_aus',
                'grund': f'{grund_text} → HP AUS',
            })

        # Wattpilot proportional reduzieren (nur wenn EV lädt)
        ev_w = obs.ev_power_w or 0
        if ev_w > 500:
            # Ziel-Ampere berechnen: aktuell minus Reduktion
            # ev_power_w / (phases × 230V) ≈ aktueller EV-Strom
            ev_phases = 3  # Annahme 3-phasig (konservativ)
            ev_strom_geschaetzt_a = ev_w / (ev_phases * 230)
            ziel_a = max(6, int(ev_strom_geschaetzt_a - reduktion_a))

            aktionen.append({
                'tier': 1, 'aktor': 'wattpilot',
                'kommando': 'reduce_current',
                'parameter': {'ampere': ziel_a},
                'grund': (f'{grund_text} → Wattpilot {ev_strom_geschaetzt_a:.0f}A→{ziel_a}A '
                          f'(Reduktion {reduktion_a:.1f}A inkl. {marge_a:.0f}A Marge)'),
            })

        # Log-Throttle (nicht bei jedem 60s-Zyklus loggen)
        now = time.time()
        if now - self._letztes_log > 300:
            LOG.warning(grund_text)
            self._letztes_log = now

        return aktionen
