"""Zentrale SOC-Bewertungsbänder (Komfort/Stress) aus battery_control.json.

Rollenübergreifend read-only (B-Routes, C-Mail/Automation, D-Diagnos). Liefert
die EINE systemweite Definition der vier Monitoring-Grenzen:

  komfort_min / komfort_max  — Komfortband (Normalbetrieb, LFP-schonend)
  stress_low  / stress_high  — Stressband (Haltbarkeits-Metrik)

Die Zeit *außerhalb Komfort* (SOC < komfort_min oder > komfort_max) schließt die
*Stresszeit* (SOC < stress_low oder > stress_high) ein, solange
stress_low <= komfort_min <= komfort_max <= stress_high gilt.

Editierbar in pv-config (Batterie-Menü) → schreibt battery_control.json.
"""

from __future__ import annotations

import json
import os

_BATTERY_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'config', 'battery_control.json')

# Fallbacks, falls die Config fehlt/korrupt ist (Historie bleibt stabil).
_DEFAULT = {
    'komfort_min': 20, 'komfort_max': 80,
    'stress_low': 10, 'stress_high': 90,
}


def lade_soc_baender() -> dict:
    """Liefert {komfort_min, komfort_max, stress_low, stress_high} als int.

    Best-effort: fehlende Einzelwerte werden aus den Defaults ergänzt.
    """
    werte = dict(_DEFAULT)
    try:
        with open(_BATTERY_CONFIG_PATH, encoding='utf-8') as f:
            g = json.load(f).get('soc_grenzen', {})
        for k in _DEFAULT:
            if g.get(k) is not None:
                werte[k] = int(g[k])
    except Exception:
        pass
    return werte
