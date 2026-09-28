"""
geraete.py — Aggregator der geraete-spezifischen Regeln (Rolle C, fast-Zyklus).

Re-Export der Regel-Klassen aus den geraeteweisen Modulen. Haelt die
String-Importpfade (`automation.engine.regeln.geraete.RegelX` in registry.py /
engine_registry.json) und die direkten Importe (regeln/__init__.py,
operator_overrides.py) stabil.

  geraete_wattpilot_schutz.py — RegelWattpilotBattSchutz
  geraete_heizpatrone.py      — RegelHeizpatrone
  geraete_klimaanlage.py      — RegelKlimaanlage (+ Engine-Ein-Bridge-Helfer)
  geraete_fbh_nacht.py        — RegelFussbodenheizungNacht
"""
from __future__ import annotations

from automation.engine.regeln.geraete_wattpilot_schutz import RegelWattpilotBattSchutz
from automation.engine.regeln.geraete_heizpatrone import RegelHeizpatrone
from automation.engine.regeln.geraete_klimaanlage import (
    RegelKlimaanlage,
    registriere_klima_engine_ein,
    klima_engine_ein_kuerzlich,
)
from automation.engine.regeln.geraete_fbh_nacht import RegelFussbodenheizungNacht

__all__ = [
    'RegelWattpilotBattSchutz',
    'RegelHeizpatrone',
    'RegelKlimaanlage',
    'RegelFussbodenheizungNacht',
    'registriere_klima_engine_ein',
    'klima_engine_ein_kuerzlich',
]
