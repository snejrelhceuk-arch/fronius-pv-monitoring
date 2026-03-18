"""
waermepumpe.py — WW-Absenkungsregel (P2, fast-Zyklus)

RegelWwAbsenkung — Nachtabsenkung WW-Solltemperatur via Modbus RTU

Nachts (konfigurierbar, Default 23–03 Uhr) wird die WW-Solltemperatur
um einen konfigurierbaren Betrag gesenkt (Default 5 K: 57°C → 52°C).
Morgens wird der Standard-Sollwert wiederhergestellt.

Parameter (soc_param_matrix.json → regelkreise.ww_absenkung):
  standard_temp_c  — WW-Soll Tageswert (55–62°C, Default 57)
  absenkung_k      — Absenkung in Kelvin (1–10 K, Default 5)
  start_h          — Beginn Nachtmodus (20–23 Uhr, Default 23)
  ende_h           — Ende Nachtmodus (0–5 Uhr, Default 3)

Aktor:  waermepumpe → set_ww_soll (Register 5047)
ABCD:   C-Rolle (Automation Engine) → D (Hardware via Modbus RTU)
Siehe:  doc/automation/WP_REGISTER.md §6.2
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


class RegelWwAbsenkung(Regel):
    """WW-Nachtabsenkung: Temperatur nachts senken, morgens wiederherstellen.

    Zeitfenster-Logik (start_h > ende_h → über Mitternacht):
      23:00–03:00  →  Nacht-Soll = standard - absenkung
      03:00–23:00  →  Tag-Soll   = standard

    Schutz:
      - Schreibt nur bei Abweichung (Soll ≠ aktueller WW-Soll)
      - Toleranz ±1°C für Hysterese (Modbus-Rundung / WP-interne Logik)
      - Deaktivierbar via param_matrix (aktiv: false)
    """

    name = 'ww_absenkung'
    regelkreis = 'ww_absenkung'
    aktor = 'waermepumpe'
    engine_zyklus = 'fast'

    def _ist_nachtzeit(self, matrix: dict) -> bool:
        """Prüfe ob aktuelle Uhrzeit im Absenkungsfenster liegt."""
        now_h = datetime.now().hour + datetime.now().minute / 60.0
        start = get_param(matrix, self.regelkreis, 'start_h', 23)
        ende = get_param(matrix, self.regelkreis, 'ende_h', 3)

        # Fenster über Mitternacht (z.B. 23–03)
        if start > ende:
            return now_h >= start or now_h < ende
        # Fenster innerhalb eines Tages (z.B. 22–23 — ungewöhnlich aber möglich)
        return start <= now_h < ende

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
