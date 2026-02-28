"""
regeln — Engine-Regeln für die PV-Automation

Exportiert alle Regel-Klassen für die Engine-Registrierung.

Module:
  basis          — Regel-Basisklasse
  schutz         — SOC-Schutz, Temp-Schutz (P1, fast)
  soc_steuerung  — Morgen SOC_MIN, Nachmittag SOC_MAX, Komfort-Reset (P2, mixed)
  optimierung    — Abend-Entladerate, Zellausgleich, Forecast-Plausi, Laderate (P2-P3, mixed)
  geraete        — WattPilot-Battschutz, Heizpatrone (P1-P2, fast)
"""

from automation.engine.regeln.basis import Regel
from automation.engine.regeln.schutz import RegelSocSchutz, RegelTempSchutz
from automation.engine.regeln.soc_steuerung import (
    RegelMorgenSocMin, RegelNachmittagSocMax, RegelKomfortReset,
)
from automation.engine.regeln.optimierung import (
    RegelAbendEntladerate, RegelZellausgleich,
    RegelForecastPlausi, RegelLaderateDynamisch,
)
from automation.engine.regeln.geraete import RegelWattpilotBattSchutz, RegelHeizpatrone

__all__ = [
    'Regel',
    'RegelSocSchutz', 'RegelTempSchutz',
    'RegelMorgenSocMin', 'RegelNachmittagSocMax', 'RegelKomfortReset',
    'RegelAbendEntladerate', 'RegelZellausgleich',
    'RegelForecastPlausi', 'RegelLaderateDynamisch',
    'RegelWattpilotBattSchutz', 'RegelHeizpatrone',
]
