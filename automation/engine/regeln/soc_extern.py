"""
soc_extern.py — Toleranz für externe SOC-Änderungen (Fronius App)

Erkennt wenn SOC_MIN/SOC_MAX außerhalb der Automation geändert wurden
(z.B. manuell in der Fronius App) und stellt eine Toleranzperiode
bereit, in der die Engine die Werte nicht überschreibt.

Muster: Analog zur HP-Extern-Erkennung (geraete.py, extern_respekt_s).
Siehe: doc/BATTERIE_STRATEGIEN.md
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from automation.engine.obs_state import ObsState
from automation.engine.param_matrix import get_param

LOG = logging.getLogger('engine')


class SocExternTracker:
    """Erkennt extern geänderte SOC-Werte und stellt Toleranzperiode bereit.

    Verwendet als Module-Level-Singleton. Alle SOC-Regeln referenzieren
    dieselbe Instanz, damit die Erkennung regelübergreifend funktioniert.

    Ablauf:
      1. Regel ruft aktualisiere(obs, matrix) am Anfang von bewerte()
      2. Tracker vergleicht obs.soc_min/soc_max mit den letzten bekannten Werten
      3. Wenn Werte sich geändert haben UND kein Engine-Kommando dafür registriert
         → Extern-Änderung erkannt → Toleranzperiode startet
      4. Regel prüft ist_toleriert(matrix) → True → Score = 0 (Engine überschreibt nicht)
      5. Nach Ablauf von extern_respekt_s → Regel arbeitet wieder normal

    Sicherheit:
      Schutz-Regeln (soc_schutz, temp_schutz) sind NICHT betroffen —
      sie operieren via Modbus (set_discharge_rate, stop_*), nicht via SOC HTTP API.
    """

    _GRACE_S = 300  # Engine-Aktionen bis zu 5 Min nach Erzeugung als "eigene" akzeptieren

    def __init__(self):
        self._prev_min: Optional[int] = None
        self._prev_max: Optional[int] = None
        # Engine-registrierte Sollwerte (aus erzeuge_aktionen)
        self._engine_set_min: Optional[int] = None
        self._engine_set_min_ts: float = 0
        self._engine_set_max: Optional[int] = None
        self._engine_set_max_ts: float = 0
        # Extern-Erkennung
        self._extern_ts: float = 0
        self._extern_grund: str = ''
        # Pro-Zyklus Guard
        self._letzter_zyklus_ts: float = 0

    def aktualisiere(self, obs: ObsState, matrix: dict) -> None:
        """Einmal pro Engine-Zyklus aufrufen (idempotent innerhalb eines Zyklus).

        Vergleicht aktuelle SOC-Werte mit vorherigen, erkennt externe Änderungen.
        """
        now = time.time()
        # Idempotenz: maximal einmal pro Sekunde (gleicher Zyklus)
        if now - self._letzter_zyklus_ts < 1.0:
            return
        self._letzter_zyklus_ts = now

        soc_min = obs.soc_min
        soc_max = obs.soc_max

        # ── SOC_MIN Prüfung ──
        if (self._prev_min is not None and soc_min is not None
                and soc_min != self._prev_min):
            if self._ist_engine_aktion(
                    self._engine_set_min, self._engine_set_min_ts, soc_min):
                LOG.debug(f'SOC_MIN {self._prev_min}%→{soc_min}%: '
                          f'Engine-Aktion erkannt → kein Extern')
                self._engine_set_min = None  # Matched → consumed
            else:
                self._extern_ts = now
                self._extern_grund = f'SOC_MIN {self._prev_min}%→{soc_min}%'
                respekt_s = get_param(matrix, 'soc_extern', 'extern_respekt_s', 1800)
                LOG.info(f'SOC extern geändert erkannt: {self._extern_grund} '
                         f'→ Toleranz {respekt_s}s aktiv')

        # ── SOC_MAX Prüfung ──
        if (self._prev_max is not None and soc_max is not None
                and soc_max != self._prev_max):
            if self._ist_engine_aktion(
                    self._engine_set_max, self._engine_set_max_ts, soc_max):
                LOG.debug(f'SOC_MAX {self._prev_max}%→{soc_max}%: '
                          f'Engine-Aktion erkannt → kein Extern')
                self._engine_set_max = None
            else:
                self._extern_ts = now
                self._extern_grund = f'SOC_MAX {self._prev_max}%→{soc_max}%'
                respekt_s = get_param(matrix, 'soc_extern', 'extern_respekt_s', 1800)
                LOG.info(f'SOC extern geändert erkannt: {self._extern_grund} '
                         f'→ Toleranz {respekt_s}s aktiv')

        self._prev_min = soc_min
        self._prev_max = soc_max

    def _ist_engine_aktion(self, pending_wert: Optional[int],
                           pending_ts: float, obs_wert: int) -> bool:
        """Prüfe ob eine beobachtete Änderung von der Engine stammt."""
        if pending_wert is None:
            return False
        return obs_wert == pending_wert and (time.time() - pending_ts) < self._GRACE_S

    def registriere_aktion(self, kommando: str, wert) -> None:
        """Von erzeuge_aktionen() aufrufen: Engine-Kommando registrieren.

        Damit wird die nächste beobachtete Änderung als Engine-eigen erkannt
        und nicht als Extern-Änderung gewertet.
        """
        now = time.time()
        if kommando == 'set_soc_min':
            self._engine_set_min = wert
            self._engine_set_min_ts = now
        elif kommando == 'set_soc_max':
            self._engine_set_max = wert
            self._engine_set_max_ts = now

    def ist_toleriert(self, matrix: dict) -> bool:
        """Ist die Toleranzperiode für externe SOC-Änderungen aktiv?

        Returns: True → SOC-Regeln sollen KEINE Aktionen erzeugen.
        """
        if self._extern_ts <= 0:
            return False
        respekt_s = get_param(matrix, 'soc_extern', 'extern_respekt_s', 1800)
        if respekt_s <= 0:
            return False
        elapsed = time.time() - self._extern_ts
        return elapsed < respekt_s

    def verbleibend_s(self, matrix: dict) -> int:
        """Verbleibende Sekunden der Toleranzperiode."""
        if self._extern_ts <= 0:
            return 0
        respekt_s = get_param(matrix, 'soc_extern', 'extern_respekt_s', 1800)
        return max(0, int(respekt_s - (time.time() - self._extern_ts)))

    @property
    def extern_grund(self) -> str:
        """Beschreibung der letzten erkannten Extern-Änderung."""
        return self._extern_grund


# ── Module-Level Singleton ───────────────────────────────────
soc_extern_tracker = SocExternTracker()
