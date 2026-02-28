"""
collectors — Datenquellen-Module für den Automation-Daemon

Exportiert:
  Tier1Checker       — Sicherheitskritische Schwellenprüfung (< 1 s)
  BatteryCollector   — Batterie via Modbus + HTTP (5–30 s)
  ForecastCollector  — Solar-Prognose trigger-basiert (Tier 3)
  DataCollector      — Sensor-Daten aus Collector-DB (10 s)
"""

from automation.engine.collectors.tier1_checker import Tier1Checker
from automation.engine.collectors.battery_collector import BatteryCollector
from automation.engine.collectors.forecast_collector import ForecastCollector
from automation.engine.collectors.data_collector import DataCollector

__all__ = [
    'Tier1Checker',
    'BatteryCollector',
    'ForecastCollector',
    'DataCollector',
]
