"""
schutz.py — Sicherheitsregeln (P1, fast-Zyklus)

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

# Keine aktiven Regeln in diesem Modul.
# Importe und Klassen wurden chirurgisch entfernt.
# Git-Historie enthält die vollständige Implementierung.
