"""
geraete_wattpilot_schutz.py — RegelWattpilotBattSchutz (Rolle C, fast-Zyklus).

Batterieschutz bei Wattpilot-EV-Ladung: hebt SOC_MIN an, wenn die EV-Last die
Hausbatterie unter den Sollwert ziehen wuerde. Re-Export ueber geraete.py.
"""
from __future__ import annotations

from datetime import datetime

from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.param_matrix import ist_aktiv, get_param, get_score_gewicht


class RegelWattpilotBattSchutz(Regel):
    """Batterieschutz bei WattPilot-EV-Ladung.

     Logik (2 Trigger):
     1. SOC ≤ SOC_MIN + puffer: SOC_MIN anheben → Netzladung erzwingen
     2. Letzte 2h vor Sunset UND SOC < 25%: SOC_MIN auf 25% halten,
         solange EV-Ladung aktiv ist

    Entfernt (2026-03-07): Stufe 2 (set_discharge_rate) — GEN24 DC-DC-Wandler
    begrenzt Batteriestrom auf ~22 A; Modbus-Ratenlimits wirkungslos.

    Parametermatrix: regelkreise.wattpilot_battschutz
    """

    name = 'wattpilot_battschutz'
    regelkreis = 'wattpilot_battschutz'
    engine_zyklus = 'fast'

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        # Default an Matrix angeglichen (2026-04-26): Matrix=5000W, Code war 2000W.
        schwelle = get_param(matrix, self.regelkreis, 'ev_leistung_schwelle_w', 5000)
        ev_aktiv = False
        if obs.ev_charging:
            ev_aktiv = True
        elif obs.ev_power_w is not None and obs.ev_power_w > schwelle:
            ev_aktiv = True

        if not ev_aktiv:
            return 0

        if obs.batt_power_w is not None and obs.batt_power_w >= 0:
            return 0

        score = get_score_gewicht(matrix, self.regelkreis)

        puffer = get_param(matrix, self.regelkreis, 'soc_min_puffer_pct', 5)
        soc_min_eff = obs.soc_min or 10
        if obs.batt_soc_pct is not None and obs.batt_soc_pct <= soc_min_eff + puffer:
            return int(score * 1.3)

        # Sunset-Guard: In den letzten 2h vor Sunset SOC_MIN auf 25% halten,
        # damit EV-Ladung nicht die Batterie unter 25% zieht.
        soc = obs.batt_soc_pct
        sunset_h = obs.sunset
        if soc is not None and sunset_h is not None:
            now_h = datetime.now().hour + datetime.now().minute / 60.0
            if (sunset_h - 2.0) <= now_h <= sunset_h and soc < 25:
                return int(score * 1.2)

        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        aktionen = []

        puffer = get_param(matrix, self.regelkreis, 'soc_min_puffer_pct', 5)
        soc_min_eff = obs.soc_min if obs.soc_min is not None else 10
        soc = obs.batt_soc_pct if obs.batt_soc_pct is not None else 50
        soc_min_netz = get_param(matrix, self.regelkreis, 'soc_min_netz_pct', 25)

        eco_info = " (Eco-Modus)" if obs.ev_eco_mode else " (kein Eco → Schnellladung)"
        ev_w = obs.ev_power_w or 0

        sunset_guard = False
        if obs.sunset is not None:
            now_h = datetime.now().hour + datetime.now().minute / 60.0
            sunset_guard = (obs.sunset - 2.0) <= now_h <= obs.sunset

        trigger_soc_nahe_min = soc <= soc_min_eff + puffer
        trigger_sunset_soc_25 = sunset_guard and soc < soc_min_netz

        # ── SOC-Schutz bei EV-Ladung → Netzbezug erzwingen ──────────
        if trigger_soc_nahe_min or trigger_sunset_soc_25:
            if obs.soc_mode != 'manual':
                aktionen.append({
                    'tier': 2, 'aktor': 'batterie',
                    'kommando': 'set_soc_mode', 'wert': 'manual',
                    'grund': 'WattPilot-Schutz: SOC_MODE → manual',
                })

            if trigger_sunset_soc_25 and not trigger_soc_nahe_min:
                grund = (f'WattPilot-Schutz (Sunset-Fenster): letzte 2h vor Sunset, '
                         f'SOC {soc:.0f}% < {soc_min_netz}% → SOC_MIN auf {soc_min_netz}% '
                         f'(Netzbezug){eco_info}')
            else:
                grund = (f'WattPilot-Schutz: SOC {soc:.0f}% nahe SOC_MIN '
                         f'{soc_min_eff}% → SOC_MIN auf {soc_min_netz}% '
                         f'(Netzbezug){eco_info}')

            aktionen.append({
                'tier': 2, 'aktor': 'batterie',
                'kommando': 'set_soc_min', 'wert': soc_min_netz,
                'grund': grund,
                'hinweis': (f'WattPilot lädt mit {ev_w:.0f}W{eco_info} — '
                            f'Batterie geschützt, Ladung ab jetzt aus dem Netz'),
            })

        # Entfernt (2026-03-07): Stufe 2 (set_discharge_rate bei SOC ≤ drosselung)
        # GEN24 DC-DC-Wandler begrenzt Batteriestrom auf ~22 A; Modbus wirkungslos.

        return aktionen
