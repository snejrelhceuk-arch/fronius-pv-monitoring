"""
waermepumpe.py — WP-Sollwertregeln (P2, fast-Zyklus)

Regeln:
    - RegelWwAbsenkung   — Nachtabsenkung WW-Solltemperatur (Reg 5047)
    - RegelHeizAbsenkung — Absenkung Heiz-Festwertsolltemperatur (Reg 5037)

ABCD: C-Rolle (Automation Engine) → D (Hardware via Modbus RTU)
Siehe: doc/automation/WP_REGISTER.md
"""

from __future__ import annotations

import logging
from datetime import datetime

from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht,
)

LOG = logging.getLogger('engine')


def _ist_im_zeitfenster(start_h: float, ende_h: float) -> bool:
    """True wenn aktuelle Uhrzeit im (ggf. über-Mitternacht) Fenster liegt."""
    now_h = datetime.now().hour + datetime.now().minute / 60.0
    if start_h > ende_h:
        return now_h >= start_h or now_h < ende_h
    return start_h <= now_h < ende_h


class RegelWwAbsenkung(Regel):
    """WW-Nachtabsenkung: Temperatur nachts senken, morgens wiederherstellen.

    Zeitfenster-Logik (start_h > ende_h → über Mitternacht):
      23:00–03:00  →  Nacht-Soll = standard - absenkung
      03:00–23:00  →  Tag-Soll   = standard

        Schutz:
            - Schreibt nur bei Abweichung (Soll ≠ aktueller WW-Soll)
            - Deaktivierbar via param_matrix (aktiv: false)
    """

    name = 'ww_absenkung'
    regelkreis = 'ww_absenkung'
    aktor = 'waermepumpe'
    engine_zyklus = 'fast'

    def _ist_nachtzeit(self, matrix: dict) -> bool:
        """Prüfe ob aktuelle Uhrzeit im Absenkungsfenster liegt."""
        start = get_param(matrix, self.regelkreis, 'start_h', 23)
        ende = get_param(matrix, self.regelkreis, 'ende_h', 3)
        return _ist_im_zeitfenster(start, ende)

    def _ziel_temp(self, matrix: dict) -> int:
        """Ziel-WW-Soll je nach Tageszeit."""
        standard = get_param(matrix, self.regelkreis, 'standard_temp_c', 57)
        absenkung = get_param(matrix, self.regelkreis, 'absenkung_k', 5)
        if self._ist_nachtzeit(matrix):
            return int(standard - absenkung)
        return int(standard)

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        ziel = self._ziel_temp(matrix)
        aktuell = obs.wp_ww_soll_c

        # Kein aktueller Wert → nicht eingreifen
        if aktuell is None:
            return 0

        # Bereits korrekt? (exakter Vergleich — beide Werte ganzzahlig)
        if int(aktuell) == ziel:
            return 0

        # Änderung nötig
        return get_score_gewicht(matrix, self.regelkreis)

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        ziel = self._ziel_temp(matrix)
        aktuell = obs.wp_ww_soll_c
        ist_nacht = self._ist_nachtzeit(matrix)

        phase = "Nachtabsenkung" if ist_nacht else "Tagwert-Wiederherstellung"
        standard = get_param(matrix, self.regelkreis, 'standard_temp_c', 57)
        absenkung = get_param(matrix, self.regelkreis, 'absenkung_k', 5)

        return [{
            'tier': 2,
            'aktor': 'waermepumpe',
            'kommando': 'set_ww_soll',
            'wert': ziel,
            'grund': (f'WW {phase}: {aktuell}°C → {ziel}°C '
                      f'(Standard {standard}°C, Absenkung {absenkung}K)'),
        }]


class RegelHeizAbsenkung(Regel):
    """Heiz-Nachtabsenkung: Festwertsoll nachts senken, morgens wiederherstellen.

    Zeitfenster-Logik (start_h > ende_h → über Mitternacht):
      18:00–03:00  → Nacht-Soll = standard - absenkung
      03:00–18:00  → Tag-Soll   = standard

    Hinweis:
      - Die Wärmepumpe nutzt intern den Rücklaufbezug; für die Automation
        ist das ohne Bedeutung, gesteuert wird ausschließlich Register 5037.
      - Zielwert wird auf Modbus-Bereich 18..60°C begrenzt.
    """

    name = 'heiz_absenkung'
    regelkreis = 'heiz_absenkung'
    aktor = 'waermepumpe'
    engine_zyklus = 'fast'

    def _ist_absenkzeit(self, matrix: dict) -> bool:
        start = get_param(matrix, self.regelkreis, 'start_h', 18)
        ende = get_param(matrix, self.regelkreis, 'ende_h', 3)
        return _ist_im_zeitfenster(start, ende)

    def _ziel_temp(self, matrix: dict) -> int:
        standard = get_param(matrix, self.regelkreis, 'standard_temp_c', 37)
        absenkung = get_param(matrix, self.regelkreis, 'absenkung_k', 2)
        if self._ist_absenkzeit(matrix):
            return max(18, int(standard - absenkung))
        return int(standard)

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        ziel = self._ziel_temp(matrix)
        aktuell = obs.wp_heiz_soll_c

        if aktuell is None:
            return 0
        if int(aktuell) == ziel:
            return 0
        return get_score_gewicht(matrix, self.regelkreis)

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        ziel = self._ziel_temp(matrix)
        aktuell = obs.wp_heiz_soll_c
        ist_absenkung = self._ist_absenkzeit(matrix)

        phase = "Absenkung" if ist_absenkung else "Tagwert-Wiederherstellung"
        standard = get_param(matrix, self.regelkreis, 'standard_temp_c', 37)
        absenkung = get_param(matrix, self.regelkreis, 'absenkung_k', 2)

        return [{
            'tier': 2,
            'aktor': 'waermepumpe',
            'kommando': 'set_heiz_soll',
            'wert': ziel,
            'grund': (f'Heiz-Soll {phase}: {aktuell}°C → {ziel}°C '
                      f'(Standard {standard}°C, Absenkung {absenkung}K)'),
        }]
