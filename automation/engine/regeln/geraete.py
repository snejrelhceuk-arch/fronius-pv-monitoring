"""
geraete.py — Geräte-spezifische Regeln (P1-P2, fast-Zyklus)

RegelWattpilotBattSchutz — Batterieschutz bei EV-Ladung
RegelHeizpatrone         — Fritz!DECT Heizpatrone (Burst-Strategie)
RegelKlimaanlage         — Fritz!DECT Klimaanlage (wie Heizpatrone, höher priorisiert)

Siehe: doc/WATTPILOT_ARCHITECTURE.md, automation/STRATEGIEN.md §2.6
"""

from __future__ import annotations

import logging
import json
import sqlite3
import time
from collections import deque
from datetime import datetime
from typing import Optional
import config

from automation.engine.obs_state import ObsState
from automation.engine.regeln.basis import Regel
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht,
    classify_forecast_kwh, get_effective_forecast_quality,
)
from automation.engine.schaltlog import logge_extern

LOG = logging.getLogger('engine')
RAM_DB_PATH = '/dev/shm/automation_obs.db'

# Override-Bridge: Steuerbox-Klima-Aktionen als engine-initiiert markieren,
# damit die Extern-Erkennung keinen falschen OFF->ON Extern-Event loggt.
_klima_engine_ein_ts: float = 0.0


def registriere_klima_engine_ein() -> None:
    """Markiere eine engine-initiierte Klima-Einschaltung.

    Wird sowohl von RegelKlimaanlage als auch vom Override-Processor genutzt.
    """
    global _klima_engine_ein_ts
    _klima_engine_ein_ts = time.time()


def klima_engine_ein_kuerzlich(timeout_s: float = 180.0) -> bool:
    """True wenn kürzlich ein engine-initiiertes Klima-EIN markiert wurde."""
    global _klima_engine_ein_ts
    if _klima_engine_ein_ts <= 0:
        return False
    if (time.time() - _klima_engine_ein_ts) < timeout_s:
        return True
    _klima_engine_ein_ts = 0.0  # Remanenz sauber abbauen
    return False


# ═════════════════════════════════════════════════════════════
# WATTPILOT BATTERIESCHUTZ (P1 — Sicherheit, fast)
# ═════════════════════════════════════════════════════════════

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


# ═════════════════════════════════════════════════════════════
# HEIZPATRONE (P2 — Steuerung, fast)
# ═════════════════════════════════════════════════════════════

