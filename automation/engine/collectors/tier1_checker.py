"""
tier1_checker.py — Tier-1 Schwellenprüfung mit Sofort-Aktion

Deterministisch, nicht verhandelbar, nicht deaktivierbar.
Prüft bei jedem ObsState-Update ob Alarmschwellen überschritten sind.

Schwellen:
  - Batterie-Temperatur (40°C warn, 45°C alarm)
  - Batterie SOC kritisch (< 5%)
  - Netz-Überlast (24 kW warn, 26 kW alarm)

HINWEIS (2026-03-07): Batterie-Aktionen (set_charge_rate, stop_discharge,
auto) wurden entfernt. Der GEN24 12.0 DC-DC-Wandler begrenzt den
Batteriestrom auf ~22 A (≈9,5 kW). Software-Ratenlimits via InWRte/
OutWRte/StorCtl_Mod waren wirkungslos. SOC_MIN/SOC_MAX über die Fronius
HTTP-API steuern Lade-/Entlade-Erlaubnis implizit.

Die Tier-1-Prüfung setzt weiterhin Alarm-Flags im ObsState für
Dashboard-Anzeige und Logging.

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
        self._batt_soc_kritisch = self.cfg.get('batt_soc_kritisch', 5)
        self._netz_ueberlast_warn_w = self.cfg.get('netz_ueberlast_warn_w', 24000)
        self._netz_ueberlast_alarm_w = self.cfg.get('netz_ueberlast_alarm_w', 26000)

    def check(self, obs: ObsState) -> list[dict]:
        """Prüfe alle Tier-1-Schwellen. Gibt Liste der ausgelösten Aktionen zurück."""
        actions = []

        # ── Batterie-Temperatur ──────────────────────────────
        actions.extend(self._check_batt_temp(obs))

        # ── Batterie SOC kritisch (mit Hysterese-Recovery) ────
        actions.extend(self._check_batt_soc(obs))

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
        """Batterie-Temperatur-Überwachung (reine Alarm-Flags, kein HW-Eingriff).

        Ab 40°C: Warnung (Alarm-Flag + Log)
        Ab 45°C: Alarm (Alarm-Flag + Log)

        HINWEIS (2026-03-07): Hardware-Eingriffe (set_charge_rate) entfernt.
        GEN24 DC-DC-Wandler begrenzt Batteriestrom auf ~22 A; BMS regelt
        bei Temperaturüberschreitung selbständig. Alarm-Flags dienen der
        Dashboard-Anzeige und dem Logging.
        """
        actions = []
        temp = obs.batt_temp_max_c  # Wärmste Zelle ist maßgeblich

        if temp is None:
            return actions

        if temp >= self._batt_temp_alarm:
            obs.alarm_batt_temp = True
            LOG.critical(f"TIER-1 ALARM: Batterie-Temp {temp:.1f}°C ≥ {self._batt_temp_alarm}°C "
                         f"(BMS regelt selbständig)")
        elif temp >= self._batt_temp_warn:
            obs.alarm_batt_temp = True
            LOG.warning(f"TIER-1: Batterie-Temp {temp:.1f}°C ≥ {self._batt_temp_warn}°C")
        else:
            obs.alarm_batt_temp = False

        return actions

    def _check_batt_soc(self, obs: ObsState) -> list[dict]:
        """Batterie-SOC-Überwachung (reine Alarm-Flags, kein HW-Eingriff).

        Unter kritisch (5%): Alarm-Flag setzen + Log

        HINWEIS (2026-03-07): Hardware-Eingriffe (stop_discharge, auto)
        entfernt. SOC_MIN via Fronius HTTP-API steuert die Entlade-Erlaubnis
        implizit. Der Wechselrichter stoppt die Entladung automatisch bei
        Erreichen des SOC_MIN-Werts.

        Die frühere Hysterese-Logik (5%/10%, StorCtl_Mod) und das Recovery-
        Prinzip sind damit obsolet.
        """
        actions = []
        soc = obs.batt_soc_pct

        if soc is None:
            return actions

        if soc < self._batt_soc_kritisch:
            obs.alarm_batt_kritisch = True
            LOG.critical(f"TIER-1 ALARM: SOC {soc:.1f}% < {self._batt_soc_kritisch}% "
                         f"(SOC_MIN regelt Entlade-Erlaubnis)")
        else:
            obs.alarm_batt_kritisch = False

        return actions
