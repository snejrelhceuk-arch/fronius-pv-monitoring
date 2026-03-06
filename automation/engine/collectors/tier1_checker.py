"""
tier1_checker.py — Tier-1 Schwellenprüfung mit Sofort-Aktion

Deterministisch, nicht verhandelbar, nicht deaktivierbar.
Prüft bei jedem ObsState-Update ob Alarmschwellen überschritten sind.

Schwellen:
  - Batterie-Temperatur (40°C warn, 45°C alarm, Hysterese 38°C)
  - Batterie SOC kritisch (< 5%, Hysterese: Recovery bei >= 10%)
  - Netz-Überlast (24 kW warn, 26 kW alarm)

Recovery-Prinzip: Jede Tier-1-Sperre MUSS einen eigenen Recovery-Pfad
haben, weil Engine-Regeln deaktiviert sein können und der Fronius-
Wechselrichter kein Auto-Revert hat (RvrtTms=0).

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
        self._batt_kapazitaet_kwh = self.cfg.get('batt_kapazitaet_kwh', 20.48)
        self._batt_soc_kritisch = self.cfg.get('batt_soc_kritisch', 5)
        self._batt_soc_recovery = self.cfg.get('batt_soc_recovery', 10)
        self._netz_ueberlast_warn_w = self.cfg.get('netz_ueberlast_warn_w', 24000)
        self._netz_ueberlast_alarm_w = self.cfg.get('netz_ueberlast_alarm_w', 26000)
        # Zustand für Hysterese
        self._batt_temp_limited = False
        self._batt_soc_discharge_blocked = False  # Tier-1 hat stop_discharge gesetzt

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
        """Batterie-Temperatur-Schutzlogik mit Hysterese.

        Ab 40°C: Ladeleistung auf 0.3C reduzieren (= ~6 kW bei 20.48 kWh)
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
            # 0.3C × 20.48 kWh = 6.14 kW; InWRte = 30% von WChaMax (BMS: 20480W) → 6144W ✓
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

    def _check_batt_soc(self, obs: ObsState) -> list[dict]:
        """Batterie-SOC-Schutzlogik mit hardware-aware Recovery.

        Unter kritisch (5%): Entladung sofort stoppen (stop_discharge)
        Recovery bei >= recovery (10%): Entladung wieder freigeben (auto)

        Hardware-Aware: Prüft den tatsächlichen Modbus StorCtl_Mod —
        nicht nur den flüchtigen RAM-Flag. Damit greift die Recovery
        auch nach Daemon-Neustart, wenn die Register noch gesperrt sind.

        DESIGN-PRINZIP: Wer sperrt, muss auch entsperren.
          - Fronius RvrtTms=0 → geschriebene Register bleiben permanent
          - Engine-Regeln können alle deaktiviert sein (aktiv=false)
          - Daemon kann zwischendurch neustarten (RAM-Zustand verloren)
          - Bug vom 2026-03-06: SOC fiel auf 4.6%, stop_discharge gesetzt,
            Daemon neugestartet, SOC stieg auf 99.5%, Batterie blieb
            gesperrt → 8 kW Netzbezug trotz voller Batterie

        Hysterese (5% Sperre / 10% Recovery) verhindert Flattern bei
        langsam steigendem SOC nahe der Grenze.
        """
        actions = []
        soc = obs.batt_soc_pct

        if soc is None:
            return actions

        # Hardware-Zustand: Ist Discharge-Limit im Wechselrichter aktiv?
        # StorCtl_Mod Bit 1 = Discharge-Limit aktiv
        hw_discharge_blocked = (
            obs.storctl_mod is not None and (obs.storctl_mod & 0x02) != 0
        )

        # RAM-Flag mit Hardware synchronisieren (nach Daemon-Neustart)
        if hw_discharge_blocked and not self._batt_soc_discharge_blocked:
            self._batt_soc_discharge_blocked = True
            LOG.info(f"TIER-1: Hardware-Sperre erkannt (StorCtl_Mod={obs.storctl_mod}), "
                     f"SOC={soc:.1f}% — Flag synchronisiert")

        if soc < self._batt_soc_kritisch:
            # ── ALARM: Entladung stoppen ─────────────────────
            obs.alarm_batt_kritisch = True
            self._batt_soc_discharge_blocked = True
            actions.append({
                'tier': 1,
                'aktor': 'batterie',
                'kommando': 'stop_discharge',
                'grund': f'SOC kritisch: {soc:.1f}% < {self._batt_soc_kritisch}%',
            })

        elif self._batt_soc_discharge_blocked and soc >= self._batt_soc_recovery:
            # ── RECOVERY: SOC über Hysterese-Schwelle → Automatik ──
            obs.alarm_batt_kritisch = False
            self._batt_soc_discharge_blocked = False
            actions.append({
                'tier': 1,
                'aktor': 'batterie',
                'kommando': 'auto',
                'grund': (f'SOC Recovery: {soc:.1f}% ≥ {self._batt_soc_recovery}% '
                          f'→ Entladesperre aufgehoben (StorCtl_Mod '
                          f'{obs.storctl_mod}→0)'),
            })
            LOG.info(f"TIER-1 RECOVERY: SOC {soc:.1f}% ≥ {self._batt_soc_recovery}% "
                     f"→ Batterie-Entladung wieder freigegeben "
                     f"(StorCtl_Mod war {obs.storctl_mod})")

        elif self._batt_soc_discharge_blocked:
            # ── ZWISCHEN-ZONE: SOC steigt, aber noch unter Recovery ──
            obs.alarm_batt_kritisch = True
            LOG.debug(f"TIER-1: SOC {soc:.1f}% > {self._batt_soc_kritisch}% "
                      f"aber < {self._batt_soc_recovery}% → Sperre bleibt aktiv")

        else:
            obs.alarm_batt_kritisch = False

        return actions