class RegelHeizpatrone(Regel):
    """Heizpatrone (2 kW) via Fritz!DECT — prognosegesteuerte Burst-Strategie.

    Potenzial-gesteuert: Forecast-kWh bestimmt Freigabegrad.
    Kontextabhängig: SOC_MAX-Phase, Verbraucher, Tageszeit.

        Potenzial-Skala (zentral über Forecast-Bewertung):
            < 40 kWh (schlecht)     — HP nur explizit/manuell, kein Parallel-Betrieb
            40–100 kWh (mittel)     — HP + WP ok, EV → HP pausiert
            ≥ 100 kWh (gut)         — HP parallel mit allen Verbrauchern

    6 Phasen:
      Phase 0:  Morgen-Drain — Batterie leeren ab sunrise-1h, prognosegetrieben
      Phase 1:  Vormittags — gute Prognose → HP darf EV+Batt verzögern
      Phase 1b: Nulleinspeiser — SOC≈MAX, PV produziert, Batt idle → stille Kapazität
      Phase 2:  Mittags    — Batterie lädt kräftig → Burst wenn Prognose reicht
      Phase 3:  Nachmittag — nur bei deutlichem Überschuss, konservativ
      Phase 4:  Abend      — Nachladezyklus: HP-Burst wenn SOC≈MAX + PV noch produziert,
                              AUS wenn SOC zu weit unter MAX sinkt, Batt lädt nach,
                              neuer Burst wenn SOC wieder ≈MAX. Adaptiv zu SOC_MAX.

    Notaus HART (immer sofort):
      - WW-Temp ≥ 78°C, SOC ≤ 7%

    Notaus Phase 4 (rest_h < 2h, differenziert):
      - SOC < SOC_MAX - 10%: AUS (Batterie-Vorrang)
      - PV < 1500W: AUS (nicht genug Rest-PV)
      - Entladung > 1000W: AUS (zu viel Batterie-Bezug)
      - Sonst: HP darf weiterlaufen

    Parametermatrix: regelkreise.heizpatrone
    Siehe: automation/STRATEGIEN.md §2.6
    """

    name = 'heizpatrone'
    regelkreis = 'heizpatrone'
    aktor = 'fritzdect'
    engine_zyklus = 'fast'
    HP_NENN_W = 2000   # Nennleistung Heizpatrone ~2 kW

    def __init__(self):
        super().__init__()
        self._burst_start: float = 0
        self._burst_ende: float = 0
        self._letzte_aus: float = 0
        self._warte_auf_engine_aus: bool = False
        self._warte_auf_engine_aus_ts: float = 0
        self._drain_modus: bool = False
        self._letzte_phase: str = ''       # Letzte Burst-Phase (für Wiedereintritt)
        # Extern-Erkennung: HP wurde außerhalb der Engine ein-/ausgeschaltet
        self._extern_ein_ts: float = 0       # Zeitpunkt der Extern-EIN-Erkennung
        self._extern_aus_ts: float = 0       # Zeitpunkt der Extern-AUS-Erkennung
        self._letzter_hp_zustand: Optional[bool] = None  # None = erster Zyklus (kein EXTERN)
        # Glättung: Netzbezug-Historie für 7-Min-Durchschnitt (Engine-Zyklus ~60s)
        self._grid_history: deque = deque(maxlen=7)
        # Probe-Logik: Nulleinspeiser-Erkennung durch Testpuls
        self._probe_modus: bool = False       # Probe-Burst aktiv (kurzer Testpuls)
        self._probe_start_pv_w: float = 0     # PV-Leistung bei Probe-Start
        self._probe_start_grid_w: float = 0   # Grid-Leistung bei Probe-Start
        self._probe_cooldown_bis: float = 0   # Epoch: nächster Probe-Versuch frühestens
        # Kurz-Burst-Schutz: nach 2x Burst < 5 min → 1h Sperre
        self._kurze_burst_zaehler: int = 0        # aufeinanderfolgende Kurz-Bursts
        self._kurz_burst_sperre_bis: float = 0    # Epoch: EIN-Sperre aktiv bis
        # Watchdog: Notaus wenn WW-Temperatur länger als Schwelle unbekannt
        self._ww_temp_letzte_gueltig: float = 0   # Epoch: letzte gültige ww_temp
        # Drain-Abschalt-Verzögerung: Soft-Verbraucher-Bedingung (Haus/WP/EV) muss
        # drain_abschalt_verzoegerung_min anhalten bevor HP abgeschaltet wird.
        # SOC, Temperatur und Netzbezug sind ausgenommen (immer sofort).
        self._drain_lastbedingung_ts: float = 0   # Epoch: erste Erkennung der Soft-Bedingung

    def _geraet_label(self) -> str:
        """Kurzlabel für menschenlesbare Extern-Logs."""
        return 'HP'

    def _cancel_conflicting_overrides(self, desired_state: str, geraet: str = 'hp') -> None:
        """Cancelt konfligierende Toggle-Overrides bei externer Schaltung.

        Symmetrische Behandlung beider Richtungen (Stand 2026-04-26):
          desired_state='off'  → cancelt alle (open|active) toggle-Overrides
                                  mit params.state='on'.
                                  Anwendung: extern AUS erkannt — eine alte
                                  „EIN"-Override darf nicht mehr reapplied
                                  werden.
          desired_state='on'   → cancelt alle (open|active) toggle-Overrides
                                  mit params.state='off'.
                                  Anwendung: extern EIN erkannt — eine alte
                                  „AUS"-Override darf nicht mehr reapplied
                                  werden.

        Schreibt zusätzlich einen `steuerbox_audit`-Eintrag pro
        cancelltem Override für die forensische Spur.

        Args:
            desired_state: 'off' oder 'on'.
            geraet:        'hp' oder 'klima' (entscheidet `action`).
        """
        if desired_state not in ('off', 'on'):
            return

        action_name = 'hp_toggle' if geraet == 'hp' else 'klima_toggle'
        # Wir wollen Overrides der GEGENRICHTUNG canceln.
        konflikt_state = 'on' if desired_state == 'off' else 'off'

        try:
            db_path = '/dev/shm/automation_obs.db'
            conn = sqlite3.connect(db_path, timeout=5.0)
            conn.execute('PRAGMA journal_mode=WAL')

            # Welche IDs werden betroffen sein? (für Audit-Trail)
            cur = conn.execute(
                "SELECT id FROM operator_overrides "
                "WHERE action=? AND status IN ('open','active') "
                "AND json_extract(params_json, '$.state')=?",
                (action_name, konflikt_state),
            )
            betroffene_ids = [row[0] for row in cur.fetchall()]

            if not betroffene_ids:
                conn.close()
                return

            conn.execute(
                "UPDATE operator_overrides SET status='released' "
                "WHERE action=? AND status IN ('open','active') "
                "AND json_extract(params_json, '$.state')=?",
                (action_name, konflikt_state),
            )

            # Audit-Trail je betroffenem Override
            now_iso = datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
            note = (
                f'external action cancelled conflicting '
                f'{action_name}(state={konflikt_state}) override '
                f'(extern_{desired_state}_detected)'
            )
            for oid in betroffene_ids:
                conn.execute(
                    "INSERT INTO steuerbox_audit "
                    "(ts, action, params_json, result_json, override_id, note) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        now_iso,
                        action_name,
                        json.dumps({'state': konflikt_state}, ensure_ascii=False),
                        json.dumps(
                            {'cancelled': True,
                             'reason': f'extern_{desired_state}_detected'},
                            ensure_ascii=False,
                        ),
                        oid,
                        note,
                    ),
                )
            conn.commit()
            conn.close()
            LOG.info(
                f'Cancelled {len(betroffene_ids)} conflicting '
                f'{action_name}(state={konflikt_state}) override(s) '
                f'due to external {desired_state.upper()}'
            )
        except Exception as e:
            LOG.warning(
                f'Failed to cancel conflicting overrides for {action_name} '
                f'(desired={desired_state}): {e}'
            )

    # ── Potenzial-Klassifikation ─────────────────────────────

    def _potenzial(self, obs: ObsState, matrix: dict) -> str:
        """Tagespotenzial klassifizieren anhand REST-Ertrag.

        Verwendet forecast_rest_kwh (= forecast_kwh - pv_today_kwh).
        Keine IST/SOLL-Skalierung — beim Nulleinspeiser bedeutet
        niedrige IST/SOLL nicht schlechtes Wetter sondern Abregelung.

        Returns: 'schlecht' | 'mittel' | 'gut'
        """
        rest_kwh = obs.forecast_rest_kwh
        if rest_kwh is None:
            rest_kwh = obs.forecast_kwh or 0

        return classify_forecast_kwh(rest_kwh, matrix) or 'schlecht'

    def _verbraucher_aktiv(self, obs: ObsState, matrix: dict) -> tuple[bool, bool]:
        """Prüfe ob Großverbraucher aktiv sind.

        Returns: (wp_aktiv, ev_aktiv)
        """
        wp_schwelle = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
        ev_schwelle = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
        wp_aktiv = (obs.wp_power_w or 0) >= wp_schwelle
        ev_aktiv = (obs.ev_power_w or 0) >= ev_schwelle
        return wp_aktiv, ev_aktiv

    def _hp_parallel_erlaubt(self, potenzial: str, wp_aktiv: bool,
                              ev_aktiv: bool) -> bool:
        """Darf HP parallel mit WP/EV laufen?

        Potenzial:
                    gut (≥100 kWh):         HP + WP + EV alles gleichzeitig
                    mittel (40-100):        HP + WP ok, HP + EV → HP pausiert
                    schlecht (<40):         HP nicht automatisch (nur Extern)
        """
        if potenzial == 'gut':
            return True  # Alles parallel erlaubt
        if potenzial == 'mittel':
            return not ev_aktiv  # WP ok, EV → HP pausiert
        # schlecht: kein Parallelbetrieb
        return not (wp_aktiv or ev_aktiv)

    def _min_lade_nach_potenzial(self, potenzial: str, matrix: dict) -> float:
        """Potenzialabhängige Mindest-Ladeleistung für Burst-Start.

        Bei gutem Potenzial reicht weniger Batterie-Ladung als Trigger,
        weil der Burst-Timer und die Potenzial-Notaus die HP schützen.
        Grundlage: p_batt - HP_Last (~2kW) sollte positiv bleiben.

        Returns: Schwellwert in Watt
        """
        basis = get_param(matrix, self.regelkreis, 'min_ladeleistung_w', 5000)
        if potenzial == 'gut':
            return max(2000, basis * 0.5)    # 50% → 2500W
        if potenzial == 'mittel':
            return max(2500, basis * 0.7)    # 70% → 3500W
        # schlecht: volle Schwelle
        return basis

    def _grid_avg(self, obs: ObsState) -> float:
        """Geglätteter Netzbezug (7-Zyklen-Durchschnitt ≈ 7 Min).

        Verhindert Notaus durch kurzzeitige Leistungssprünge (±10kW)
        und Haushaltslast-Schaltspitzen (Waschmaschine, Trockner etc.).
        Nur positive Werte (Bezug) werden gemittelt; Einspeisung = 0.
        """
        gw = obs.grid_power_w
        if gw is not None:
            self._grid_history.append(max(0, gw))
        if not self._grid_history:
            return 0.0
        return sum(self._grid_history) / len(self._grid_history)

    def _restbedarf_fuer_hp_kwh(self, obs: ObsState, matrix: dict, rest_h: float) -> float:
        """Dynamischer Rest-Prognosebedarf für HP-Freigabe im Notaus-Kontext.

        Bestandteile:
          1) Batteriebedarf bis Ziel-SOC (bei hohem SOC optional ignorieren)
          2) Haushalt bis Sonnenuntergang (mit Mindest-Grundlast)
          3) Sicherheitsreserve
          4) Optionaler Klima-Bedarf (wenn Klima aktuell läuft)
        """
        sicherheit_kwh = float(get_param(
            matrix, self.regelkreis, 'notaus_forecast_sicherheit_kwh', 5.0
        ))
        haushalt_min_w = float(get_param(
            matrix, self.regelkreis, 'notaus_forecast_haushalt_min_w', 500
        ))

        haus_netto_w = float(obs.house_load_w or 0)
        if obs.heizpatrone_aktiv:
            haus_netto_w = max(0.0, haus_netto_w - self.HP_NENN_W)
        haus_plan_w = max(haushalt_min_w, haus_netto_w)
        plan_h = max(0.0, rest_h)
        haushalt_kwh = haus_plan_w * plan_h / 1000.0

        soc_now = float(obs.batt_soc_pct if obs.batt_soc_pct is not None else 50.0)
        batt_ignore_ab_soc = float(get_param(
            matrix, self.regelkreis, 'notaus_forecast_batt_ignore_ab_soc_pct', 95
        ))
        batt_ziel_soc = float(get_param(
            matrix, self.regelkreis, 'notaus_forecast_batt_ziel_soc_pct', 100
        ))
        if soc_now >= batt_ignore_ab_soc:
            batt_bedarf_kwh = 0.0
        else:
            ziel_soc = max(soc_now, min(100.0, batt_ziel_soc))
            batt_bedarf_kwh = max(0.0, (ziel_soc - soc_now) * config.PV_BATTERY_KWH / 100.0)

        klima_kwh = 0.0
        if bool(obs.klima_aktiv):
            klima_last_w = float(get_param(
                matrix, self.regelkreis, 'notaus_forecast_klima_last_w', 1300
            ))
            klima_plan_h = float(get_param(
                matrix, self.regelkreis, 'notaus_forecast_klima_plan_h', 4.0
            ))
            klima_h = min(plan_h, max(0.0, klima_plan_h))
            klima_kwh = klima_last_w * klima_h / 1000.0

        return batt_bedarf_kwh + haushalt_kwh + sicherheit_kwh + klima_kwh

    def _netzbezug_notaus_ausloesen(
        self,
        obs: ObsState,
        matrix: dict,
        rest_h: float,
        grid_avg: float,
        notaus_netz: float,
    ) -> tuple[bool, str]:
        """Entscheidet HP-Notaus wegen Netzbezug inkl. Forecast-/Ist-Vetos."""
        grid_current = float(obs.grid_power_w or 0)
        current_veto_w = float(get_param(
            matrix, self.regelkreis, 'notaus_netzbezug_aktuell_veto_w', 200
        ))

        # Veto 1: aktueller Netzbezug ist klein → Durchschnitt kann veraltet sein
        if grid_current < current_veto_w:
            return False, ''

        rest_kwh = obs.forecast_rest_kwh
        if rest_kwh is None:
            rest_kwh = obs.forecast_kwh or 0
        forecast_quality = get_effective_forecast_quality(obs, matrix) or ''

        # Veto 2: gute Prognose + ausreichend Rest für Batt+Haushalt+Reserve (+Klima)
        if forecast_quality == 'gut':
            mindest_rest_kwh = self._restbedarf_fuer_hp_kwh(obs, matrix, rest_h)
            if rest_kwh >= mindest_rest_kwh:
                return False, ''

        if grid_avg > notaus_netz:
            return True, (f'Netzbezug Ø{grid_avg:.0f}W > {notaus_netz:.0f}W '
                          f'(aktuell {grid_current:.0f}W)')
        return False, ''

    def _batt_entladung_toleriert(self, potenzial: str, soc_max_eff: int,
                                   obs: ObsState) -> bool:
        """Wird Batterie-Entladung toleriert (HP darf trotzdem laufen)?

        Kontext-Logik:
                                        gut (≥ 100 kWh):     toleriert (ausreichend PV um nachzuladen)
                    mittel (40-100):      toleriert WENN SOC_MAX ≤ 75% (Batt gedeckelt,
                                                                füllen noch nicht nötig)
                    schlecht (<40):       nie toleriert
        """
        if potenzial == 'gut':
            return True
        if potenzial == 'mittel':
            # Batterie ist noch gedeckelt → Entladung ist "normal"
            return soc_max_eff <= 75
        return False  # schlecht → keine Toleranz

    def _drain_soc_freigegeben(self, obs: ObsState, matrix: dict) -> bool:
        """Phase 0 nur bei bereits geöffneter Batterie erlauben.

        Prüft ob die Morgen-Öffnung aktiv ist (SOC_MIN < Komfort 25%).
        Bei leichten Nächten (SOC_MIN=25%) wird kein Drain benötigt.
        """
        komfort_min = int(get_param(matrix, 'komfort_reset', 'komfort_min_pct', 25))
        return obs.soc_min is not None and obs.soc_min < komfort_min

    def _forecast_power_at_hour(self, obs: ObsState, hour: int) -> Optional[float]:
        """Hole Prognoseleistung [W] für eine Stunde aus dem Forecast-Profil."""
        if not obs.forecast_power_profile:
            return None
        for entry in obs.forecast_power_profile:
            if entry.get('hour', 0) == hour:
                return float(entry.get('total_ac_w', 0) or 0)
        return None

    def _drain_haushalt_prognose_veto(
        self,
        obs: ObsState,
        matrix: dict,
        house_netto_w: float,
        now_h: float,
    ) -> tuple[bool, str]:
        """Veto für Drain-Haushaltsabschaltung bei guter/tragfähiger Prognose.

        Voraussetzungen:
          1) Tagesprognose-Qualität ist "gut".
          2) Entweder Lastdeckung jetzt+30min ODER positiver Trend bis +30min
             mit ausreichender SOC-Brücke für die Übergangszeit.
        """
        quality = get_effective_forecast_quality(obs, matrix) or ''
        tagesqualitaet_gut = quality == 'gut'
        if not tagesqualitaet_gut:
            return False, ''

        last_w = max(0.0, float(house_netto_w)) + float(self.HP_NENN_W)
        reserve_w = float(get_param(
            matrix, self.regelkreis, 'drain_haushalt_prognose_reserve_w', 200
        ))
        noetig_w = last_w + reserve_w

        now_hour = int(now_h)
        plus30_hour = int((now_h + 0.5) % 24)
        fc_now_w = self._forecast_power_at_hour(obs, now_hour)
        fc_30_w = self._forecast_power_at_hour(obs, plus30_hour)

        if fc_now_w is None or fc_30_w is None:
            return False, ''

        # Fall A: klassisch — Prognose deckt Bedarf bereits jetzt und in 30 Min.
        if fc_now_w >= noetig_w and fc_30_w >= noetig_w:
            return True, (f'Tagesprognose=gut und Prognose trägt Last: jetzt {fc_now_w:.0f}W, '
                          f'+30min {fc_30_w:.0f}W ≥ Bedarf {noetig_w:.0f}W')

        # Fall B: Gradient-Freigabe — jetzt ggf. Defizit, aber in 30 Min ausreichend.
        # Dann nur zulassen, wenn SOC das Defizit überbrücken kann.
        gradient_min_w = float(get_param(
            matrix, self.regelkreis, 'drain_haushalt_gradient_min_w', 300
        ))
        trend_w = fc_30_w - fc_now_w
        if fc_30_w < noetig_w or trend_w < gradient_min_w:
            return False, ''

        bridge_h = float(get_param(
            matrix, self.regelkreis, 'drain_haushalt_bridge_h', 0.5
        ))
        deficit_now_w = max(0.0, noetig_w - fc_now_w)
        bridge_need_kwh = deficit_now_w * max(0.0, bridge_h) / 1000.0

        soc = float(obs.batt_soc_pct if obs.batt_soc_pct is not None else 0.0)
        drain_stop_soc = float(get_param(
            matrix, self.regelkreis, 'drain_stop_soc_pct', 15
        ))
        soc_reserve_pct = float(get_param(
            matrix, self.regelkreis, 'drain_haushalt_soc_reserve_pct', 2
        ))
        soc_min_bridge = drain_stop_soc + soc_reserve_pct
        soc_buffer_pct = max(0.0, soc - soc_min_bridge)
        bridge_avail_kwh = soc_buffer_pct * config.PV_BATTERY_KWH / 100.0

        if bridge_avail_kwh >= bridge_need_kwh:
            return True, (
                f'Tagesprognose=gut und Gradient trägt: ΔP={trend_w:.0f}W, '
                f'+30min {fc_30_w:.0f}W ≥ Bedarf {noetig_w:.0f}W, '
                f'SOC-Brücke {bridge_avail_kwh:.2f}/{bridge_need_kwh:.2f}kWh'
            )
        return False, ''

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        """Score für HP-Steuerung.

        Drei Pfade:
          1. Notaus (HP AUS) — IMMER aktiv, auch bei aktiv=False
          2. Drain-EIN (Phase 0) — wenn aktiv, Batterie morgens leeren
          3. Burst-EIN (Phase 1-3) — nur bei aktiv=True (Strategie).
        """
        now_h = datetime.now().hour + datetime.now().minute / 60
        sunset = obs.sunset or 17.0
        rest_h = max(0, sunset - now_h)
        p_batt = obs.batt_power_w
        score = get_score_gewicht(matrix, self.regelkreis)

        # ── Extern-Erkennung (in bewerte(), da immer aufgerufen) ──
        # Default an Matrix angeglichen (2026-04-26): Matrix=1800s, Code war 3600s.
        extern_respekt = get_param(matrix, self.regelkreis, 'extern_respekt_s', 1800)
        geraet = self._geraet_label()

        # Erwartete Engine-AUS-Bestätigung nicht ewig halten
        if (self._warte_auf_engine_aus and obs.heizpatrone_aktiv
                and (time.time() - self._warte_auf_engine_aus_ts) > 180):
            self._warte_auf_engine_aus = False
            self._warte_auf_engine_aus_ts = 0

        # Erster Zyklus nach (Neu-)Start: kein State → min_pause als Schutz
        if self._letzter_hp_zustand is None and not obs.heizpatrone_aktiv:
            # HP ist beim Start AUS → kurze Sperre damit Engine nicht sofort einschaltet
            if self._letzte_aus == 0:
                self._letzte_aus = time.time()
                LOG.info(f'Erster Zyklus: {geraet} AUS vorgefunden → min_pause-Schutz aktiv')

        # Extern-EIN: HP ging AUS→EIN ohne laufenden Burst/Drain
        if (obs.heizpatrone_aktiv and self._letzter_hp_zustand is not None
                and not self._letzter_hp_zustand):
            if self._burst_ende == 0 and not self._drain_modus:
                self._extern_ein_ts = time.time()
                LOG.info(f'{geraet} extern eingeschaltet erkannt → Hysterese aktiv')
                logge_extern('fritzdect', f'{geraet} extern EIN',
                             'Manuell eingeschaltet (nicht durch Engine)')
                # Symmetrie zu Extern-AUS (2026-04-26):
                # Cancelt alle konfligierenden hp_toggle(state=off)-Overrides,
                # damit eine alte „AUS"-Intent nicht über das manuelle
                # Einschalten hinweg reapplied wird.
                self._cancel_conflicting_overrides('on')

        # Extern-AUS: HP ging EIN→AUS ohne Engine-hp_aus
        if (not obs.heizpatrone_aktiv and self._letzter_hp_zustand is not None
                and self._letzter_hp_zustand):
            engine_hat_ausgeschaltet = self._warte_auf_engine_aus
            if engine_hat_ausgeschaltet:
                self._warte_auf_engine_aus = False
                self._warte_auf_engine_aus_ts = 0
            else:
                self._extern_aus_ts = time.time()
                self._burst_ende = 0
                self._burst_start = 0
                self._drain_modus = False
                LOG.info(f'{geraet} extern ausgeschaltet erkannt → EIN-Sperre aktiv')
                logge_extern('fritzdect', f'{geraet} extern AUS',
                             'Manuell ausgeschaltet (nicht durch Engine) → EIN-Sperre aktiv')
                # Race-Condition-Fix: Cancelt alle konfliktierenden hp_toggle(state=on) Overrides
                self._cancel_conflicting_overrides('off')

        if not obs.heizpatrone_aktiv:
            self._extern_ein_ts = 0
        self._letzter_hp_zustand = obs.heizpatrone_aktiv

        ist_extern = (self._extern_ein_ts > 0
                      and (time.time() - self._extern_ein_ts) < extern_respekt)

        # ── Notaus-Pfad: IMMER aktiv ──
        if obs.heizpatrone_aktiv:
            min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
            temp_max = get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78)
            soc_schutz_abs = get_param(matrix, 'soc_schutz', 'stop_entladung_unter_pct', 5)

            # ── HARTE Kriterien: IMMER sofort, auch bei Extern ──
            if obs.ww_temp_c is not None:
                self._ww_temp_letzte_gueltig = time.time()
                if obs.ww_temp_c >= temp_max:
                    return int(score * 1.5)
            else:
                # Watchdog: WW-Temp unbekannt (Modbus-Ausfall) → Notaus nach Timeout
                ww_watchdog_s = get_param(
                    matrix, self.regelkreis, 'ww_temp_watchdog_s', 300
                )
                if (self._ww_temp_letzte_gueltig > 0
                        and (time.time() - self._ww_temp_letzte_gueltig) > ww_watchdog_s):
                    LOG.warning('HP-Notaus: WW-Temperatur seit %ds unbekannt (Modbus?)',
                                int(time.time() - self._ww_temp_letzte_gueltig))
                    return int(score * 1.5)
            if (obs.batt_soc_pct or 0) <= soc_schutz_abs:
                return int(score * 1.5)
            # Extern-Autoritäts-Override: manuelle Einschaltung bei niedrigem SOC überstimmen
            if ist_extern:
                extern_notaus_soc = get_param(matrix, self.regelkreis, 'extern_notaus_soc_pct', 15)
                if (obs.batt_soc_pct or 0) <= extern_notaus_soc:
                    return int(score * 1.5)
            # rest_h < min_rest_h: Phase-4-Differenzierung
            # HP darf weiterlaufen wenn SOC nahe SOC_MAX und PV noch produziert.
            # Primärziel: Batterie-Vollladung, HP nutzt Restkapazität.
            # Bei manueller Autorität (ist_extern) pausiert — User hat Vorrang.
            if rest_h < min_rest_h and not ist_extern:
                abend_aus = get_param(matrix, self.regelkreis, 'abend_soc_aus_unter_max_pct', 10)
                abend_max_entl = get_param(matrix, self.regelkreis, 'abend_max_entladung_w', 1000)
                abend_min_pv = get_param(matrix, self.regelkreis, 'abend_min_pv_w', 1500)
                soc_now = obs.batt_soc_pct or 0
                soc_max_now = obs.soc_max or 75
                soc_ok = soc_now >= (soc_max_now - abend_aus)
                entl_ok = (p_batt or 0) >= -abend_max_entl
                pv_ok = (obs.pv_total_w or 0) >= abend_min_pv
                if not (soc_ok and entl_ok and pv_ok):
                    return int(score * 1.5)
                # Abend-Bedingungen erfüllt → kein Notaus, weiter prüfen

            # ── KONTEXTABHÄNGIGE Kriterien ──
            # Bei Extern-Hysterese: nur HARTE greifen (oben), Rest pausiert
            if ist_extern:
                verbleibend = int(extern_respekt - (time.time() - self._extern_ein_ts))
                LOG.debug(f'HP extern → Autorität respektiert, '
                          f'nur Übertemp/SOC-Schutz aktiv ({verbleibend}s verbleibend)')
            else:
                potenzial = self._potenzial(obs, matrix)
                soc_max_eff = obs.soc_max or 75
                wp_aktiv, ev_aktiv = self._verbraucher_aktiv(obs, matrix)

                # Drain-Modus hat eigene Schutzlogik
                if self._drain_modus:
                    drain_stop_soc = get_param(matrix, self.regelkreis, 'drain_stop_soc_pct', 15)
                    soc_now = obs.batt_soc_pct or 0
                    if soc_now <= drain_stop_soc:
                        return int(score * 1.5)
                    # Phase 0 (Morgen-Drain): Batterie wird absichtlich VOR PV-Start
                    # entladen — PV-Check darf hier NICHT greifen.
                    # Schutz: SOC-Minimum + Netzbezug + Haushalt-Limits reichen.
                    if self._letzte_phase != 'phase0':
                        # Späterer Drain (nach PV-Start): PV muss liefern
                        pv_w = obs.pv_total_w or 0
                        if pv_w < self.HP_NENN_W * 0.25:  # < 500W PV → kein Solarertrag
                            return int(score * 1.5)
                    # Netzbezug während Drain → Energie kommt aus Netz, nicht PV
                    notaus_netz = get_param(matrix, self.regelkreis, 'notaus_netzbezug_w', 200)
                    grid_avg = self._grid_avg(obs)
                    notaus_ausloesen, _ = self._netzbezug_notaus_ausloesen(
                        obs, matrix, rest_h, grid_avg, float(notaus_netz)
                    )
                    if notaus_ausloesen:
                        return int(score * 1.5)
                    d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
                    d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
                    d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
                    # HP-Eigenverbrauch herausrechnen (Selbstreferenz-Fix)
                    haus_netto = (obs.house_load_w or 0)
                    if obs.heizpatrone_aktiv:
                        haus_netto = max(0, haus_netto - self.HP_NENN_W)
                    # WP-Leistung auch herausrechnen (eigene Prüfung unten)
                    haus_netto = max(0, haus_netto - (obs.wp_power_w or 0))
                    # Soft-Bedingungen: Haushalt/WP/EV — mit Verzögerung damit
                    # kurze Verbrauchsspitzen (Wasserkocher, Backofen, Hauswasserwerk)
                    # den Drain nicht sofort unterbrechen.
                    # SOC, Temperatur, Netzbezug sind NICHT verzögert (oben bereits geprüft).
                    soft_bedingung = False
                    if haus_netto >= d_haus * 1.2:
                        veto, _ = self._drain_haushalt_prognose_veto(
                            obs, matrix, haus_netto, now_h
                        )
                        if not veto:
                            soft_bedingung = True
                    if not soft_bedingung and (
                            (obs.wp_power_w or 0) >= d_wp
                            or (obs.ev_power_w or 0) >= d_ev):
                        soft_bedingung = True
                    if soft_bedingung:
                        verz_s = int(get_param(
                            matrix, self.regelkreis,
                            'drain_abschalt_verzoegerung_min', 5
                        )) * 60
                        now_ts = time.time()
                        if self._drain_lastbedingung_ts == 0:
                            self._drain_lastbedingung_ts = now_ts
                            LOG.info(
                                'HP Drain-Verbrauchersperre: Verzögerung gestartet '
                                '(%.0f Min) — Haus=%.0fW, WP=%.0fW, EV=%.0fW',
                                verz_s / 60, haus_netto,
                                obs.wp_power_w or 0, obs.ev_power_w or 0,
                            )
                        elif (now_ts - self._drain_lastbedingung_ts) >= verz_s:
                            return int(score * 1.5)
                    else:
                        if self._drain_lastbedingung_ts > 0:
                            LOG.debug('HP Drain-Verbrauchersperre: Bedingung weggefallen → Timer reset')
                        self._drain_lastbedingung_ts = 0
                else:
                    # Batterie entlädt: potenzial- und kontextabhängig
                    if p_batt is not None and p_batt < 0:
                        if not self._batt_entladung_toleriert(potenzial, soc_max_eff, obs):
                            return int(score * 1.5)

                    # Verbraucher-Konkurrenz: potenzialabhängig
                    if not self._hp_parallel_erlaubt(potenzial, wp_aktiv, ev_aktiv):
                        return int(score * 1.2)

                    # Netzbezug (5-Min-Durchschnitt)
                    notaus_netz = get_param(matrix, self.regelkreis, 'notaus_netzbezug_w', 200)
                    grid_avg = self._grid_avg(obs)
                    notaus_ausloesen, _ = self._netzbezug_notaus_ausloesen(
                        obs, matrix, rest_h, grid_avg, float(notaus_netz)
                    )
                    if notaus_ausloesen:
                        return int(score * 1.5)

                # Burst-Timer abgelaufen
                if self._burst_ende > 0 and time.time() >= self._burst_ende:
                    # Phase 0 darf innerhalb des Drain-Fensters kontinuierlich laufen.
                    # Das eigentliche Verlängern passiert in erzeuge_aktionen().
                    if self._drain_modus and self._letzte_phase == 'phase0':
                        drain_fenster = get_param(
                            matrix, self.regelkreis, 'drain_fenster_ende_h', 10.0
                        )
                        if now_h < drain_fenster:
                            return score
                    return int(score * 1.2)

            # Laufender Burst noch aktiv → Score halten (kein Abschalten)
            if not ist_extern and self._burst_ende > 0 and time.time() < self._burst_ende:
                return score

        # ── Burst-EIN-Pfad: nur bei aktiv=True ──
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        rest_kwh = obs.forecast_rest_kwh
        soc = obs.batt_soc_pct
        soc_max_eff = obs.soc_max or 75

        if p_batt is None or rest_kwh is None or soc is None:
            return 0

        min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
        # rest_h < min_rest_h ist KEIN early return mehr → Phase 4 am Ende

        temp_max = get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78)
        if obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
            return 0

        min_pause = get_param(matrix, self.regelkreis, 'min_pause_s', 300)
        if (not obs.heizpatrone_aktiv and self._letzte_aus > 0
                and (time.time() - self._letzte_aus) < min_pause):
            return 0

        # Extern-AUS respektieren: HP wurde manuell ausgeschaltet → Sperre
        # Default an Matrix angeglichen (2026-04-26): Matrix=1800s.
        extern_respekt = get_param(matrix, self.regelkreis, 'extern_respekt_s', 1800)
        if (self._extern_aus_ts > 0
                and (time.time() - self._extern_aus_ts) < extern_respekt):
            verbleibend = int(extern_respekt - (time.time() - self._extern_aus_ts))
            LOG.debug(f'{self._geraet_label()} extern AUS → EIN-Sperre noch {verbleibend}s')
            return 0

        # Kurz-Burst-Sperre: 2× Burst < 5 Min → 1h EIN-Pause
        if self._kurz_burst_sperre_bis > 0 and time.time() < self._kurz_burst_sperre_bis:
            verbleibend = int(self._kurz_burst_sperre_bis - time.time())
            LOG.debug(f'{self._geraet_label()} Kurz-Burst-Sperre → EIN-Pause noch {verbleibend}s')
            return 0

        batt_rest_kwh = max(0, (soc_max_eff - soc) * config.PV_BATTERY_KWH / 100)

        potenzial = self._potenzial(obs, matrix)
        wp_aktiv, ev_aktiv = self._verbraucher_aktiv(obs, matrix)

        # Phase 0: Morgen-Drain — HP um Batterie schneller zu leeren
        #   Frühestens sunrise - 1h (prognosegetrieben, NICHT p_batt-abhängig).
        #   SOC > drain_start_soc (20%), Stop bei drain_stop_soc (15%).
        #   Bedingung: Prognose erwartet bald hohe PV-Leistung.
        #   Guard: Mindestens 5h Sonnenschein prognostiziert — bei Regentagen
        #   mit hohem Forecast aber wenig Sonne kein Drain (Batterie braucht
        #   die Energie für den Haushalt).
        sunrise_h = obs.sunrise or 6.0
        drain_fruehstart_h = get_param(matrix, self.regelkreis, 'drain_fruehstart_vor_sunrise_h', 1.0)
        drain_fenster = get_param(matrix, self.regelkreis, 'drain_fenster_ende_h', 10.0)
        drain_start_soc = get_param(matrix, self.regelkreis, 'drain_start_soc_pct', 20)
        drain_min_sunshine_h = get_param(matrix, self.regelkreis, 'drain_min_sunshine_h', 5.0)
        sunshine_h = obs.sunshine_hours or 0
        if now_h >= (sunrise_h - drain_fruehstart_h) and now_h < drain_fenster:
            if not self._drain_soc_freigegeben(obs, matrix):
                LOG.debug('Phase 0 blockiert: SOC_MIN=%s%% (Morgen-Öffnung nicht aktiv)', obs.soc_min)
            elif sunshine_h < drain_min_sunshine_h:
                LOG.debug(f'Phase 0 blockiert: Sonnenstunden {sunshine_h:.1f}h '
                          f'< {drain_min_sunshine_h:.1f}h Minimum')
            else:
                d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
                d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
                d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
                d_prognose_kw = get_param(matrix, self.regelkreis, 'drain_min_prognose_kw', 4.0)

                # HP-Eigenverbrauch herausrechnen (Selbstreferenz-Fix)
                haus_netto = (obs.house_load_w or 0)
                if obs.heizpatrone_aktiv:
                    haus_netto = max(0, haus_netto - self.HP_NENN_W)
                # WP-Leistung auch herausrechnen (eigene Prüfung unten)
                haus_netto = max(0, haus_netto - (obs.wp_power_w or 0))
                haushalt_ok = haus_netto < d_haus
                wp_ok = (obs.wp_power_w or 0) < d_wp
                ev_ok = (obs.ev_power_w or 0) < d_ev
                soc_ok = soc > drain_start_soc
                forecast_ok = (get_effective_forecast_quality(obs, matrix) or '') in ('gut', 'mittel')

                # Prognose zeigt ≥ drain_min_prognose_kw zeitnah (sunrise + Horizont)
                # Nicht den ganzen Tag prüfen — Nachmittagssonne rechtfertigt
                # keinen Morgen-Drain bei bewölktem Vormittag.
                prognose_stark = False
                d_horizont_h = get_param(matrix, self.regelkreis, 'drain_prognose_horizont_h', 3.0)
                horizont_bis_h = int(sunrise_h + d_horizont_h)
                if obs.forecast_power_profile:
                    now_h_int = int(now_h)
                    for entry in obs.forecast_power_profile:
                        h = entry.get('hour', 0)
                        if h > now_h_int and h <= horizont_bis_h and entry.get('total_ac_w', 0) >= d_prognose_kw * 1000:
                            prognose_stark = True
                            break
                if not prognose_stark:
                    LOG.debug(f'Phase 0 blockiert: keine Stunde mit ≥{d_prognose_kw:.0f}kW '
                              f'bis {horizont_bis_h}:00 (sunrise + {d_horizont_h:.0f}h)')

                # Phase 0 ist Vor-PV-Drain. Wenn Batterie bereits stark
                # von PV lädt, ist PV dominant → Drain kontraproduktiv.
                # Phase 1/1b übernimmt dann den Überschuss.
                drain_skip_w = get_param(matrix, self.regelkreis, 'drain_skip_bei_ladung_w', 2000)
                pv_laedt_bereits = p_batt > drain_skip_w
                if pv_laedt_bereits:
                    LOG.debug(f'Phase 0 übersprungen: P_Batt={p_batt:.0f}W > '
                              f'{drain_skip_w}W → PV lädt bereits')
                elif all([haushalt_ok, wp_ok, ev_ok, soc_ok, forecast_ok, prognose_stark]):
                    # Score-Abstufung nach Drain-Tiefe:
                    #   SOC_MIN=5% (voller Drain)  → 100% Score
                    #   SOC_MIN=20% (knapp offen)  →  25% Score
                    # Je weniger Drain nötig, desto weniger lohnt HP-Einsatz
                    # (Batterie-Lebensdauer an SOC-Grenzen > Eigenverbrauch).
                    komfort_min = int(get_param(matrix, 'komfort_reset', 'komfort_min_pct', 25))
                    stress_min = int(get_param(matrix, 'morgen_soc_min', 'stress_min_pct', 5))
                    drain_spanne = max(1, komfort_min - stress_min)  # 20
                    drain_tiefe = max(0, komfort_min - (obs.soc_min or komfort_min))
                    drain_frac = min(1.0, drain_tiefe / drain_spanne)
                    # Mindestens 25% Score wenn Phase 0 überhaupt greift
                    phase0_score = max(int(score * 0.25), int(score * drain_frac))
                    LOG.debug(f'Phase 0: SOC_MIN={obs.soc_min}%% '
                              f'→ drain_frac={drain_frac:.2f} '
                              f'→ Score {phase0_score}/{score}')
                    return phase0_score

        # Phase 1: Vormittags
        #   p_batt > min_lade_morgens + SOC nahe SOC_MAX (Überlaufventil-Prinzip).
        #   HP soll NUR laufen wenn Batterie am Deckel anschlägt und PV
        #   abgeregelt wird. Ohne SOC≈MAX lieber Batterie zuerst füllen.
        min_lade_morgens = get_param(matrix, self.regelkreis, 'min_ladeleistung_morgens_w', 3000)
        min_rest_kwh_morgens = get_param(matrix, self.regelkreis, 'min_rest_kwh_morgens', 20.0)
        min_rest_h_morgens = get_param(matrix, self.regelkreis, 'min_rest_h_morgens', 5.0)
        soc_nah_max_phase1 = soc >= (soc_max_eff - 5)  # z.B. ≥70% bei MAX=75

        if rest_h > min_rest_h_morgens and rest_kwh > min_rest_kwh_morgens and soc_nah_max_phase1:
            # Wiedereintritt nach Phase-1-Burst: reduzierte Schwelle
            schwelle = min_lade_morgens
            if (self._letzte_phase == 'phase1'
                    and self._letzte_aus > 0
                    and (time.time() - self._letzte_aus) < 600):  # < 10 Min seit letztem AUS
                schwelle = max(1000, min_lade_morgens - self.HP_NENN_W)
            if p_batt > schwelle:
                return score

        # Phase 2+3 Vorbereitungen (hier berechnet, damit Phase 1b sie nutzen kann)
        min_lade = self._min_lade_nach_potenzial(potenzial, matrix)
        min_rest = get_param(matrix, self.regelkreis, 'min_rest_kwh', 12.0)
        reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)

        if rest_h < 3.0:
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_nachmittag_kwh', 3.0)

        parallel_ok = self._hp_parallel_erlaubt(potenzial, wp_aktiv, ev_aktiv)

        # Phase 1b: Nulleinspeiser-Überschuss — PV wird gedrosselt
        #   SOC ≈ SOC_MAX, Batterie idle, Grid ≈ 0 → Nulleinspeiser drosselt PV.
        #   pv_total_w zeigt nur gedrosselte AC-Leistung (≈ Haushalt), NICHT
        #   was die Module könnten. Daher Forecast-Profil als Proxy nutzen.
        #   HP einschalten erzeugt Nachfrage → WR lässt PV hochfahren.
        hp_last = self.HP_NENN_W
        soc_nah_max = soc >= (soc_max_eff - 2)
        batt_idle_tol = get_param(matrix, self.regelkreis, 'batt_idle_toleranz_w', 800)
        batt_idle = abs(p_batt) < batt_idle_tol
        grid_ok_tol = get_param(matrix, self.regelkreis, 'grid_ok_toleranz_w', 500)
        grid_ok = abs(obs.grid_power_w or 0) < grid_ok_tol

        # Forecast für aktuelle Stunde: zeigt was PV KANN (nicht was WR liefert)
        forecast_jetzt_w = 0
        if obs.forecast_power_profile:
            now_h_int = int(now_h)
            for entry in obs.forecast_power_profile:
                if entry.get('hour', 0) == now_h_int:
                    forecast_jetzt_w = entry.get('total_ac_w', 0)
                    break
        pv_kann_hp = forecast_jetzt_w >= hp_last  # Forecast sagt: PV reicht für HP

        if rest_h >= min_rest_h and soc_nah_max and batt_idle and pv_kann_hp and grid_ok and parallel_ok:
            probe_cooldown_ok = (self._probe_cooldown_bis == 0
                                 or time.time() >= self._probe_cooldown_bis)
            if rest_kwh > reserve and probe_cooldown_ok:
                return score

        # Phase 2+3: Mittags/Nachmittags (nur bei rest_h ≥ min_rest_h)
        #   Batterie muss nahe SOC_MAX sein (Überlaufventil-Prinzip).
        #   HP soll PV nutzen die sonst abgeregelt wird, nicht Batterie-
        #   Reserven auf Kosten des Abend-Eigenverbrauchs verbrennen.
        soc_nah_max_phase2 = soc >= (soc_max_eff - 5)  # z.B. ≥70% bei MAX=75

        if rest_h >= min_rest_h and soc_nah_max_phase2 and p_batt > min_lade and parallel_ok:
            if rest_kwh > batt_rest_kwh + reserve:
                return score

        if rest_h >= min_rest_h and soc_nah_max_phase2 and rest_kwh > min_rest and p_batt > min_lade and parallel_ok:
            return score

        # Phase 4: Abend-Nachladezyklus (rest_h < min_rest_h)
        #   HP darf kurze Bursts fahren wenn SOC nahe SOC_MAX und PV genug liefert.
        #   Zyklus: HP ein → SOC sinkt → HP aus (SOC < Max-Schwelle) →
        #   Batterie lädt → SOC ≈ Max → HP ein.
        #   Primärziel: Batterie-Vollladung, Restkapazität für HP nutzen.
        #   Adaptiv zu SOC_MAX (Sommer 75%, Winter flexibel).
        if rest_h < min_rest_h and rest_h > 0:
            abend_ein = get_param(matrix, self.regelkreis, 'abend_soc_ein_unter_max_pct', 2)
            abend_min_pv = get_param(matrix, self.regelkreis, 'abend_min_pv_w', 1500)
            soc_nah_voll = soc >= (soc_max_eff - abend_ein)
            pv_w = obs.pv_total_w or 0
            pv_ok = pv_w >= abend_min_pv or forecast_jetzt_w >= abend_min_pv
            batt_ok = p_batt >= 0  # Batterie lädt oder idle beim Start
            if soc_nah_voll and pv_ok and batt_ok:
                return score

        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        """HP ein-/ausschalten: Notaus + Burst-Strategie."""
        now_h = datetime.now().hour + datetime.now().minute / 60
        sunset = obs.sunset or 17.0
        rest_h = max(0, sunset - now_h)
        rest_kwh = obs.forecast_rest_kwh or 0
        p_batt = obs.batt_power_w or 0
        soc = obs.batt_soc_pct if obs.batt_soc_pct is not None else 50
        soc_max_eff = obs.soc_max if obs.soc_max is not None else 75

        # ── Extern-Erkennung läuft jetzt in bewerte() ──

        # ── HP ist EIN → Notaus prüfen ──
        if obs.heizpatrone_aktiv:
            notaus_grund = None
            min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
            temp_max = get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78)

            # Extern-Erkennung auch im Aktion-Pfad nutzen
            # Default an Matrix angeglichen (2026-04-26): Matrix=1800s.
            extern_respekt = get_param(matrix, self.regelkreis, 'extern_respekt_s', 1800)
            ist_extern = (self._extern_ein_ts > 0
                          and (time.time() - self._extern_ein_ts) < extern_respekt)
            soc_schutz_abs = get_param(matrix, 'soc_schutz', 'stop_entladung_unter_pct', 5)

            # ── HARTE Kriterien: IMMER sofort ──
            if obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
                notaus_grund = f'HART: Übertemperatur ({obs.ww_temp_c:.0f}°C ≥ {temp_max}°C)'
            elif soc <= soc_schutz_abs:
                notaus_grund = f'HART: SOC {soc:.0f}% ≤ Schutzgrenze {soc_schutz_abs}%'
            # Extern-Autoritäts-Override + Hysterese
            elif ist_extern:
                extern_notaus_soc = get_param(matrix, self.regelkreis, 'extern_notaus_soc_pct', 15)
                if soc <= extern_notaus_soc:
                    notaus_grund = (f'Extern-Override: SOC {soc:.0f}% ≤ {extern_notaus_soc}% '
                                    f'→ manuelle Einschaltung überstimmt')
                else:
                    verbleibend = int(extern_respekt - (time.time() - self._extern_ein_ts))
                    LOG.debug(f'HP extern → Autorität respektiert, '
                              f'nur Übertemp/SOC-Schutz aktiv ({verbleibend}s verbleibend)')
            elif rest_h < min_rest_h:
                # Phase 4: differenziert — HP darf bei SOC≈MAX + PV weiterlaufen
                abend_aus = get_param(matrix, self.regelkreis, 'abend_soc_aus_unter_max_pct', 10)
                abend_max_entl = get_param(matrix, self.regelkreis, 'abend_max_entladung_w', 1000)
                abend_min_pv = get_param(matrix, self.regelkreis, 'abend_min_pv_w', 1500)
                soc_ok = soc >= (soc_max_eff - abend_aus)
                entl_ok = p_batt >= -abend_max_entl
                pv_ok = (obs.pv_total_w or 0) >= abend_min_pv
                if not (soc_ok and entl_ok and pv_ok):
                    if not soc_ok:
                        notaus_grund = (f'Phase 4: SOC {soc:.0f}% < SOC_MAX({soc_max_eff}%)-'
                                        f'{abend_aus}% → Batterie-Vorrang')
                    elif not pv_ok:
                        notaus_grund = (f'Phase 4: PV {obs.pv_total_w or 0:.0f}W < '
                                        f'{abend_min_pv}W → nicht genug PV')
                    else:
                        notaus_grund = (f'Phase 4: Entladung {p_batt:.0f}W > '
                                        f'-{abend_max_entl}W toleriert')

            # ── KONTEXTABHÄNGIGE Kriterien: bei normaler Engine-Steuerung ──
            else:
                potenzial = self._potenzial(obs, matrix)
                wp_aktiv, ev_aktiv = self._verbraucher_aktiv(obs, matrix)

                if self._drain_modus:
                    # Drain: gewollte Entladung — Schutzgrenzen prüfen
                    drain_stop_soc = get_param(matrix, self.regelkreis, 'drain_stop_soc_pct', 15)
                    if soc <= drain_stop_soc:
                        notaus_grund = (f'Drain-Ende: SOC {soc:.0f}% ≤ '
                                        f'drain_stop {drain_stop_soc}%')
                    else:
                        # Phase 0 (Morgen-Drain): Batterie wird VOR PV-Start
                        # entladen — PV-Check darf hier nicht greifen.
                        if self._letzte_phase != 'phase0':
                            pv_w = obs.pv_total_w or 0
                            if pv_w < self.HP_NENN_W * 0.25:
                                notaus_grund = (f'Drain-Ende: PV {pv_w:.0f}W — '
                                                f'kein Solarertrag')
                        # Netzbezug → Energie aus Netz statt PV
                        if not notaus_grund:
                            notaus_netz = get_param(matrix, self.regelkreis, 'notaus_netzbezug_w', 200)
                            grid_avg = self._grid_avg(obs)
                            notaus_ausloesen, netz_grund = self._netzbezug_notaus_ausloesen(
                                obs, matrix, rest_h, grid_avg, float(notaus_netz)
                            )
                            if notaus_ausloesen:
                                notaus_grund = f'Drain-Ende: {netz_grund}'
                        # Verbraucher-Checks (Soft-Bedingungen, mit Verzögerung)
                        if not notaus_grund:
                            d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
                            d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
                            d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
                            # HP-Eigenverbrauch herausrechnen (Selbstreferenz-Fix)
                            house_w = obs.house_load_w or 0
                            if obs.heizpatrone_aktiv:
                                house_w = max(0, house_w - self.HP_NENN_W)
                            # WP-Leistung auch herausrechnen (eigene Prüfung unten)
                            house_w = max(0, house_w - (obs.wp_power_w or 0))
                            wp_w = obs.wp_power_w or 0
                            ev_w = obs.ev_power_w or 0
                            # Delay-Auswertung: Timer wurde in bewerte() gesetzt;
                            # Abschalten erst wenn Verzögerung abgelaufen.
                            verz_s = int(get_param(
                                matrix, self.regelkreis,
                                'drain_abschalt_verzoegerung_min', 5
                            )) * 60
                            verz_abgelaufen = (
                                self._drain_lastbedingung_ts > 0
                                and (time.time() - self._drain_lastbedingung_ts) >= verz_s
                            )
                            if house_w >= d_haus * 1.2:
                                veto, veto_grund = self._drain_haushalt_prognose_veto(
                                    obs, matrix, house_w, now_h
                                )
                                if veto:
                                    LOG.info(
                                        f'Drain-Haushalt VETO: {veto_grund} '
                                        f'(Haus={house_w:.0f}W, Schwelle={d_haus}×1.2)'
                                    )
                                elif verz_abgelaufen:
                                    notaus_grund = (
                                        f'Drain-Ende (nach {verz_s // 60:.0f} Min '
                                        f'Verzögerung): Haushalt {house_w:.0f}W '
                                        f'≥ {d_haus}×1.2'
                                    )
                            if not notaus_grund and wp_w >= d_wp and verz_abgelaufen:
                                notaus_grund = (
                                    f'Drain-Ende (nach {verz_s // 60:.0f} Min '
                                    f'Verzögerung): WP {wp_w:.0f}W ≥ {d_wp}W'
                                )
                            elif not notaus_grund and ev_w >= d_ev and verz_abgelaufen:
                                notaus_grund = (
                                    f'Drain-Ende (nach {verz_s // 60:.0f} Min '
                                    f'Verzögerung): EV {ev_w:.0f}W ≥ {d_ev}W'
                                )
                else:
                    # Batterie entlädt: potenzial- und kontextabhängig
                    if p_batt < 0:
                        if not self._batt_entladung_toleriert(potenzial, soc_max_eff, obs):
                            notaus_grund = (f'Batterie entlädt ({p_batt:.0f}W) '
                                            f'bei Potenzial={potenzial}, SOC_MAX={soc_max_eff}%')

                    # Verbraucher-Konkurrenz
                    if not notaus_grund and not self._hp_parallel_erlaubt(potenzial, wp_aktiv, ev_aktiv):
                        notaus_grund = (f'Verbraucher-Konkurrenz: Potenzial={potenzial}, '
                                        f'WP={wp_aktiv}, EV={ev_aktiv}')

                    # Netzbezug (7-Min-Durchschnitt gegen Leistungssprünge/Haushaltslast)
                    if not notaus_grund:
                        notaus_netz = get_param(matrix, self.regelkreis, 'notaus_netzbezug_w', 200)
                        grid_avg = self._grid_avg(obs)
                        notaus_ausloesen, netz_grund = self._netzbezug_notaus_ausloesen(
                            obs, matrix, rest_h, grid_avg, float(notaus_netz)
                        )
                        if notaus_ausloesen:
                            notaus_grund = netz_grund

                # Burst-Timer abgelaufen
                if not notaus_grund and self._burst_ende > 0 and time.time() >= self._burst_ende:
                    if self._probe_modus:
                        # ── Probe auswerten: Hat PV auf die HP-Last reagiert? ──
                        pv_jetzt = obs.pv_total_w or 0
                        grid_jetzt = obs.grid_power_w or 0
                        pv_delta = pv_jetzt - self._probe_start_pv_w
                        probe_pv_min = get_param(matrix, self.regelkreis,
                                                 'probe_pv_delta_min_w', 500)
                        probe_grid_max = get_param(matrix, self.regelkreis,
                                                   'probe_grid_max_w', 300)

                        if pv_delta >= probe_pv_min and grid_jetzt <= probe_grid_max:
                            # Probe erfolgreich → WR hatte gedrosselt → Burst verlängern
                            verlaengern_s = get_param(matrix, self.regelkreis,
                                                      'burst_dauer_lang_s', 1800)
                            self._burst_ende = time.time() + verlaengern_s
                            self._probe_modus = False
                            LOG.info(
                                f'Probe erfolgreich: ΔPV={pv_delta:.0f}W (≥{probe_pv_min}W), '
                                f'Grid={grid_jetzt:.0f}W (≤{probe_grid_max}W) '
                                f'→ Burst verlängert um {verlaengern_s // 60} Min')
                            # Kein notaus_grund → HP bleibt ein
                        else:
                            # Probe gescheitert → HP aus, Cooldown
                            probe_cd = get_param(matrix, self.regelkreis,
                                                 'probe_cooldown_s', 600)
                            self._probe_cooldown_bis = time.time() + probe_cd
                            self._probe_modus = False
                            notaus_grund = (
                                f'Probe gescheitert: ΔPV={pv_delta:.0f}W '
                                f'(min {probe_pv_min}W), Grid={grid_jetzt:.0f}W '
                                f'(max {probe_grid_max}W) → Cooldown {probe_cd}s')
                    else:
                        # ── Auto-Verlängerung bei laufendem Burst ──
                        # Statt abschalten und 10 Min später neu starten:
                        # direkt verlängern wenn Bedingungen weiterhin gut.
                        auto_verlaengert = False

                        # Phase 0 (Morgen-Drain): innerhalb Drain-Fenster kontinuierlich laufen.
                        if self._drain_modus and self._letzte_phase == 'phase0':
                            drain_fenster = get_param(
                                matrix, self.regelkreis, 'drain_fenster_ende_h', 10.0
                            )
                            if now_h < drain_fenster:
                                verlaengern_s = get_param(
                                    matrix, self.regelkreis, 'drain_burst_dauer_s', 2700
                                )
                                self._burst_ende = time.time() + verlaengern_s
                                auto_verlaengert = True
                                laufzeit = int((time.time() - self._burst_start) / 60)
                                LOG.info(
                                    f'phase0 Auto-Verlängerung ({laufzeit} Min): '
                                    f'SOC={soc:.0f}%, rest_h={rest_h:.1f}, '
                                    f'rest_kwh={rest_kwh:.1f} '
                                    f'→ +{verlaengern_s // 60} Min')

                        # Phasen 1b/2/3: Verlängerung nur bei weiter guten Überschusskriterien.
                        if (not auto_verlaengert
                                and self._letzte_phase in ('phase1b', 'phase2', 'phase3')):
                            grid_ok_tol = get_param(matrix, self.regelkreis,
                                                    'grid_ok_toleranz_w', 500)
                            grid_jetzt = obs.grid_power_w or 0
                            soc_nah_max = soc >= (soc_max_eff - 3)
                            grid_ok = grid_jetzt < grid_ok_tol
                            reserve = get_param(matrix, self.regelkreis,
                                                'batt_reserve_kwh', 2.0)
                            rest_ok = rest_kwh > reserve + 5.0
                            if soc_nah_max and grid_ok and rest_ok:
                                verlaengern_s = get_param(matrix, self.regelkreis,
                                                          'burst_dauer_lang_s', 1800)
                                self._burst_ende = time.time() + verlaengern_s
                                auto_verlaengert = True
                                laufzeit = int((time.time() - self._burst_start) / 60)
                                LOG.info(
                                    f'{self._letzte_phase} Auto-Verlängerung '
                                    f'({laufzeit} Min): '
                                    f'SOC={soc:.0f}%, Grid={grid_jetzt:.0f}W, '
                                    f'rest_kwh={rest_kwh:.1f} '
                                    f'→ +{verlaengern_s // 60} Min')

                        if not auto_verlaengert:
                            notaus_grund = (f'Burst-Timer abgelaufen '
                                            f'({int((time.time() - self._burst_start) / 60)} Min)')

            if notaus_grund:
                # Kurz-Burst-Erkennung: War die HP kürzer als kurz_burst_max_s an?
                # Gilt nur für normale Bursts (nicht Drain), und nur wenn ein
                # Burst-Start bekannt ist.
                if self._burst_start > 0 and not self._drain_modus:
                    kurz_max_s = get_param(matrix, self.regelkreis,
                                           'kurz_burst_max_s', 420)  # 7 Min (vorher 5)
                    kurz_limit = get_param(matrix, self.regelkreis,
                                           'kurz_burst_limit', 2)
                    kurz_sperre_s = get_param(matrix, self.regelkreis,
                                              'kurz_burst_sperre_s', 1800)  # 30 Min (vorher 7)
                    burst_dauer_ist = time.time() - self._burst_start
                    if burst_dauer_ist < kurz_max_s:
                        self._kurze_burst_zaehler += 1
                        LOG.info(
                            f'HP Kurz-Burst #{self._kurze_burst_zaehler}: '
                            f'{burst_dauer_ist:.0f}s < {kurz_max_s}s Minimum '
                            f'({notaus_grund})')
                        if self._kurze_burst_zaehler >= kurz_limit:
                            self._kurz_burst_sperre_bis = time.time() + kurz_sperre_s
                            self._kurze_burst_zaehler = 0
                            LOG.warning(
                                f'HP: {kurz_limit}× Kurz-Burst → EIN-Sperre für '
                                f'{kurz_sperre_s // 60:.0f} Min')
                    else:
                        # Langer Burst → Zähler zurücksetzen
                        self._kurze_burst_zaehler = 0
                self._letzte_aus = time.time()
                self._warte_auf_engine_aus = True
                self._warte_auf_engine_aus_ts = self._letzte_aus
                self._burst_start = 0
                self._burst_ende = 0
                self._drain_modus = False
                self._probe_modus = False
                self._drain_lastbedingung_ts = 0   # Verzögerungstimer zurücksetzen
                return [{
                    'tier': 2, 'aktor': 'fritzdect',
                    'kommando': 'hp_aus',
                    'grund': f'HP AUS: {notaus_grund}',
                }]

            return []

        # ── HP ist AUS → prüfe ob Burst gestartet werden soll ─
        # Kurz-Burst-Sperre auch im Aktions-Pfad prüfen
        if self._kurz_burst_sperre_bis > 0 and time.time() < self._kurz_burst_sperre_bis:
            verbleibend = int(self._kurz_burst_sperre_bis - time.time())
            LOG.debug(f'{self._geraet_label()} Kurz-Burst-Sperre aktiv → kein EIN noch {verbleibend}s')
            return []

        batt_rest_kwh = max(0, (soc_max_eff - soc) * config.PV_BATTERY_KWH / 100)
        min_rest_h_morgens = get_param(matrix, self.regelkreis, 'min_rest_h_morgens', 5.0)
        min_rest_kwh_morgens = get_param(matrix, self.regelkreis, 'min_rest_kwh_morgens', 20.0)
        min_lade_morgens = get_param(matrix, self.regelkreis, 'min_ladeleistung_morgens_w', 3000)
        burst_lang = get_param(matrix, self.regelkreis, 'burst_dauer_lang_s', 1800)
        burst_kurz = get_param(matrix, self.regelkreis, 'burst_dauer_kurz_s', 900)

        burst_dauer = 0
        grund = ''

        # Phase 0: Morgen-Drain — Batterie mit HP leeren
        #   Frühestens sunrise-1h (prognosegetrieben, NICHT p_batt-abhängig).
        #   SOC > 20%, Stop bei SOC < 15%.
        #   Bedingung: Prognose erwartet bald hohe PV-Leistung.
        #   Guard: Mindestens 5h Sonnenschein — kein Drain bei Regentagen.
        sunrise_h = obs.sunrise or 6.0
        drain_fruehstart_h = get_param(matrix, self.regelkreis, 'drain_fruehstart_vor_sunrise_h', 1.0)
        drain_fenster = get_param(matrix, self.regelkreis, 'drain_fenster_ende_h', 10.0)
        drain_start_soc = get_param(matrix, self.regelkreis, 'drain_start_soc_pct', 20)
        drain_min_sunshine_h = get_param(matrix, self.regelkreis, 'drain_min_sunshine_h', 5.0)
        sunshine_h = obs.sunshine_hours or 0
        if now_h >= (sunrise_h - drain_fruehstart_h) and now_h < drain_fenster:
            if not self._drain_soc_freigegeben(obs, matrix):
                LOG.debug('Phase 0 Schalt-Log blockiert: SOC_MIN=%s%% (Morgen-Öffnung nicht aktiv)', obs.soc_min)
            elif sunshine_h < drain_min_sunshine_h:
                LOG.debug(f'Phase 0 Schalt-Log blockiert: Sonnenstunden {sunshine_h:.1f}h '
                          f'< {drain_min_sunshine_h:.1f}h')
            else:
                d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
                d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
                d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
                d_prognose_kw = get_param(matrix, self.regelkreis, 'drain_min_prognose_kw', 4.0)
                drain_burst = get_param(matrix, self.regelkreis, 'drain_burst_dauer_s', 2700)

                haushalt_ok = (obs.house_load_w or 0) < d_haus
                wp_ok = (obs.wp_power_w or 0) < d_wp
                ev_ok = (obs.ev_power_w or 0) < d_ev
                soc_ok = soc > drain_start_soc
                forecast_ok = (get_effective_forecast_quality(obs, matrix) or '') in ('gut', 'mittel')

                # Prognose zeitnah: nur Stunden bis sunrise + Horizont
                prognose_stark = False
                d_horizont_h = get_param(matrix, self.regelkreis, 'drain_prognose_horizont_h', 3.0)
                horizont_bis_h = int(sunrise_h + d_horizont_h)
                if obs.forecast_power_profile:
                    now_h_int = int(now_h)
                    for entry in obs.forecast_power_profile:
                        h = entry.get('hour', 0)
                        if h > now_h_int and h <= horizont_bis_h and entry.get('total_ac_w', 0) >= d_prognose_kw * 1000:
                            prognose_stark = True
                            break

                # Phase 0 ist Vor-PV-Drain: Batterie bereits stark von
                # PV geladen → Drain kontraproduktiv, Phase 1/1b übernimmt.
                drain_skip_w = get_param(matrix, self.regelkreis, 'drain_skip_bei_ladung_w', 2000)
                pv_laedt_bereits = p_batt > drain_skip_w
                if pv_laedt_bereits:
                    LOG.info(f'Phase 0 übersprungen: P_Batt={p_batt:.0f}W > '
                             f'{drain_skip_w}W → PV lädt bereits, kein Drain')
                elif all([haushalt_ok, wp_ok, ev_ok, soc_ok, forecast_ok, prognose_stark]):
                    self._burst_start = time.time()
                    self._burst_ende = time.time() + drain_burst
                    self._drain_modus = True
                    self._letzte_phase = 'phase0'
                    # Erwarteten Zustand vormerken: Observer hat HP=AUS gesehen
                    # (vor Actuator-Aktion), daher manuell auf True setzen,
                    # damit nächster Zyklus Extern-AUS erkennt wenn User abschaltet.
                    self._letzter_hp_zustand = True
                    return [{
                        'tier': 2, 'aktor': 'fritzdect',
                        'kommando': 'hp_ein',
                        'grund': (f'HP EIN (Drain {drain_burst // 60:.0f} Min): '
                                  f'Phase 0 (Morgen-Drain) SOC={soc:.0f}%, '
                                  f'Sonne={sunshine_h:.1f}h, '
                                  f'P_Batt={p_batt:.0f}W, '
                                  f'Haus={obs.house_load_w or 0:.0f}W, '
                                  f'Prognose={get_effective_forecast_quality(obs, matrix) or "?"}'),
                    }]

        # Phase 1: Vormittags (SOC≈MAX erforderlich)
        soc_nah_max_phase1 = soc >= (soc_max_eff - 5)
        if rest_h > min_rest_h_morgens and rest_kwh > min_rest_kwh_morgens and soc_nah_max_phase1:
            schwelle = min_lade_morgens
            if (self._letzte_phase == 'phase1'
                    and self._letzte_aus > 0
                    and (time.time() - self._letzte_aus) < 600):
                schwelle = max(1000, min_lade_morgens - self.HP_NENN_W)
            if p_batt > schwelle:
                burst_dauer = burst_lang
                grund = (f'Phase 1 (Vormittag): P_Batt={p_batt:.0f}W (Schwelle={schwelle:.0f}W), '
                         f'SOC={soc:.0f}%≈MAX({soc_max_eff}%), '
                         f'rest_kwh={rest_kwh:.1f}, rest_h={rest_h:.1f}')

        # Phase 1b: Nulleinspeiser-Überschuss — PV wird gedrosselt
        potenzial = self._potenzial(obs, matrix)
        min_lade = self._min_lade_nach_potenzial(potenzial, matrix)
        wp_aktiv, ev_aktiv = self._verbraucher_aktiv(obs, matrix)
        parallel_ok = self._hp_parallel_erlaubt(potenzial, wp_aktiv, ev_aktiv)

        # Forecast für aktuelle Stunde (Proxy für verfügbare PV-Kapazität)
        # Wird von Phase 1b und Phase 4 genutzt.
        forecast_jetzt_w = 0
        if obs.forecast_power_profile:
            now_h_int = int(now_h)
            for entry in obs.forecast_power_profile:
                if entry.get('hour', 0) == now_h_int:
                    forecast_jetzt_w = entry.get('total_ac_w', 0)
                    break

        min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)

        if not burst_dauer:
            hp_last = self.HP_NENN_W
            soc_nah_max = soc >= (soc_max_eff - 2)
            batt_idle_tol = get_param(matrix, self.regelkreis, 'batt_idle_toleranz_w', 800)
            batt_idle = abs(p_batt) < batt_idle_tol
            grid_ok_tol = get_param(matrix, self.regelkreis, 'grid_ok_toleranz_w', 500)
            grid_ok = abs(obs.grid_power_w or 0) < grid_ok_tol
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)
            pv_kann_hp = forecast_jetzt_w >= hp_last
            probe_cooldown_ok = (self._probe_cooldown_bis == 0
                                 or time.time() >= self._probe_cooldown_bis)

            if rest_h >= min_rest_h and soc_nah_max and batt_idle and pv_kann_hp and grid_ok and parallel_ok:
                if rest_kwh > reserve and probe_cooldown_ok:
                    # Probe-Burst: kurzer Testpuls statt vollem Burst.
                    # Nach probe_dauer_s wird ausgewertet ob PV hochgefahren ist.
                    probe_dauer = get_param(matrix, self.regelkreis, 'probe_dauer_s', 120)
                    burst_dauer = probe_dauer
                    self._probe_modus = True
                    self._probe_start_pv_w = obs.pv_total_w or 0
                    self._probe_start_grid_w = obs.grid_power_w or 0
                    grund = (f'Phase 1b (Probe {probe_dauer}s): '
                             f'SOC={soc:.0f}%≈MAX({soc_max_eff}%), '
                             f'Forecast={forecast_jetzt_w:.0f}W, '
                             f'PV_start={self._probe_start_pv_w:.0f}W, '
                             f'Potenzial={potenzial}')

        # Phase 2 (nur bei rest_h ≥ min_rest_h, SOC≈MAX)
        soc_nah_max_phase2 = soc >= (soc_max_eff - 5)
        if not burst_dauer and rest_h >= min_rest_h and soc_nah_max_phase2 and p_batt > min_lade:
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)

            if rest_kwh > batt_rest_kwh + reserve and parallel_ok:
                burst_dauer = burst_lang if rest_kwh > min_rest_kwh_morgens else burst_kurz
                grund = (f'Phase 2 (Mittag): P_Batt={p_batt:.0f}W, '
                         f'SOC={soc:.0f}%≈MAX({soc_max_eff}%), '
                         f'rest_kwh={rest_kwh:.1f}, batt_rest={batt_rest_kwh:.1f}, '
                         f'Potenzial={potenzial}, min_lade={min_lade:.0f}W')

        # Phase 3 (SOC≈MAX)
        if not burst_dauer and rest_h < 3.0 and rest_h >= min_rest_h and soc_nah_max_phase2:
            reserve_nm = get_param(matrix, self.regelkreis, 'batt_reserve_nachmittag_kwh', 3.0)
            if p_batt > min_lade and rest_kwh > batt_rest_kwh + reserve_nm:
                burst_dauer = burst_kurz
                grund = (f'Phase 3 (Nachmittag): P_Batt={p_batt:.0f}W, '
                         f'SOC={soc:.0f}%≈MAX({soc_max_eff}%), '
                         f'rest_kwh={rest_kwh:.1f}, reserve={reserve_nm:.1f}')

        # Phase 4: Abend-Nachladezyklus (rest_h < min_rest_h)
        #   SOC nahe SOC_MAX + PV produziert noch → kurzer Burst.
        #   Zyklus: HP ein → SOC sinkt → HP aus → Batt lädt → SOC ≈ Max → HP ein.
        #   Primärziel: Batterie-Vollladung, Restkapazität für HP nutzen.
        #   Adaptiv zu SOC_MAX (Sommer 75%, Winter flexibel).
        if not burst_dauer and rest_h < min_rest_h and rest_h > 0:
            abend_ein = get_param(matrix, self.regelkreis, 'abend_soc_ein_unter_max_pct', 2)
            abend_min_pv = get_param(matrix, self.regelkreis, 'abend_min_pv_w', 1500)
            soc_nah_voll = soc >= (soc_max_eff - abend_ein)
            pv_w = obs.pv_total_w or 0
            pv_ok = pv_w >= abend_min_pv or forecast_jetzt_w >= abend_min_pv
            batt_ok = p_batt >= 0  # Batterie lädt oder idle beim Start
            if soc_nah_voll and pv_ok and batt_ok:
                burst_dauer = burst_kurz
                grund = (f'Phase 4 (Abend): SOC={soc:.0f}%≈MAX({soc_max_eff}%), '
                         f'PV={pv_w:.0f}W, P_Batt={p_batt:.0f}W, rest_h={rest_h:.1f}')

        if burst_dauer > 0:
            self._burst_start = time.time()
            self._burst_ende = time.time() + burst_dauer
            self._drain_modus = False  # Normal-Burst, kein Drain
            # Phase merken für Wiedereintritt-Logik
            if 'Phase 1 ' in grund:
                self._letzte_phase = 'phase1'
            elif 'Phase 1b' in grund:
                self._letzte_phase = 'phase1b'
            elif 'Phase 2' in grund:
                self._letzte_phase = 'phase2'
            elif 'Phase 3' in grund:
                self._letzte_phase = 'phase3'
            elif 'Phase 4' in grund:
                self._letzte_phase = 'phase4'
            else:
                self._letzte_phase = ''
            # Erwarteten Zustand vormerken (wie Phase 0 oben)
            self._letzter_hp_zustand = True
            return [{
                'tier': 2, 'aktor': 'fritzdect',
                'kommando': 'hp_ein',
                'grund': f'HP EIN (Burst {burst_dauer // 60:.0f} Min): {grund}',
            }]

        return []


