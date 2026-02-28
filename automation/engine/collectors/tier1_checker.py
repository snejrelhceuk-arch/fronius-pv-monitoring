"""
tier1_checker.py — Tier-1 Schwellenprüfung mit Sofort-Aktion

Deterministisch, nicht verhandelbar, nicht deaktivierbar.
Prüft bei jedem ObsState-Update ob Alarmschwellen überschritten sind.

Schwellen:
  - Batterie-Temperatur (40°C warn, 45°C alarm, Hysterese 38°C)
  - Batterie SOC kritisch (< 5%)
  - Netz-Überlast (24 kW warn, 26 kW alarm)

Siehe: doc/SCHUTZREGELN.md SR-BAT-01, SR-BAT-02
"""

from __future__ import annotations

import logging
from automation.engine.obs_state import ObsState

LOG = logging.getLogger('tier1_checker')


class Tier1Checker:
    """Deterministisch, nicht verhandelbar, nicht deaktivierbar.

    Prüft bei jedem ObsState-Update ob Alarmschwellen überschritten sind.
    Setzt Flags im ObsState UND triggert ggf. Sofort-Aktionen via Actuator.
    """

    def __init__(self, actuator=None, schutz_cfg: dict = None):
        self.actuator = actuator
        self.cfg = schutz_cfg or {}
        # Batterie-spezifisch
        self._batt_temp_warn = self.cfg.get('batt_temp_warn_c', 40)
        self._batt_temp_alarm = self.cfg.get('batt_temp_alarm_c', 45)
        self._batt_temp_reduce_c_rate = self.cfg.get('batt_temp_reduce_c_rate', 0.3)
        self._batt_kapazitaet_kwh = self.cfg.get('batt_kapazitaet_kwh', 10.24)
        self._batt_soc_kritisch = self.cfg.get('batt_soc_kritisch', 5)
        self._netz_ueberlast_warn_w = self.cfg.get('netz_ueberlast_warn_w', 24000)
        self._netz_ueberlast_alarm_w = self.cfg.get('netz_ueberlast_alarm_w', 26000)
        # Zustand für Hysterese
        self._batt_temp_limited = False

    def check(self, obs: ObsState) -> list[dict]:
        """Prüfe alle Tier-1-Schwellen. Gibt Liste der ausgelösten Aktionen zurück."""
        actions = []

        # ── Batterie-Temperatur ──────────────────────────────
        actions.extend(self._check_batt_temp(obs))

        # ── Batterie SOC kritisch ────────────────────────────
        if obs.batt_soc_pct is not None and obs.batt_soc_pct < self._batt_soc_kritisch:
            obs.alarm_batt_kritisch = True
            actions.append({
                'tier': 1,
                'aktor': 'batterie',
                'kommando': 'stop_discharge',
                'grund': f'SOC kritisch: {obs.batt_soc_pct:.1f}% < {self._batt_soc_kritisch}%',
            })
        else:
            obs.alarm_batt_kritisch = False

        # ── Netz-Überlast ────────────────────────────────────
        if obs.grid_power_w is not None:
            if obs.grid_power_w > self._netz_ueberlast_alarm_w:
                obs.alarm_ueberlast = True
                actions.append({
                    'tier': 1,
                    'aktor': 'wattpilot',
                    'kommando': 'set_power',
                    'wert': 1400,  # Minimum
                    'grund': f'Netz-Überlast ALARM: {obs.grid_power_w:.0f}W > {self._netz_ueberlast_alarm_w}W',
                })
            elif obs.grid_power_w > self._netz_ueberlast_warn_w:
                obs.alarm_ueberlast = True
                actions.append({
                    'tier': 1,
                    'aktor': 'wattpilot',
                    'kommando': 'reduce_power',
                    'grund': f'Netz-Überlast WARNUNG: {obs.grid_power_w:.0f}W > {self._netz_ueberlast_warn_w}W',
                })
            else:
                obs.alarm_ueberlast = False

        return actions

    def _check_batt_temp(self, obs: ObsState) -> list[dict]:
        """Batterie-Temperatur-Schutzlogik mit Hysterese.

        Ab 40°C: Ladeleistung auf 0.3C reduzieren (= ~3 kW bei 10.24 kWh)
        Ab 45°C: Ladung komplett stoppen
        Hysterese: Erst bei < 38°C wieder normalisieren
        """
        actions = []
        temp = obs.batt_temp_max_c  # Wärmste Zelle ist maßgeblich

        if temp is None:
            # Kein Temperaturwert → keine Entscheidung, Flag beibehalten
            return actions

        if temp >= self._batt_temp_alarm:
            # ── ALARM: Ladung stoppen ────────────────────────
            obs.alarm_batt_temp = True
            self._batt_temp_limited = True
            actions.append({
                'tier': 1,
                'aktor': 'batterie',
                'kommando': 'set_charge_rate',
                'wert': 0,
                'grund': f'Batterie-Temp ALARM: {temp:.1f}°C ≥ {self._batt_temp_alarm}°C → Ladung STOP',
            })
            LOG.critical(f"TIER-1 ALARM: Batterie-Temp {temp:.1f}°C ≥ {self._batt_temp_alarm}°C → Ladung STOP")

        elif temp >= self._batt_temp_warn:
            # ── WARNUNG: Ladeleistung auf 0.3C reduzieren ────
            obs.alarm_batt_temp = True
            self._batt_temp_limited = True
            # 0.3C = 0.3 × 10.24 kW = 3.072 kW, WChaMax = 10.24 kW → 30%
            reduce_pct = int(self._batt_temp_reduce_c_rate * 100)  # 0.3C → 30%
            actions.append({
                'tier': 1,
                'aktor': 'batterie',
                'kommando': 'set_charge_rate',
                'wert': reduce_pct,
                'grund': (f'Batterie-Temp WARNUNG: {temp:.1f}°C ≥ {self._batt_temp_warn}°C '
                          f'→ Ladeleistung auf {self._batt_temp_reduce_c_rate}C '
                          f'({reduce_pct}% ≈ {self._batt_kapazitaet_kwh * self._batt_temp_reduce_c_rate:.1f} kW)'),
            })
            LOG.warning(f"TIER-1: Batterie-Temp {temp:.1f}°C ≥ {self._batt_temp_warn}°C "
                        f"→ Laderate auf {reduce_pct}%")

        elif self._batt_temp_limited and temp < (self._batt_temp_warn - 2):
            # ── HYSTERESE: Normalisieren bei < 38°C ──────────
            obs.alarm_batt_temp = False
            self._batt_temp_limited = False
            actions.append({
                'tier': 1,
                'aktor': 'batterie',
                'kommando': 'set_charge_rate',
                'wert': 100,
                'grund': f'Batterie-Temp normalisiert: {temp:.1f}°C < {self._batt_temp_warn - 2}°C → Laderate 100%',
            })
            LOG.info(f"TIER-1: Batterie-Temp normalisiert: {temp:.1f}°C → Laderate zurück auf 100%")

        else:
            obs.alarm_batt_temp = False

        return actions
