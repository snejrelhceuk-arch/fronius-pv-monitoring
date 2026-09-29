"""
geraete_heizpatrone.py — RegelHeizpatrone (Rolle C, fast-Zyklus).

Prognosegesteuerte Burst-Strategie fuer die Fritz!DECT-Heizpatrone im
WW-Speicher (6 Phasen, ExternalRespect, Netzbezug-Integral, WP-Koordinations-
Cap). Re-Export ueber geraete.py.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections import deque, namedtuple
from datetime import datetime
from typing import Optional

import config

from automation.engine.obs_state import ObsState
from automation.engine.operator_intents import read_active_afternoon_charge_intent
from automation.engine.regeln.basis import Regel
from automation.engine.param_matrix import (
    ist_aktiv, get_param, get_score_gewicht,
    classify_forecast_kwh, get_effective_forecast_quality,
    get_forecast_tier, forecast_tier_of, FC_TIER_MITTEL, FC_TIER_GUT,
)
from automation.engine.schaltlog import logge_extern

LOG = logging.getLogger('engine')

# Harte SOC-Schutzgrenze (Entladung-Stopp). Der frühere Regelkreis 'soc_schutz'
# existiert seit 2026-03-07 nicht mehr in der Matrix; SOC<5 % wird durch
# Tier-1-Alarm abgefangen. Konstante ersetzt die Phantom-Matrix-Referenz.
SOC_SCHUTZ_ABS_PCT = 5


# Ergebnis der gemeinsamen EIN-Phasen-Entscheidung (Single-Source für den
# bewerte()-Score UND die erzeuge_aktionen()-Aktion). `score` trägt bereits die
# phasenspezifische Gewichtung (Phase 0: Skalierung nach Drain-Tiefe); die
# übrigen Phasen liefern das volle Score-Gewicht.
EinEntscheidung = namedtuple(
    'EinEntscheidung',
    ['phase', 'burst_dauer', 'score', 'is_probe', 'is_drain'],
)


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

    AUS HART (immer sofort):
      - WW-Temp ≥ 78°C, SOC ≤ 7%

    AUS Phase 4 (rest_h < 2h, differenziert):
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
        # Glättung: Netzbezug-Historie für Energie-Integral (Engine-Tick ≈60s)
        # MaxLen=10 erlaubt Fenster-Tuning bis 10 Min via Matrix; ausgewertet werden
        # die letzten `aus_netzbezug_fenster_min` Einträge.
        self._grid_history: deque = deque(maxlen=10)
        # Probe-Logik: Nulleinspeiser-Erkennung durch Testpuls
        self._probe_modus: bool = False       # Probe-Burst aktiv (kurzer Testpuls)
        self._probe_start_pv_w: float = 0     # PV-Leistung bei Probe-Start
        self._probe_cooldown_bis: float = 0   # Epoch: nächster Probe-Versuch frühestens
        # Kurz-Burst-Schutz: nach 2x Burst < 5 min → 1h Sperre
        self._kurze_burst_zaehler: int = 0        # aufeinanderfolgende Kurz-Bursts
        self._kurz_burst_sperre_bis: float = 0    # Epoch: EIN-Sperre aktiv bis
        # Watchdog: AUS wenn WW-Temperatur länger als Schwelle unbekannt
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

    # ── Dynamische WW-Temperatur-Obergrenze (WP-Koordination) ────────

    def _dynamic_temp_max_c(self, obs: ObsState, matrix: dict, now_h: float):
        """Effektive WW-Temperatur-Obergrenze fuer HP-AUS/EIN.

        Kontextabhaengige Verschaerfung der Hart-Schwelle
        `speicher_temp_max_c` (Default 78 C), damit der WW-Speicher
        kuehl genug bleibt fuer den Dimplex-WP-Lauf am Tag und der
        mechanische Thermostat (~72 C) nicht hart abwirft.

          - Morgen-Drain-Fenster (now_h < drain_fenster_ende_h):
                Cap = drain_aus_ww_temp_c  (Default 55 C)
          - <= abend_ww_cap_aktiv_vor_sunset_h vor Sunset:
                Cap = abend_ww_temp_c      (Default 65 C)
          - Sonst:
                Cap = speicher_temp_max_c  (78 C)

        Andere AUS-/EIN-Kriterien (Phase 4, Forecast, SOC, Netzbezug,
        Extern-Respekt) bleiben unveraendert; diese Funktion liefert nur
        die wirksame WW-Temperatur-Obergrenze.

        Returns: (cap_c: float, grund: str)  grund in {'hart','drain','abend'}.
        """
        hart = float(get_param(matrix, self.regelkreis, 'speicher_temp_max_c', 78))
        eff = hart
        grund = 'hart'

        drain_fenster = float(get_param(
            matrix, self.regelkreis, 'drain_fenster_ende_h', 10.0))
        if now_h < drain_fenster:
            drain_cap = float(get_param(
                matrix, self.regelkreis, 'drain_aus_ww_temp_c', 55))
            if drain_cap < eff:
                eff = drain_cap
                grund = 'drain'

        sunset_h = obs.sunset
        if sunset_h is not None:
            vor_h = float(get_param(
                matrix, self.regelkreis,
                'abend_ww_cap_aktiv_vor_sunset_h', 4.0))
            abend_cap = float(get_param(
                matrix, self.regelkreis, 'abend_ww_temp_c', 65))
            if (sunset_h - vor_h) <= now_h <= sunset_h and abend_cap < eff:
                eff = abend_cap
                grund = 'abend'

        return eff, grund

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
        tier = forecast_tier_of(potenzial)
        if tier >= FC_TIER_GUT:
            return True  # Alles parallel erlaubt
        if tier == FC_TIER_MITTEL:
            return not ev_aktiv  # WP ok, EV → HP pausiert
        # schlecht: kein Parallelbetrieb
        return not (wp_aktiv or ev_aktiv)

    def _min_lade_nach_potenzial(self, potenzial: str, matrix: dict) -> float:
        """Potenzialabhängige Mindest-Ladeleistung für Burst-Start.

        Bei gutem Potenzial reicht weniger Batterie-Ladung als Trigger,
        weil der Burst-Timer und die Potenzial-AUS die HP schützen.
        Grundlage: p_batt - HP_Last (~2kW) sollte positiv bleiben.

        Returns: Schwellwert in Watt
        """
        basis = get_param(matrix, self.regelkreis, 'min_ladeleistung_w', 5000)
        tier = forecast_tier_of(potenzial)
        if tier >= FC_TIER_GUT:
            return max(2000, basis * 0.5)    # 50% → 2500W
        if tier == FC_TIER_MITTEL:
            return max(2500, basis * 0.7)    # 70% → 3500W
        # schlecht: volle Schwelle
        return basis

    def _grid_avg(self, obs: ObsState) -> float:
        """Pflegt die Netzbezug-Historie und gibt den positiven Mittelwert zurück.

        Nur positive Werte (Bezug) werden gespeichert; Einspeisung = 0.
        Side-Effect: append in `_grid_history` — Aufruf MUSS einmal pro Tick
        passieren, damit die Energie-Integral-Auswertung in
        `_netzbezug_aus_ausloesen()` aktuelle Samples hat.
        """
        gw = obs.grid_power_w
        if gw is not None:
            self._grid_history.append(max(0, gw))
        if not self._grid_history:
            return 0.0
        return sum(self._grid_history) / len(self._grid_history)

    def _netzbezug_aus_ausloesen(
        self,
        obs: ObsState,
        matrix: dict,
    ) -> tuple[bool, str]:
        """Entscheidet HP-AUS wegen Netzbezug.

        Grundprinzip (seit 2026-05-16):
          Die Heizpatrone ist Verbraucher für PV-Überschuss. Sie darf keinen
          Netzbezug verursachen. Toleriert sind nur Schaltverluste durch
          Lastwechsel und Erzeugungsschwankungen, bis die Wechselrichter
          sich angepasst haben (Wattpilot-Start, Backofen, Wolkenfront ...).

        Messung:
          Energie-Integral des positiven Netzbezugs über
          `aus_netzbezug_fenster_min` Min (Default 5 Min). Engine-Tick ≈ 60 s,
          d.h. 5 Samples. Energie [kWh] = Σ(W) · 60 s / 3600 s / 1000 W/kW.
          Überschreitet die integrierte Energie
          `aus_netzbezug_energie_kwh` (Default 0.02 kWh ≡ Ø 240 W über 5 Min),
          gilt der Bezug als »sustained« → HP AUS.

        Veto:
          Aktueller Bezug `< aus_netzbezug_aktuell_veto_w` (200 W) → keine
          Auswertung (Historie evtl. veraltet, kein akuter Bezug).
        """
        grid_current = float(obs.grid_power_w or 0)
        current_veto_w = float(get_param(
            matrix, self.regelkreis, 'aus_netzbezug_aktuell_veto_w', 200
        ))
        if grid_current < current_veto_w:
            return False, ''

        fenster_min = int(get_param(
            matrix, self.regelkreis, 'aus_netzbezug_fenster_min', 5
        ))
        schwelle_kwh = float(get_param(
            matrix, self.regelkreis, 'aus_netzbezug_energie_kwh', 0.02
        ))
        # Letzte `fenster_min` Samples (entspricht `fenster_min` Min bei 60-s-Tick)
        recent = list(self._grid_history)[-fenster_min:]
        if len(recent) < fenster_min:
            # Noch kein volles Fenster → keine Auswertung
            return False, ''
        # Energie in kWh: Σ(W) · 60s / 3600 / 1000  =  Σ(W) / 60000
        energie_kwh = sum(recent) / 60000.0
        if energie_kwh >= schwelle_kwh:
            avg_w = sum(recent) / len(recent)
            return True, (f'Netzbezug-Integral {energie_kwh:.3f} kWh / '
                          f'{fenster_min} Min ≥ {schwelle_kwh:.3f} kWh '
                          f'(Ø {avg_w:.0f} W, aktuell {grid_current:.0f} W)')
        return False, ''

    def _ueberschuss_traegt_hp(self, obs: ObsState,
                               matrix: dict) -> tuple[bool, str]:
        """Traegt der momentane PV-Ueberschuss die HP (ohne Netzbezug)?

        Gegenstueck zum Netzbezug-Integral (`_netzbezug_aus_ausloesen`, die
        eigentliche Schutzinstanz gegen *tatsaechlichen* Netzbezug): erkennt den
        Fall, dass genug Momentan-Ueberschuss vorhanden ist, sodass die HP trotz
        konkurrierender Grossverbraucher (EV/WP) bzw. trotz Nachmittags-
        Ladewunsch NICHT hart abgeschaltet werden muss — sonst ginge die Energie
        in die Abregelung.

        Kriterien (alle erfuellt):
          - kein akuter Netzbezug: grid_power_w < ueberschuss_grid_bezug_max_w
          - Batterie nicht am Entladen:
            batt_power_w >= -ueberschuss_batt_entlade_tol_w
          - Batterie nahe voll: batt_soc_pct >= ueberschuss_soc_hoch_pct
            (nur dann ist der Ueberschuss ueberzaehlig und wuerde sonst
            abgeregelt; bei niedrigem SOC hat die Batterieladung Vorrang)

        Returns (traegt, grund). Der Netzbezug-Integral-Guard bleibt Backstop.
        """
        grid = obs.grid_power_w
        p_batt = obs.batt_power_w
        soc = obs.batt_soc_pct
        if grid is None or p_batt is None or soc is None:
            return False, ''
        grid_max = float(get_param(
            matrix, self.regelkreis, 'ueberschuss_grid_bezug_max_w', 300))
        entlade_tol = float(get_param(
            matrix, self.regelkreis, 'ueberschuss_batt_entlade_tol_w', 300))
        soc_hoch = float(get_param(
            matrix, self.regelkreis, 'ueberschuss_soc_hoch_pct', 85))
        if grid >= grid_max or p_batt < -entlade_tol or soc < soc_hoch:
            return False, ''
        return True, (f'Ueberschuss traegt HP: Netz {grid:.0f}W<{grid_max:.0f}W, '
                      f'P_Batt {p_batt:.0f}W, SOC {soc:.0f}%>={soc_hoch:.0f}%')

    def _batt_entladung_toleriert(self, potenzial: str, soc_max_eff: int,
                                   obs: ObsState) -> bool:
        """Wird Batterie-Entladung toleriert (HP darf trotzdem laufen)?

        Kontext-Logik:
                                        gut (≥ 100 kWh):     toleriert (ausreichend PV um nachzuladen)
                    mittel (40-100):      toleriert WENN SOC_MAX ≤ 75% (Batt gedeckelt,
                                                                füllen noch nicht nötig)
                    schlecht (<40):       nie toleriert
        """
        tier = forecast_tier_of(potenzial)
        if tier >= FC_TIER_GUT:
            return True
        if tier == FC_TIER_MITTEL:
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
        tagesqualitaet_gut = get_forecast_tier(obs, matrix) >= FC_TIER_GUT
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

    # ── Gemeinsame Schaltentscheidungen (bewerte + erzeuge_aktionen) ─────
    # Diese Helfer sind die Single-Source fuer Score UND Aktion: bewerte()
    # leitet daraus den Score ab, erzeuge_aktionen() die Aktion. Verhindert die
    # frueher aufgetretene stille Drift zwischen beiden Pfaden.

    def _ww_temp_aus_pruefen(self, obs: ObsState, matrix: dict,
                             now_h: float,
                             nur_hart_cap: bool = False) -> tuple[bool, str, str]:
        """WW-Temp-AUS-Entscheidung mit dynamischem WP-Koordinations-Cap.

        Nutzt `_dynamic_temp_max_c` fuer BEIDE Pfade (frueher: erzeuge_aktionen
        verglich gegen den Roh-Cap `speicher_temp_max_c` = 78 C, bewerte gegen
        den dynamischen Cap → Score/Aktion drifteten im Drain-/Abend-Fenster).

        `nur_hart_cap=True` blendet die weichen WP-Koordinations-Caps
        (drain/abend) aus und prueft nur die harte Sicherheitsschwelle
        `speicher_temp_max_c` (78 C). Damit ueberstimmt die WP-Koordination
        keine explizite Nutzer-/Operator-Autoritaet (manueller HP-EIN oder
        Steuerbox-Override, beide als Extern-EIN erkannt): der Bediener darf den
        WW-Speicher bewusst ueber die Abend-/Drain-Grenze aufheizen (z. B. bei
        WP-Defekt, HP als Ersatzheizung); nur die harte 78-C-Grenze (nahe dem
        mechanischen Thermostat ~72 C) bleibt zwingend.

        Returns: (ist_aus, grund, temp_max_grund) mit
                 temp_max_grund ∈ {'hart','drain','abend'}.
        """
        if nur_hart_cap:
            temp_max = float(get_param(
                matrix, self.regelkreis, 'speicher_temp_max_c', 78))
            temp_max_grund = 'hart'
        else:
            temp_max, temp_max_grund = self._dynamic_temp_max_c(obs, matrix, now_h)
        if obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
            grund = (f'HART: Übertemperatur ({obs.ww_temp_c:.0f}°C ≥ '
                     f'{temp_max:.0f}°C)')
            if temp_max_grund != 'hart':
                grund += f' [{temp_max_grund}-Cap, WP-Koordination]'
            return True, grund, temp_max_grund
        return False, '', temp_max_grund

    def _phase0_haushalt_netto(self, obs: ObsState) -> float:
        """Haushaltslast ohne HP-Eigenverbrauch und WP (Selbstreferenz-Fix).

        Gemeinsam fuer Phase-0-Freigabe und Drain-Soft-Check in BEIDEN Pfaden
        (frueher: erzeuge_aktionen rechnete in der Phase-0-Freigabe HP+WP NICHT
        heraus → Freigabe drifte gegen bewerte).
        """
        haus = obs.house_load_w or 0
        if obs.heizpatrone_aktiv:
            haus = max(0, haus - self.HP_NENN_W)
        return max(0, haus - (obs.wp_power_w or 0))

    def _phase4_aus_pruefen(self, obs: ObsState, matrix: dict, p_batt: float,
                            soc: float, soc_max_eff: int) -> tuple[bool, str]:
        """Phase-4-Abend-Differenzierung (AUS-Pfad, rest_h < min_rest_h).

        HP darf bei SOC≈MAX + genug PV + toleriertem Batt-Bezug weiterlaufen;
        sonst AUS. Reine Bedingung (kein Seiteneffekt); Score/Aktion leiten die
        Aufrufer ab. Returns (ist_aus, grund).
        """
        abend_aus = get_param(matrix, self.regelkreis, 'abend_soc_aus_unter_max_pct', 10)
        abend_max_entl = get_param(matrix, self.regelkreis, 'abend_max_entladung_w', 1000)
        abend_min_pv = get_param(matrix, self.regelkreis, 'abend_min_pv_w', 1500)
        soc_ok = soc >= (soc_max_eff - abend_aus)
        entl_ok = p_batt >= -abend_max_entl
        pv_ok = (obs.pv_total_w or 0) >= abend_min_pv
        if soc_ok and entl_ok and pv_ok:
            return False, ''
        if not soc_ok:
            grund = (f'Phase 4: SOC {soc:.0f}% < SOC_MAX({soc_max_eff}%)-'
                     f'{abend_aus}% → Batterie-Vorrang')
        elif not pv_ok:
            grund = (f'Phase 4: PV {obs.pv_total_w or 0:.0f}W < '
                     f'{abend_min_pv}W → nicht genug PV')
        else:
            grund = (f'Phase 4: Entladung {p_batt:.0f}W > '
                     f'-{abend_max_entl}W toleriert')
        return True, grund

    def _aus_kontext_pruefen(self, obs: ObsState, matrix: dict, potenzial: str,
                             wp_aktiv: bool, ev_aktiv: bool, soc_max_eff: int,
                             p_batt) -> tuple[str, str]:
        """Kontextabhaengige AUS-Kriterien im Normalbetrieb (kein Drain-Modus).

        Reihenfolge Batt-Entladung → Verbraucher-Konkurrenz → Netzbezug; die
        erste zutreffende gewinnt. `_grid_avg` (Historie-Pflege) wird NUR
        aufgerufen wenn weder Entladung noch Konkurrenz bereits AUS ausloesen —
        identisches Seiteneffekt-Timing wie zuvor in beiden Pfaden. Beide Aufrufer
        rufen den Helfer einmal je Tick (bewerte + erzeuge) → 2 Historie-Samples
        pro Tick bei aktivem HP, wie gehabt.

        Returns (grund_typ, grund) mit grund_typ ∈
        {'', 'entladung', 'konkurrenz', 'netzbezug'}; der Aufrufer leitet Score
        (bewerte) bzw. Aktion (erzeuge_aktionen) ab.
        """
        if p_batt is not None and p_batt < 0:
            if not self._batt_entladung_toleriert(potenzial, soc_max_eff, obs):
                return 'entladung', (f'Batterie entlädt ({p_batt:.0f}W) '
                                     f'bei Potenzial={potenzial}, SOC_MAX={soc_max_eff}%')
        if not self._hp_parallel_erlaubt(potenzial, wp_aktiv, ev_aktiv):
            # Verbraucher-Konkurrenz ist ein *praediktiver* Block (Forecast-Rest
            # niedrig + Grossverbraucher). Traegt der momentane PV-Ueberschuss
            # die HP aber nachweislich (Batt nahe voll, kein Netzbezug), nicht
            # hart abschalten — das Netzbezug-Integral unten bleibt die
            # eigentliche Schutzinstanz gegen echten Netzbezug.
            if not self._ueberschuss_traegt_hp(obs, matrix)[0]:
                return 'konkurrenz', (f'Verbraucher-Konkurrenz: Potenzial={potenzial}, '
                                      f'WP={wp_aktiv}, EV={ev_aktiv}')
        self._grid_avg(obs)  # Side-Effect: Historie pflegen
        aus_ausloesen, netz_grund = self._netzbezug_aus_ausloesen(obs, matrix)
        if aus_ausloesen:
            return 'netzbezug', netz_grund
        return '', ''

    def _ein_entscheidung(self, obs: ObsState, matrix: dict) -> Optional[EinEntscheidung]:
        """Gemeinsame EIN-Phasen-Entscheidung (Single-Source Score + Aktion).

        Repliziert die Phasen-Gate-Logik (Phase 0/1/1b/2/4), die früher in
        `bewerte()` (Score) und `erzeuge_aktionen()` (Aktion/Burst) doppelt lag.
        Reine Entscheidung ohne Seiteneffekte: `bewerte()` nimmt `score`,
        `erzeuge_aktionen()` nimmt `phase`/`burst_dauer`/`is_probe`/`is_drain` und
        leitet daraus Burst-/Probe-/Drain-Zustand ab.

        Frühere stille Divergenzen sind auf den `bewerte()`-Gate vereinheitlicht
        (der im Engine-Betrieb ohnehin entscheidet, ob `erzeuge_aktionen()`
        überhaupt läuft — die Aktion ist die Schnittmenge beider Pfade):
          - Phase 2 nutzt nur `rest_kwh > batt_rest + reserve`; die frühere
            Zusatzbedingung `rest_kwh > min_rest_kwh` (12) war bei SOC≈MAX
            (batt_rest ≤ 5 %·20,48 kWh ≈ 1 kWh, +reserve ≤ 3 kWh) nie zusätzlich
            erreichbar → entfällt.
          - `reserve` nutzt den Nachmittagswert (`batt_reserve_nachmittag_kwh`,
            rest_h < 3 h) auch in Phase 1b/2 (erzeuge_aktionen nutzte dort fix 2,0).
          - Die frühere Phase 3 (Nachmittag) geht in Phase 2 auf (sie war stets
            von Phase 2 verdrängt bzw. vom bewerte-Gate ausgeschlossen).

        Returns EinEntscheidung oder None (kein EIN).
        """
        now_h = datetime.now().hour + datetime.now().minute / 60
        sunset = obs.sunset or 17.0
        rest_h = max(0, sunset - now_h)
        p_batt = obs.batt_power_w
        rest_kwh = obs.forecast_rest_kwh
        soc = obs.batt_soc_pct
        soc_max_eff = obs.soc_max or 75

        if p_batt is None or rest_kwh is None or soc is None:
            return None

        score = get_score_gewicht(matrix, self.regelkreis)
        min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
        burst_lang = get_param(matrix, self.regelkreis, 'burst_dauer_lang_s', 1800)
        burst_kurz = get_param(matrix, self.regelkreis, 'burst_dauer_kurz_s', 900)

        batt_rest_kwh = max(0, (soc_max_eff - soc) * config.PV_BATTERY_KWH / 100)
        potenzial = self._potenzial(obs, matrix)
        wp_aktiv, ev_aktiv = self._verbraucher_aktiv(obs, matrix)

        # ── Phase 0: Morgen-Drain (prognosegetrieben, vor PV-Start) ──
        sunrise_h = obs.sunrise or 6.0
        drain_fruehstart_h = get_param(matrix, self.regelkreis, 'drain_fruehstart_vor_sunrise_h', 1.0)
        drain_fenster = get_param(matrix, self.regelkreis, 'drain_fenster_ende_h', 10.0)
        drain_start_soc = get_param(matrix, self.regelkreis, 'drain_start_soc_pct', 20)
        drain_min_sunshine_h = get_param(matrix, self.regelkreis, 'drain_min_sunshine_h', 5.0)
        sunshine_h = obs.sunshine_hours or 0
        if (now_h >= (sunrise_h - drain_fruehstart_h) and now_h < drain_fenster
                and self._drain_soc_freigegeben(obs, matrix)
                and sunshine_h >= drain_min_sunshine_h):
            d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
            d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
            d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
            d_prognose_kw = get_param(matrix, self.regelkreis, 'drain_min_prognose_kw', 4.0)
            haushalt_ok = self._phase0_haushalt_netto(obs) < d_haus
            wp_ok = (obs.wp_power_w or 0) < d_wp
            ev_ok = (obs.ev_power_w or 0) < d_ev
            soc_ok = soc > drain_start_soc
            forecast_ok = get_forecast_tier(obs, matrix) >= FC_TIER_MITTEL

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

            drain_skip_w = get_param(matrix, self.regelkreis, 'drain_skip_bei_ladung_w', 2000)
            pv_laedt_bereits = p_batt > drain_skip_w
            if not pv_laedt_bereits and all(
                    [haushalt_ok, wp_ok, ev_ok, soc_ok, forecast_ok, prognose_stark]):
                komfort_min = int(get_param(matrix, 'komfort_reset', 'komfort_min_pct', 25))
                stress_min = int(get_param(matrix, 'morgen_soc_min', 'stress_min_pct', 5))
                drain_spanne = max(1, komfort_min - stress_min)
                drain_tiefe = max(0, komfort_min - (obs.soc_min or komfort_min))
                drain_frac = min(1.0, drain_tiefe / drain_spanne)
                phase0_score = max(int(score * 0.25), int(score * drain_frac))
                drain_burst = get_param(matrix, self.regelkreis, 'drain_burst_dauer_s', 2700)
                return EinEntscheidung('phase0', drain_burst, phase0_score, False, True)

        # ── Phase 1: Vormittags (SOC≈MAX, Überlaufventil) ──
        min_lade_morgens = get_param(matrix, self.regelkreis, 'min_ladeleistung_morgens_w', 3000)
        min_rest_kwh_morgens = get_param(matrix, self.regelkreis, 'min_rest_kwh_morgens', 20.0)
        min_rest_h_morgens = get_param(matrix, self.regelkreis, 'min_rest_h_morgens', 5.0)
        soc_nah_max_phase1 = soc >= (soc_max_eff - 5)
        if rest_h > min_rest_h_morgens and rest_kwh > min_rest_kwh_morgens and soc_nah_max_phase1:
            schwelle = min_lade_morgens
            if (self._letzte_phase == 'phase1' and self._letzte_aus > 0
                    and (time.time() - self._letzte_aus) < 600):
                schwelle = max(1000, min_lade_morgens - self.HP_NENN_W)
            if p_batt > schwelle:
                return EinEntscheidung('phase1', burst_lang, score, False, False)

        # ── Phase 2/3 Vorbereitungen (auch von Phase 1b genutzt) ──
        min_lade = self._min_lade_nach_potenzial(potenzial, matrix)
        reserve = get_param(matrix, self.regelkreis, 'batt_reserve_kwh', 2.0)
        if rest_h < 3.0:
            reserve = get_param(matrix, self.regelkreis, 'batt_reserve_nachmittag_kwh', 3.0)
        parallel_ok = self._hp_parallel_erlaubt(potenzial, wp_aktiv, ev_aktiv)

        # ── Phase 1b: Nulleinspeiser-Überschuss (Probe-Puls) ──
        hp_last = self.HP_NENN_W
        soc_nah_max = soc >= (soc_max_eff - 2)
        batt_idle_tol = get_param(matrix, self.regelkreis, 'batt_idle_toleranz_w', 800)
        batt_idle = abs(p_batt) < batt_idle_tol
        grid_ok_tol = get_param(matrix, self.regelkreis, 'grid_ok_toleranz_w', 500)
        grid_ok = abs(obs.grid_power_w or 0) < grid_ok_tol
        forecast_jetzt_w = 0
        if obs.forecast_power_profile:
            now_h_int = int(now_h)
            for entry in obs.forecast_power_profile:
                if entry.get('hour', 0) == now_h_int:
                    forecast_jetzt_w = entry.get('total_ac_w', 0)
                    break
        pv_kann_hp = forecast_jetzt_w >= hp_last
        if rest_h >= min_rest_h and soc_nah_max and batt_idle and pv_kann_hp and grid_ok and parallel_ok:
            probe_cooldown_ok = (self._probe_cooldown_bis == 0
                                 or time.time() >= self._probe_cooldown_bis)
            if rest_kwh > reserve and probe_cooldown_ok:
                probe_dauer = get_param(matrix, self.regelkreis, 'probe_dauer_s', 120)
                return EinEntscheidung('phase1b', probe_dauer, score, True, False)

        # ── Phase 2 (Mittag) inkl. Nachmittag (früher separate Phase 3) ──
        soc_nah_max_phase2 = soc >= (soc_max_eff - 5)
        if (rest_h >= min_rest_h and soc_nah_max_phase2 and p_batt > min_lade
                and parallel_ok and rest_kwh > batt_rest_kwh + reserve):
            burst_dauer = burst_lang if rest_kwh > min_rest_kwh_morgens else burst_kurz
            return EinEntscheidung('phase2', burst_dauer, score, False, False)

        # ── Phase 4: Abend-Nachladezyklus (rest_h < min_rest_h) ──
        if rest_h < min_rest_h and rest_h > 0:
            abend_ein = get_param(matrix, self.regelkreis, 'abend_soc_ein_unter_max_pct', 2)
            abend_min_pv = get_param(matrix, self.regelkreis, 'abend_min_pv_w', 1500)
            soc_nah_voll = soc >= (soc_max_eff - abend_ein)
            pv_w = obs.pv_total_w or 0
            pv_ok = pv_w >= abend_min_pv or forecast_jetzt_w >= abend_min_pv
            batt_ok = p_batt >= 0
            if soc_nah_voll and pv_ok and batt_ok:
                return EinEntscheidung('phase4', burst_kurz, score, False, False)

        return None

    def bewerte(self, obs: ObsState, matrix: dict) -> int:
        """Score für HP-Steuerung.

        Drei Pfade:
          1. AUS — IMMER aktiv, auch bei aktiv=False
          2. Drain-EIN (Phase 0) — wenn aktiv, Batterie morgens leeren
          3. Burst-EIN (Phase 1-3) — nur bei aktiv=True (Strategie).
        """
        # hp_nenn_w aus Matrix (verhaltensneutral: Default = bisheriger Hardcode 2000 W)
        self.HP_NENN_W = get_param(matrix, self.regelkreis, 'hp_nenn_w', 2000)
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

        intent = read_active_afternoon_charge_intent()
        if intent and bool(intent.get('pause_hp_until_target', False)):
            target_soc = int(intent.get('target_soc_pct', 100))
            soc_now = float(obs.batt_soc_pct if obs.batt_soc_pct is not None else 0.0)
            if soc_now < max(0, target_soc - 1):
                # HP nur sperren wenn Batterie aktiv laedt UND Ladeleistung < 8 kW.
                # Bei starker Ladung (>=8 kW) reicht PV fuer beide; bei fehlender
                # Ladung (Batterie entlaedt oder idle) ist kein Konflikt vorhanden.
                # Ausnahme: momentaner PV-Ueberschuss traegt die HP bereits (Batt
                # nahe voll, kein Netzbezug) — dann nicht abschalten, sonst ginge
                # die Energie in die Abregelung (Nachmittags-Ladewunsch-Fall).
                batt_w = obs.batt_power_w
                if (batt_w is not None and 0 < batt_w < 8000
                        and not self._ueberschuss_traegt_hp(obs, matrix)[0]):
                    if obs.heizpatrone_aktiv:
                        return int(score * 1.6)
                    return 0

        # ── AUS-Pfad: IMMER aktiv ──
        if obs.heizpatrone_aktiv:
            min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)
            soc_schutz_abs = SOC_SCHUTZ_ABS_PCT

            # ── HARTE Kriterien: IMMER sofort ──
            # Bei manueller/Operator-Autoritaet (ist_extern: manueller HP-EIN
            # ODER Steuerbox-Override, beide als Extern-EIN erkannt) gelten NUR
            # die harte 78-C-Sicherheitsschwelle und die SOC-Floors — die
            # weichen WP-Koordinations-Caps (drain/abend) ueberstimmen den
            # Bediener nicht (WP-Defekt-Fall: HP als Ersatzheizung ueber 65 C).
            if obs.ww_temp_c is not None:
                self._ww_temp_letzte_gueltig = time.time()
                ww_aus, ww_grund, _ = self._ww_temp_aus_pruefen(
                    obs, matrix, now_h, nur_hart_cap=ist_extern)
                if ww_aus:
                    LOG.info('HP-AUS: %s', ww_grund)
                    return int(score * 1.5)
            else:
                # Watchdog: WW-Temp unbekannt (Modbus-Ausfall) → AUS nach Timeout
                ww_watchdog_s = get_param(
                    matrix, self.regelkreis, 'ww_temp_watchdog_s', 300
                )
                if (self._ww_temp_letzte_gueltig > 0
                        and (time.time() - self._ww_temp_letzte_gueltig) > ww_watchdog_s):
                    LOG.warning('HP-AUS: WW-Temperatur seit %ds unbekannt (Modbus?)',
                                int(time.time() - self._ww_temp_letzte_gueltig))
                    return int(score * 1.5)
            if (obs.batt_soc_pct or 0) <= soc_schutz_abs:
                return int(score * 1.5)
            # Extern-Autoritäts-Override: manuelle Einschaltung bei niedrigem SOC überstimmen
            if ist_extern:
                extern_aus_soc = get_param(matrix, self.regelkreis, 'extern_aus_soc_pct', 15)
                if (obs.batt_soc_pct or 0) <= extern_aus_soc:
                    return int(score * 1.5)
            # rest_h < min_rest_h: Phase-4-Differenzierung
            # HP darf weiterlaufen wenn SOC nahe SOC_MAX und PV noch produziert.
            # Primärziel: Batterie-Vollladung, HP nutzt Restkapazität.
            # Bei manueller Autorität (ist_extern) pausiert — User hat Vorrang.
            if rest_h < min_rest_h and not ist_extern:
                phase4_aus, _ = self._phase4_aus_pruefen(
                    obs, matrix, (p_batt or 0), (obs.batt_soc_pct or 0),
                    (obs.soc_max or 75))
                if phase4_aus:
                    return int(score * 1.5)
                # Abend-Bedingungen erfüllt → kein AUS, weiter prüfen

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
                    self._grid_avg(obs)  # Side-Effect: Historie pflegen
                    aus_ausloesen, _ = self._netzbezug_aus_ausloesen(obs, matrix)
                    if aus_ausloesen:
                        return int(score * 1.5)
                    d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
                    d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
                    d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
                    haus_netto = self._phase0_haushalt_netto(obs)
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
                    # Kontext-AUS (Entladung/Konkurrenz/Netzbezug) — Single-Source
                    grund_typ, _ = self._aus_kontext_pruefen(
                        obs, matrix, potenzial, wp_aktiv, ev_aktiv,
                        soc_max_eff, p_batt)
                    if grund_typ == 'konkurrenz':
                        return int(score * 1.2)
                    if grund_typ:
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

        if p_batt is None or rest_kwh is None or soc is None:
            return 0

        temp_max, temp_max_grund = self._dynamic_temp_max_c(obs, matrix, now_h)
        if obs.ww_temp_c is not None and obs.ww_temp_c >= temp_max:
            if temp_max_grund != 'hart':
                LOG.debug(
                    'HP-EIN blockiert: WW_Temp %.1f°C ≥ Cap %.0f°C (%s) — '
                    'WP-Koordination', obs.ww_temp_c, temp_max, temp_max_grund)
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

        # Gemeinsame Phasen-Entscheidung (Single-Source mit erzeuge_aktionen)
        dec = self._ein_entscheidung(obs, matrix)
        return dec.score if dec is not None else 0

    def erzeuge_aktionen(self, obs: ObsState, matrix: dict) -> list[dict]:
        """HP ein-/ausschalten: AUS + Burst-Strategie."""
        # hp_nenn_w aus Matrix (verhaltensneutral: Default = bisheriger Hardcode 2000 W)
        self.HP_NENN_W = get_param(matrix, self.regelkreis, 'hp_nenn_w', 2000)
        now_h = datetime.now().hour + datetime.now().minute / 60
        sunset = obs.sunset or 17.0
        rest_h = max(0, sunset - now_h)
        rest_kwh = obs.forecast_rest_kwh or 0
        p_batt = obs.batt_power_w or 0
        soc = obs.batt_soc_pct if obs.batt_soc_pct is not None else 50
        soc_max_eff = obs.soc_max if obs.soc_max is not None else 75

        intent = read_active_afternoon_charge_intent()
        if intent and bool(intent.get('pause_hp_until_target', False)):
            target_soc = int(intent.get('target_soc_pct', 100))
            if soc < max(0, target_soc - 1):
                # HP nur abschalten wenn Batterie aktiv laedt UND Ladeleistung < 8 kW
                # UND kein momentaner PV-Ueberschuss die HP bereits traegt (Batt
                # nahe voll + kein Netzbezug → Energie sonst abgeregelt).
                if (0 < p_batt < 8000
                        and not self._ueberschuss_traegt_hp(obs, matrix)[0]):
                    if obs.heizpatrone_aktiv:
                        remaining_min = int(intent.get('respekt_remaining_s', 0)) // 60
                        self._letzte_aus = time.time()
                        self._warte_auf_engine_aus = True
                        self._warte_auf_engine_aus_ts = self._letzte_aus
                        self._burst_start = 0
                        self._burst_ende = 0
                        self._drain_modus = False
                        self._probe_modus = False
                        self._drain_lastbedingung_ts = 0
                        return [{
                            'tier': 2, 'aktor': 'fritzdect',
                            'kommando': 'hp_aus',
                            'grund': (f'HP AUS: Nachmittag-Ladewunsch aktiv, Ladung {p_batt:.0f}W < 8 kW '
                                      f'(SOC {soc:.0f}% < Ziel {target_soc}%, '
                                      f'Rest ~{remaining_min} min)'),
                        }]
                    return []

        # ── Extern-Erkennung läuft jetzt in bewerte() ──

        # ── HP ist EIN → AUS prüfen ──
        if obs.heizpatrone_aktiv:
            aus_grund = None
            should_cancel_override = False  # True → cancelt hp_toggle(state=on) Override
            min_rest_h = get_param(matrix, self.regelkreis, 'min_rest_h', 2.0)

            # Extern-Erkennung auch im Aktion-Pfad nutzen
            # Default an Matrix angeglichen (2026-04-26): Matrix=1800s.
            extern_respekt = get_param(matrix, self.regelkreis, 'extern_respekt_s', 1800)
            ist_extern = (self._extern_ein_ts > 0
                          and (time.time() - self._extern_ein_ts) < extern_respekt)
            soc_schutz_abs = SOC_SCHUTZ_ABS_PCT

            # ── HARTE Kriterien: IMMER sofort ──
            # Bei manueller/Operator-Autoritaet (ist_extern) nur die harte
            # 78-C-Schwelle; die weichen WP-Koordinations-Caps (drain/abend)
            # ueberstimmen den Bediener nicht (s. bewerte()).
            ww_aus, ww_grund, _ = self._ww_temp_aus_pruefen(
                obs, matrix, now_h, nur_hart_cap=ist_extern)
            if ww_aus:
                aus_grund = ww_grund
                should_cancel_override = True
            elif soc <= soc_schutz_abs:
                aus_grund = f'HART: SOC {soc:.0f}% ≤ Schutzgrenze {soc_schutz_abs}%'
                should_cancel_override = True
            # Extern-Autoritäts-Override + Hysterese
            elif ist_extern:
                extern_aus_soc = get_param(matrix, self.regelkreis, 'extern_aus_soc_pct', 15)
                if soc <= extern_aus_soc:
                    aus_grund = (f'Extern-Override: SOC {soc:.0f}% ≤ {extern_aus_soc}% '
                                    f'→ manuelle Einschaltung überstimmt')
                    should_cancel_override = True
                else:
                    verbleibend = int(extern_respekt - (time.time() - self._extern_ein_ts))
                    LOG.debug(f'HP extern → Autorität respektiert, '
                              f'nur Übertemp/SOC-Schutz aktiv ({verbleibend}s verbleibend)')
            elif rest_h < min_rest_h:
                # Phase 4: differenziert — HP darf bei SOC≈MAX + PV weiterlaufen
                phase4_aus, phase4_grund = self._phase4_aus_pruefen(
                    obs, matrix, p_batt, soc, soc_max_eff)
                if phase4_aus:
                    should_cancel_override = True
                    aus_grund = phase4_grund

            # ── KONTEXTABHÄNGIGE Kriterien: bei normaler Engine-Steuerung ──
            else:
                potenzial = self._potenzial(obs, matrix)
                wp_aktiv, ev_aktiv = self._verbraucher_aktiv(obs, matrix)

                if self._drain_modus:
                    # Drain: gewollte Entladung — Schutzgrenzen prüfen
                    drain_stop_soc = get_param(matrix, self.regelkreis, 'drain_stop_soc_pct', 15)
                    if soc <= drain_stop_soc:
                        aus_grund = (f'Drain-Ende: SOC {soc:.0f}% ≤ '
                                        f'drain_stop {drain_stop_soc}%')
                    else:
                        # Phase 0 (Morgen-Drain): Batterie wird VOR PV-Start
                        # entladen — PV-Check darf hier nicht greifen.
                        if self._letzte_phase != 'phase0':
                            pv_w = obs.pv_total_w or 0
                            if pv_w < self.HP_NENN_W * 0.25:
                                aus_grund = (f'Drain-Ende: PV {pv_w:.0f}W — '
                                                f'kein Solarertrag')
                        # Netzbezug → Energie aus Netz statt PV
                        if not aus_grund:
                            self._grid_avg(obs)  # Side-Effect: Historie pflegen
                            aus_ausloesen, netz_grund = self._netzbezug_aus_ausloesen(obs, matrix)
                            if aus_ausloesen:
                                aus_grund = f'Drain-Ende: {netz_grund}'
                        # Verbraucher-Checks (Soft-Bedingungen, mit Verzögerung)
                        if not aus_grund:
                            d_haus = get_param(matrix, self.regelkreis, 'drain_max_haushalt_w', 700)
                            d_wp = get_param(matrix, self.regelkreis, 'drain_max_wp_w', 500)
                            d_ev = get_param(matrix, self.regelkreis, 'drain_max_ev_w', 1000)
                            house_w = self._phase0_haushalt_netto(obs)
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
                                    aus_grund = (
                                        f'Drain-Ende (nach {verz_s // 60:.0f} Min '
                                        f'Verzögerung): Haushalt {house_w:.0f}W '
                                        f'≥ {d_haus}×1.2'
                                    )
                            if not aus_grund and wp_w >= d_wp and verz_abgelaufen:
                                aus_grund = (
                                    f'Drain-Ende (nach {verz_s // 60:.0f} Min '
                                    f'Verzögerung): WP {wp_w:.0f}W ≥ {d_wp}W'
                                )
                            elif not aus_grund and ev_w >= d_ev and verz_abgelaufen:
                                aus_grund = (
                                    f'Drain-Ende (nach {verz_s // 60:.0f} Min '
                                    f'Verzögerung): EV {ev_w:.0f}W ≥ {d_ev}W'
                                )
                else:
                    # Kontext-AUS (Entladung/Konkurrenz/Netzbezug) — Single-Source
                    grund_typ, kontext_grund = self._aus_kontext_pruefen(
                        obs, matrix, potenzial, wp_aktiv, ev_aktiv,
                        soc_max_eff, p_batt)
                    if grund_typ:
                        aus_grund = kontext_grund
                        should_cancel_override = True

                # Burst-Timer abgelaufen
                if not aus_grund and self._burst_ende > 0 and time.time() >= self._burst_ende:
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
                            # Kein aus_grund → HP bleibt ein
                        else:
                            # Probe gescheitert → HP aus, Cooldown
                            probe_cd = get_param(matrix, self.regelkreis,
                                                 'probe_cooldown_s', 600)
                            self._probe_cooldown_bis = time.time() + probe_cd
                            self._probe_modus = False
                            aus_grund = (
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
                            aus_grund = (f'Burst-Timer abgelaufen '
                                            f'({int((time.time() - self._burst_start) / 60)} Min)')

            if aus_grund:
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
                            f'({aus_grund})')
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
                
                # Cancel konfligierende hp_toggle(state=on) Overrides bei starken Bedingungen.
                # Verhindert Pingpong: Override will EIN → Regel schaltet AUS → Override reapplied EIN → ...
                # Nur bei kontextabhängigen/harten Kriterien, NICHT bei normalem Burst-Ende.
                if should_cancel_override:
                    self._cancel_conflicting_overrides('off')
                
                return [{
                    'tier': 2, 'aktor': 'fritzdect',
                    'kommando': 'hp_aus',
                    'grund': f'HP AUS: {aus_grund}',
                }]

            return []

        # ── HP ist AUS → prüfe ob Burst gestartet werden soll ─
        # Kurz-Burst-Sperre auch im Aktions-Pfad prüfen
        if self._kurz_burst_sperre_bis > 0 and time.time() < self._kurz_burst_sperre_bis:
            verbleibend = int(self._kurz_burst_sperre_bis - time.time())
            LOG.debug(f'{self._geraet_label()} Kurz-Burst-Sperre aktiv → kein EIN noch {verbleibend}s')
            return []

        # Gemeinsame Phasen-Entscheidung (Single-Source mit bewerte).
        dec = self._ein_entscheidung(obs, matrix)
        if dec is None:
            return []

        self._burst_start = time.time()
        self._burst_ende = time.time() + dec.burst_dauer
        self._grid_history.clear()   # Stale-History-Fix: Deque frisch starten
        self._drain_modus = dec.is_drain
        if dec.is_probe:
            self._probe_modus = True
            self._probe_start_pv_w = obs.pv_total_w or 0
        self._letzte_phase = dec.phase
        # Erwarteten Zustand vormerken: Observer hat HP=AUS gesehen (vor Actuator-
        # Aktion), daher manuell auf True setzen, damit der nächste Zyklus eine
        # manuelle User-Abschaltung als Extern-AUS erkennt.
        self._letzter_hp_zustand = True

        if dec.phase == 'phase0':
            grund = (f'Phase 0 (Morgen-Drain) SOC={soc:.0f}%, '
                     f'Sonne={obs.sunshine_hours or 0:.1f}h, P_Batt={p_batt:.0f}W, '
                     f'Haus={obs.house_load_w or 0:.0f}W, '
                     f'Prognose={get_effective_forecast_quality(obs, matrix) or "?"}')
        elif dec.phase == 'phase1':
            grund = (f'Phase 1 (Vormittag): P_Batt={p_batt:.0f}W, '
                     f'SOC={soc:.0f}%≈MAX({soc_max_eff}%), '
                     f'rest_kwh={rest_kwh:.1f}, rest_h={rest_h:.1f}')
        elif dec.phase == 'phase1b':
            grund = (f'Phase 1b (Probe {dec.burst_dauer}s): '
                     f'SOC={soc:.0f}%≈MAX({soc_max_eff}%), '
                     f'PV_start={self._probe_start_pv_w:.0f}W')
        elif dec.phase == 'phase2':
            grund = (f'Phase 2 (Mittag): P_Batt={p_batt:.0f}W, '
                     f'SOC={soc:.0f}%≈MAX({soc_max_eff}%), rest_kwh={rest_kwh:.1f}')
        elif dec.phase == 'phase4':
            grund = (f'Phase 4 (Abend): SOC={soc:.0f}%≈MAX({soc_max_eff}%), '
                     f'PV={obs.pv_total_w or 0:.0f}W, P_Batt={p_batt:.0f}W, rest_h={rest_h:.1f}')
        else:
            grund = dec.phase

        art = 'Drain' if dec.is_drain else 'Burst'
        return [{
            'tier': 2, 'aktor': 'fritzdect',
            'kommando': 'hp_ein',
            'grund': f'HP EIN ({art} {dec.burst_dauer // 60:.0f} Min): {grund}',
        }]
