"""
regeln — Engine-Regeln für die PV-Automation

Exportiert alle Regel-Klassen für die Engine-Registrierung.

Module:
  basis          — Regel-Basisklasse
  schutz         — (entfernt 2026-03-07, GEN24 HW-Limit)
  soc_steuerung  — Morgen SOC_MIN, Nachmittag SOC_MAX, Komfort-Reset (P2, mixed)
  optimierung    — Zellausgleich, Forecast-Plausi (P2-P3, strategic)
  geraete        — WattPilot-Battschutz, Heizpatrone (P1-P2, fast)
"""

from automation.engine.regeln.basis import Regel
from automation.engine.regeln.schutz import RegelSlsSchutz
from automation.engine.regeln.soc_steuerung import (
    RegelMorgenSocMin, RegelNachmittagSocMax, RegelKomfortReset,
)
from automation.engine.regeln.optimierung import (
    RegelZellausgleich, RegelForecastPlausi,
)
# optimierung.py: RegelAbendEntladerate, RegelLaderateDynamisch entfernt (2026-03-07)
from automation.engine.regeln.geraete import RegelWattpilotBattSchutz, RegelHeizpatrone

__all__ = [
    'Regel',
    'RegelSlsSchutz',
    'RegelMorgenSocMin', 'RegelNachmittagSocMax', 'RegelKomfortReset',
    'RegelZellausgleich', 'RegelForecastPlausi',
    'RegelWattpilotBattSchutz', 'RegelHeizpatrone',
]
