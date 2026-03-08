"""
basis.py — Regel-Basisklasse und Hilfsfunktionen

Alle konkreten Regeln erben von Regel und überschreiben
bewerte() und erzeuge_aktionen().

Siehe: doc/AUTOMATION_ARCHITEKTUR.md §5
"""

from __future__ import annotations

from automation.engine.obs_state import ObsState


def _first_not_none(*values, default=None):
    """Erstes Element das nicht None ist (0 und 0.0 sind gültig!)."""
    for v in values:
        if v is not None:
            return v
    return default


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
