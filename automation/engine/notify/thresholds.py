"""
automation/engine/notify/thresholds.py — reine Schwellwert-Auswertung.

Prüft ein ObsState-Feld gegen eine Schwellwert-Definition. Zustandslos —
verbatim aus EventNotifier._schwelle_verletzt extrahiert (Refactor 2026-06-29).
"""

from __future__ import annotations

from automation.engine.obs_state import ObsState


def schwelle_verletzt(obs: ObsState, threshold: dict) -> bool:
    """Prüfe ob ein ObsState-Feld eine Schwelle verletzt."""
    feld = threshold.get('obs_feld', '')
    op = threshold.get('op', '>=')
    schwelle = threshold.get('schwelle', 0)

    wert = getattr(obs, feld, None)
    if wert is None:
        return False

    if op == '>=':
        return wert >= schwelle
    elif op == '<=':
        return wert <= schwelle
    elif op == '<':
        return wert < schwelle
    elif op == '>':
        return wert > schwelle
    elif op == '==':
        return wert == schwelle
    return False