class RegelKlimaanlage(RegelHeizpatrone):
    # Eigenstaendige Thermoschutzregel fuer das Heizhaus via Fritz!DECT.
    #
    # Extern-Erkennung:
    #   Identisches Muster wie HP: Zustandsübergangs-Erkennung (OFF↔ON ohne
    #   Engine-Beteiligung). Während extern_respekt_s wird der erkannte Zustand
    #   (ON oder OFF) aktiv gehalten.
    #   Zusätzlich wird ein aktiver Steuerbox-Override-Hold (status=active)
    #   für klima_toggle ON/OFF symmetrisch respektiert.

    name = 'klimaanlage'
    regelkreis = 'klimaanlage'
    aktor = 'fritzdect'
    engine_zyklus = 'fast'

    def __init__(self):
        super().__init__()
        # Klima-spezifische Extern-Erkennung (getrennt von HP-State)
        self._klima_letzter_zustand: Optional[bool] = None
        self._klima_extern_ein_ts: float = 0
        self._klima_extern_aus_ts: float = 0
        self._engine_klima_ein_ts: float = 0
        self._engine_klima_aus_ts: float = 0

    # ── Extern-Erkennung ─────────────────────────────────────

    def _aktualisiere_klima_extern(self, obs: ObsState, matrix: dict) -> bool:
        """Zustandsübergangs-basierte Extern-Erkennung. Muss JEDEN Zyklus laufen.

        Erkennt ob Klima OFF↔ON ging ohne dass die Engine es veranlasst hat.
        Returns: True wenn ein externer Hold (ON/OFF) aktuell aktiv ist.
        """
        extern_respekt = float(get_param(
            matrix, self.regelkreis, 'extern_respekt_s', 1800
        ))

        # ── OFF→ON Transition ──
        if (obs.klima_aktiv
                and self._klima_letzter_zustand is not None
                and not self._klima_letzter_zustand):
            # War das die Engine? (klima_ein innerhalb 180s erzeugt)
            if ((time.time() - self._engine_klima_ein_ts) < 180
                    or klima_engine_ein_kuerzlich(180.0)):
                self._engine_klima_ein_ts = 0  # verbraucht
                LOG.debug('Klima EIN: Engine-initiiert (erkannt)')
            else:
                self._klima_extern_ein_ts = time.time()
                self._klima_extern_aus_ts = 0
                LOG.info('Klima extern eingeschaltet erkannt → Respekt %ds aktiv',
                         int(extern_respekt))
                logge_extern('fritzdect', 'Klima extern EIN',
                             'Manuell eingeschaltet (nicht durch Engine)')
                # Symmetrie zu Extern-AUS (2026-04-26):
                # cancelt alle konfligierenden klima_toggle(state=off)-Overrides.
                self._cancel_conflicting_overrides('on', geraet='klima')

        # ── ON→OFF Transition ──
        if (not obs.klima_aktiv
                and self._klima_letzter_zustand is not None
                and self._klima_letzter_zustand):
            if (time.time() - self._engine_klima_aus_ts) < 180:
                self._engine_klima_aus_ts = 0
                LOG.debug('Klima AUS: Engine-initiiert (erkannt)')
            else:
                self._klima_extern_aus_ts = time.time()
                self._klima_extern_ein_ts = 0
                LOG.info('Klima extern ausgeschaltet erkannt → Respekt %ds aktiv',
                         int(extern_respekt))
                logge_extern('fritzdect', 'Klima extern AUS',
                             'Manuell ausgeschaltet (nicht durch Engine)')
                # Race-Condition-Fix: Cancelt alle konfliktierenden klima_toggle(state=on) Overrides
                self._cancel_conflicting_overrides('off', geraet='klima')

        self._klima_letzter_zustand = obs.klima_aktiv
        now = time.time()
        return (
            (self._klima_extern_ein_ts > 0 and (now - self._klima_extern_ein_ts) < extern_respekt)
            or
            (self._klima_extern_aus_ts > 0 and (now - self._klima_extern_aus_ts) < extern_respekt)
        )

    def _aktiver_klima_extern_hold(self, matrix: dict) -> tuple[str | None, int]:
        extern_respekt = float(get_param(
            matrix, self.regelkreis, 'extern_respekt_s', 1800
        ))
        now = time.time()

        if self._klima_extern_ein_ts > 0:
            verbleibend = int(extern_respekt - (now - self._klima_extern_ein_ts))
            if verbleibend > 0:
                return 'on', verbleibend
            self._klima_extern_ein_ts = 0

        if self._klima_extern_aus_ts > 0:
            verbleibend = int(extern_respekt - (now - self._klima_extern_aus_ts))
            if verbleibend > 0:
                return 'off', verbleibend
            self._klima_extern_aus_ts = 0

        return None, 0

    @staticmethod
    def _aktiver_steuerbox_klima_hold() -> tuple[str | None, int]:
        try:
            conn = sqlite3.connect(RAM_DB_PATH, timeout=2.0)
            row = conn.execute(
                "SELECT params_json, created_at, respekt_s FROM operator_overrides "
                "WHERE action='klima_toggle' AND status='active' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
        except Exception:
            return None, 0

        if not row:
            return None, 0

        try:
            params = json.loads(row[0] or '{}')
            state = str(params.get('state') or '').strip().lower()
            if state not in {'on', 'off'}:
                return None, 0
            created_at = datetime.fromisoformat(row[1])
            remaining = int(created_at.timestamp() + int(row[2] or 0) - time.time())
            if remaining <= 0:
                return None, 0
            return state, remaining
        except Exception:
            return None, 0

    # ── Hilfsfunktionen ──────────────────────────────────────

    def _now_h(self) -> float:
        now = datetime.now()
        return now.hour + now.minute / 60.0

    def _ist_vor_sunrise(self, obs: ObsState) -> bool:
        sunrise_h = obs.sunrise if obs.sunrise is not None else 6.0
        return self._now_h() < sunrise_h

    def _get_temp_ist_c(self, obs: ObsState, matrix: dict) -> float:
        if obs.klima_temp_c is not None:
            return float(obs.klima_temp_c)
        return float(get_param(matrix, self.regelkreis, 'initial_temp_c', 15))

    def _forecast_ist_gut(self, obs: ObsState, matrix: dict) -> bool:
        return (get_effective_forecast_quality(obs, matrix) or '') == 'gut'

    def _start_temp_nach_sunrise(self, obs: ObsState, matrix: dict) -> float:
        """Start-Schwelle nach Sunrise abhängig von der Prognosequalität."""
        if self._forecast_ist_gut(obs, matrix):
            return float(get_param(
                matrix, self.regelkreis, 'initial_temp_c_gut_nach_sunrise', 15
            ))
        return float(get_param(matrix, self.regelkreis, 'initial_temp_c_maessig', 20))

    def _sunset_soc_stop(self, obs: ObsState, matrix: dict) -> bool:
        soc_stop = float(get_param(matrix, self.regelkreis, 'sunset_soc_stop_pct', 90))
        sunset = obs.sunset if obs.sunset is not None else 20.0
        now_h = self._now_h()
        soc = obs.batt_soc_pct if obs.batt_soc_pct is not None else 100
        return now_h > sunset and soc < soc_stop

    def _soll_klima_laufen(self, obs: ObsState, matrix: dict) -> bool:
        """Reine Temperatur-/Zeitlogik — ohne Extern-Berücksichtigung.

        Extern-Handling erfolgt in bewerte() und erzeuge_aktionen(),
        NICHT hier, um Zirkelschlüsse zu vermeiden.
        """
        if not self._startzeit_erreicht(obs, matrix):
            return False
        if self._sunset_soc_stop(obs, matrix):
            return False

        temp_ist = self._get_temp_ist_c(obs, matrix)
        hyst_k = float(get_param(matrix, self.regelkreis, 'temp_hysterese_k', 1.0))

        # Laufend EIN: Temperatur-Hysterese statt Tages-Latch
        if bool(obs.klima_aktiv):
            if self._ist_vor_sunrise(obs):
                temp_start = float(get_param(matrix, self.regelkreis, 'initial_temp_c', 15))
                temp_stop = temp_start - hyst_k
                return self._forecast_ist_gut(obs, matrix) and temp_ist >= temp_stop

            temp_start = self._start_temp_nach_sunrise(obs, matrix)
            temp_stop = temp_start - hyst_k
            return temp_ist >= temp_stop

        if self._ist_vor_sunrise(obs):
            temp_pre = float(get_param(matrix, self.regelkreis, 'initial_temp_c', 15))
            return self._forecast_ist_gut(obs, matrix) and temp_ist >= temp_pre

        temp_tag = self._start_temp_nach_sunrise(obs, matrix)
        return temp_ist >= temp_tag

    def _startzeit_erreicht(self, obs: ObsState, matrix: dict) -> bool:
        sunrise_h = obs.sunrise if obs.sunrise is not None else 6.0
        now_h = self._now_h()
        return now_h >= (sunrise_h - 1.0)

    # ── Haupt-Regellogik ─────────────────────────────────────

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        if not ist_aktiv(matrix, self.regelkreis):
            return 0

        basis_score = get_score_gewicht(matrix, self.regelkreis)

        # Extern-Erkennung MUSS IMMER laufen (State-Tracking jeder Zyklus)
        ist_extern = self._aktualisiere_klima_extern(obs, matrix)

        # Harte Sicherheit: Sunset+SOC-Stop — IMMER aktiv, auch bei extern.
        if self._sunset_soc_stop(obs, matrix):
            if obs.klima_aktiv:
                return int(basis_score * 2)
            return 0

        # Steuerbox-Hold (ON/OFF) hat Vorrang vor normaler Regelautomatik.
        sb_state, sb_rem = self._aktiver_steuerbox_klima_hold()
        if sb_state == 'on':
            if not obs.klima_aktiv:
                return int(basis_score * 2)
            LOG.debug('Klima Steuerbox-Hold ON aktiv (%ds verbleibend)', sb_rem)
            return 0
        if sb_state == 'off':
            if obs.klima_aktiv:
                return int(basis_score * 2)
            LOG.debug('Klima Steuerbox-Hold OFF aktiv (%ds verbleibend)', sb_rem)
            return 0

        # Extern-Hold (ON/OFF) symmetrisch respektieren.
        if ist_extern:
            ext_state, ext_rem = self._aktiver_klima_extern_hold(matrix)
            if ext_state == 'on':
                if not obs.klima_aktiv:
                    return int(basis_score * 2)
                LOG.debug('Klima extern-Hold ON aktiv (%ds verbleibend)', ext_rem)
                return 0
            if ext_state == 'off':
                if obs.klima_aktiv:
                    return int(basis_score * 2)
                LOG.debug('Klima extern-Hold OFF aktiv (%ds verbleibend)', ext_rem)
                return 0

        soll_laufen = self._soll_klima_laufen(obs, matrix)
        ist_an = bool(obs.klima_aktiv)

        if soll_laufen != ist_an:
            return basis_score
        return 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        if not ist_aktiv(matrix, self.regelkreis):
            return []

        soc_stop = float(get_param(matrix, self.regelkreis, 'sunset_soc_stop_pct', 90))

        # Harte Sicherheit: Sunset+SOC — IMMER, auch bei extern.
        if self._sunset_soc_stop(obs, matrix):
            if obs.klima_aktiv:
                self._engine_klima_aus_ts = time.time()
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_aus',
                    'grund': f'Klima AUS: nach Sonnenuntergang und SOC < {soc_stop:.0f}%',
                }]
            return []

        # Steuerbox-Hold (ON/OFF) erzwingen.
        sb_state, sb_rem = self._aktiver_steuerbox_klima_hold()
        if sb_state == 'on':
            if not obs.klima_aktiv:
                self._engine_klima_ein_ts = time.time()
                registriere_klima_engine_ein()
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_ein',
                    'grund': f'Klima EIN: Steuerbox-Respekt-Hold aktiv ({sb_rem}s verbleibend)',
                }]
            return []
        if sb_state == 'off':
            if obs.klima_aktiv:
                self._engine_klima_aus_ts = time.time()
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_aus',
                    'grund': f'Klima AUS: Steuerbox-Respekt-Hold aktiv ({sb_rem}s verbleibend)',
                }]
            return []

        # Extern-Hold (ON/OFF) erzwingen.
        ext_state, ext_rem = self._aktiver_klima_extern_hold(matrix)
        if ext_state == 'on':
            if not obs.klima_aktiv:
                self._engine_klima_ein_ts = time.time()
                registriere_klima_engine_ein()
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_ein',
                    'grund': f'Klima EIN: Extern-Respekt-Hold aktiv ({ext_rem}s verbleibend)',
                }]
            return []
        if ext_state == 'off':
            if obs.klima_aktiv:
                self._engine_klima_aus_ts = time.time()
                return [{
                    'tier': 2,
                    'aktor': 'fritzdect',
                    'kommando': 'klima_aus',
                    'grund': f'Klima AUS: Extern-Respekt-Hold aktiv ({ext_rem}s verbleibend)',
                }]
            return []

        soll_laufen = self._soll_klima_laufen(obs, matrix)
        ist_an = bool(obs.klima_aktiv)

        if soll_laufen and not ist_an:
            # Engine-Einschaltung markieren (für Extern-Erkennung im nächsten Zyklus)
            self._engine_klima_ein_ts = time.time()
            registriere_klima_engine_ein()
            if self._ist_vor_sunrise(obs):
                temp_pre = float(get_param(matrix, self.regelkreis, 'initial_temp_c', 15))
                grund = (f'Klima EIN: Vor Sunrise, Forecast gut und Temp >= {temp_pre:.1f}°C')
            else:
                temp_tag = self._start_temp_nach_sunrise(obs, matrix)
                fq = (get_effective_forecast_quality(obs, matrix) or 'unbekannt').lower()
                grund = (f'Klima EIN: Nach Sunrise, Temp >= {temp_tag:.1f}°C '
                         f'(Forecast={fq})')
            return [{
                'tier': 2,
                'aktor': 'fritzdect',
                'kommando': 'klima_ein',
                'grund': grund,
            }]

        if (not soll_laufen) and ist_an:
            self._engine_klima_aus_ts = time.time()
            temp_ist = self._get_temp_ist_c(obs, matrix)
            hyst_k = float(get_param(matrix, self.regelkreis, 'temp_hysterese_k', 1.0))
            if not self._startzeit_erreicht(obs, matrix):
                grund = 'Klima AUS: Startfenster noch nicht offen (ab sunrise-1h)'
            elif self._sunset_soc_stop(obs, matrix):
                grund = f'Klima AUS: nach Sonnenuntergang und SOC < {soc_stop:.0f}%'
            else:
                if self._ist_vor_sunrise(obs):
                    temp_pre = float(get_param(matrix, self.regelkreis, 'initial_temp_c', 15))
                    temp_stop = temp_pre - hyst_k
                    grund = (f'Klima AUS: Vor Sunrise Temp {temp_ist:.1f}°C < '
                             f'{temp_stop:.1f}°C (Schwelle {temp_pre:.1f}°C, Hyst {hyst_k:.1f}K) '
                             f'oder Forecast nicht gut')
                else:
                    temp_tag = self._start_temp_nach_sunrise(obs, matrix)
                    temp_stop = temp_tag - hyst_k
                    grund = (f'Klima AUS: Nach Sunrise Temp {temp_ist:.1f}°C < '
                             f'{temp_stop:.1f}°C (Start {temp_tag:.1f}°C, Hyst {hyst_k:.1f}K)')
            return [{
                'tier': 2,
                'aktor': 'fritzdect',
                'kommando': 'klima_aus',
                'grund': grund,
            }]

        return []
