#!/usr/bin/env python3
"""
Characterization-Test-Harness fuer RegelHeizpatrone (golden-master).

Zweck: Schnappschuss des IST-Verhaltens (Score + erzeugte Aktionen) ueber ein
kuratiertes Szenario-Gitter. Dient als Sicherheitsnetz fuer den geplanten
HP-Phasen-State-Machine-Refactor: Ein Umbau muss EXAKT dieselben Aktionen
liefern (Golden bleibt gruen).

Deterministik:
  - frische RegelHeizpatrone() je Szenario (kein akkumulierter State, kein EXTERN)
  - datetime.now()/utcnow() und time.time() werden auf feste Werte gepatcht
  - erfasst werden nur verhaltensrelevante Felder (kommando/aktor/wert), nicht
    der dynamische Begruendungstext

Nutzung:
  python3 tests/test_heizpatrone_characterization.py            # vergleicht gegen Golden
  python3 tests/test_heizpatrone_characterization.py --update   # Golden neu schreiben
"""
from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import sys
import time as _real_time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from automation.engine.obs_state import ObsState  # noqa: E402
from automation.engine.param_matrix import lade_matrix  # noqa: E402
# RegelHeizpatrone lebt seit dem Geraete-Split in geraete_heizpatrone; die
# Zeit-Patches muessen dieses Modul treffen (nicht den geraete-Aggregator).
import automation.engine.regeln.geraete_heizpatrone as geraete  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden',
                      'heizpatrone_golden.json')
FIXED_EPOCH = 1782000000.0  # fester time.time()-Wert (Cooldowns inaktiv bei frischer Regel)


class _FixedDateTime(_dt.datetime):
    """datetime-Subklasse mit fixem now()/utcnow(); alles andere wie echt."""
    _fixed = _dt.datetime(2026, 6, 29, 12, 0)

    @classmethod
    def now(cls, tz=None):  # noqa: A003
        return cls._fixed

    @classmethod
    def utcnow(cls):
        return cls._fixed


class _FakeTime:
    """time-Modul-Proxy mit fixem time(); andere Attribute delegiert."""
    def time(self):
        return FIXED_EPOCH

    def __getattr__(self, name):
        return getattr(_real_time, name)


# ── Basis-ObsState + Szenarien ───────────────────────────────
def _base_obs() -> ObsState:
    o = ObsState()
    o.sunrise = 7.5
    o.sunset = 17.0
    o.sunshine_hours = 9.0
    o.batt_soc_pct = 50.0
    o.soc_max = 75
    o.soc_min = 5
    o.soc_mode = 'manual'
    o.batt_power_w = 0.0
    o.pv_total_w = 0.0
    o.grid_power_w = 0.0
    o.house_load_w = 600.0
    o.forecast_kwh = 45.0
    o.forecast_rest_kwh = 30.0
    o.ww_temp_c = 55.0
    o.wp_power_w = 0.0
    o.ev_charging = False
    o.ev_power_w = 0.0
    o.klima_aktiv = False
    o.klima_power_w = 0.0
    return o


# (name, hour, overrides-dict) — deckt AUS, Drain(P0), Burst(P1/1b), P2, Abend(P4) ab
SZENARIEN = [
    ('aus_nachts',            2.0,  {'batt_soc_pct': 30, 'pv_total_w': 0}),
    ('drain_morgens_gut',     6.5,  {'batt_soc_pct': 25, 'sunshine_hours': 9, 'pv_total_w': 200}),
    ('drain_blockiert_regen', 6.5,  {'batt_soc_pct': 25, 'sunshine_hours': 3.5, 'pv_total_w': 100}),
    ('drain_soc_zu_niedrig',  6.5,  {'batt_soc_pct': 15, 'sunshine_hours': 9}),
    ('phase1_blockiert_soc',  10.5, {'batt_soc_pct': 15, 'batt_power_w': 3500, 'forecast_rest_kwh': 38}),
    ('phase1_burst',          11.75,{'batt_soc_pct': 71, 'soc_max': 75, 'batt_power_w': 3800, 'forecast_rest_kwh': 38}),
    ('phase1b_probe',         12.0, {'batt_soc_pct': 73, 'soc_max': 75, 'batt_power_w': 0, 'pv_total_w': 4000}),
    ('phase2_blockiert',      14.0, {'batt_soc_pct': 85, 'soc_max': 100, 'batt_power_w': 5100}),
    ('phase2_burst',          14.0, {'batt_soc_pct': 96, 'soc_max': 100, 'batt_power_w': 5100, 'pv_total_w': 6000}),
    ('phase4_abend',          15.5, {'batt_soc_pct': 96, 'soc_max': 100, 'pv_total_w': 1800, 'batt_power_w': 300}),
    ('aus_hoher_netzbezug',   13.0, {'batt_soc_pct': 60, 'grid_power_w': 3000, 'house_load_w': 3500}),
    ('aus_entladung',         16.5, {'batt_soc_pct': 80, 'batt_power_w': -1500}),
    ('ww_zu_heiss',           12.0, {'batt_soc_pct': 96, 'soc_max': 100, 'ww_temp_c': 79, 'batt_power_w': 4000}),
    ('ev_laedt_parallel',     12.0, {'batt_soc_pct': 73, 'soc_max': 75, 'ev_charging': True, 'ev_power_w': 7000, 'batt_power_w': 3800}),
    # Regressions-Anker: WW-Temp-AUS nutzt in BEIDEN Pfaden den dynamischen
    # WP-Koordinations-Cap. Drain-Fenster (8 h) → Cap 55 °C, ww 60 °C liegt
    # zwischen Drain-Cap und Roh-Cap (78 °C). Score UND Aktion muessen AUS sein
    # (frueher lieferte erzeuge_aktionen kein hp_aus → stille Drift).
    ('ww_drain_cap_konsistent', 8.0, {'heizpatrone_aktiv': True, 'batt_soc_pct': 60, 'ww_temp_c': 60}),
    # Ueberschuss-Override: HP EIN + EV-Konkurrenz + niedriger Forecast-Rest, aber
    # Batterie nahe voll (SOC 90 / MAX 100) und kein Netzbezug → Ueberschuss
    # traegt die HP → KEIN konkurrenz-AUS (Energie sonst abgeregelt).
    ('konkurrenz_ev_ueberschuss_haelt', 12.0, {'heizpatrone_aktiv': True, 'batt_soc_pct': 90, 'soc_max': 100, 'ev_charging': True, 'ev_power_w': 7000, 'batt_power_w': 500, 'grid_power_w': 0, 'pv_total_w': 9000, 'forecast_rest_kwh': 20}),
    # Gegenprobe: gleiche Konkurrenz, aber SOC 70 < ueberschuss_soc_hoch (85) →
    # kein Ueberschuss-Override → konkurrenz-AUS bleibt (Batterieladung Vorrang).
    ('konkurrenz_ev_ohne_ueberschuss_aus', 12.0, {'heizpatrone_aktiv': True, 'batt_soc_pct': 70, 'soc_max': 75, 'ev_charging': True, 'ev_power_w': 7000, 'batt_power_w': 500, 'grid_power_w': 0, 'forecast_rest_kwh': 20}),
]


def _run_one(name, hour, overrides, matrix_aktiv):
    """Frische Regel, fixe Zeit, ObsState bauen, bewerte()+erzeuge_aktionen()."""
    _FixedDateTime._fixed = _dt.datetime(2026, 6, 29, int(hour), int(round((hour % 1) * 60)))
    orig_dt, orig_time = geraete.datetime, geraete.time
    orig_cancel = geraete.RegelHeizpatrone._cancel_conflicting_overrides
    orig_logge = geraete.logge_extern
    geraete.datetime = _FixedDateTime
    geraete.time = _FakeTime()
    # DB-abhaengige Override-Annullation neutralisieren (host-/laufzeitunabh.)
    geraete.RegelHeizpatrone._cancel_conflicting_overrides = (
        lambda self, desired_state, geraet='hp': None)
    # Schaltlog-Datei-Seiteneffekt der Extern-Erkennung neutralisieren.
    geraete.logge_extern = lambda *a, **k: None
    try:
        matrix = copy.deepcopy(lade_matrix())
        matrix['regelkreise']['heizpatrone']['aktiv'] = matrix_aktiv
        obs = _base_obs()
        for k, v in overrides.items():
            setattr(obs, k, v)
        regel = geraete.RegelHeizpatrone()
        score = regel.bewerte(obs, matrix)
        aktionen = regel.erzeuge_aktionen(obs, matrix)
        akt = [{'kommando': a.get('kommando'), 'aktor': a.get('aktor'), 'wert': a.get('wert')}
               for a in (aktionen or [])]
        return {'score': int(score), 'aktionen': akt}
    finally:
        geraete.datetime = orig_dt
        geraete.time = orig_time
        geraete.RegelHeizpatrone._cancel_conflicting_overrides = orig_cancel
        geraete.logge_extern = orig_logge


# ── Multi-Tick State-Sequenz-Szenarien ───────────────────────
# Die Einzel-Tick-Szenarien oben nutzen je eine FRISCHE Regel und treffen damit
# stets den Erst-Zyklus-Schutz (min_pause): Score bleibt 0 und die zustands-
# behafteten Pfade (Burst-Timer-Ablauf/Auto-Verlaengerung, Probe-Auswertung,
# Kurz-Burst-Sperre, Drain-Verzoegerungstimer) werden nie durchlaufen. Die
# folgenden Sequenzen fahren EINE Regelinstanz ueber mehrere Ticks (fort-
# schreitende Uhr) und frieren dieses Verhalten als Golden ein — Sicherheitsnetz
# fuer den bewerte()/erzeuge_aktionen()-Dedup-Refactor.


class _SeqClock:
    """Fortschreitende Uhr fuer Multi-Tick-Sequenzen (deterministisch)."""

    def __init__(self):
        self.epoch = FIXED_EPOCH
        self.dt = _dt.datetime(2026, 6, 29, 12, 0)

    def set_hour(self, hour):
        self.dt = _dt.datetime(2026, 6, 29, int(hour), int(round((hour % 1) * 60)))

    def advance(self, seconds):
        self.epoch += seconds
        self.dt = self.dt + _dt.timedelta(seconds=seconds)


_SEQ_CLOCK = _SeqClock()


class _SeqDateTime(_dt.datetime):
    """datetime-Subklasse, die now()/utcnow() aus _SEQ_CLOCK liest."""

    @classmethod
    def now(cls, tz=None):  # noqa: A003
        return _SEQ_CLOCK.dt

    @classmethod
    def utcnow(cls):
        return _SEQ_CLOCK.dt


class _SeqTime:
    """time-Modul-Proxy, dessen time() aus _SEQ_CLOCK liest."""

    def time(self):
        return _SEQ_CLOCK.epoch

    def __getattr__(self, name):
        return getattr(_real_time, name)


def _seq_actions(aktionen) -> list:
    return [{'kommando': a.get('kommando'), 'aktor': a.get('aktor'), 'wert': a.get('wert')}
            for a in (aktionen or [])]


# (name, hour_start, [ (advance_s, overrides), … ])
# Tick 0 hat advance_s=0. overrides mutieren den fortlaufenden ObsState.
# Zwischen den Ticks wird heizpatrone_aktiv aus der letzten Aktion zurueck-
# gespiegelt (hp_ein→True, hp_aus→False) — Nachbildung der Aktor/Observer-
# Rueckkopplung; ein override kann heizpatrone_aktiv explizit ueberschreiben.
SEQ_SZENARIEN = [
    # Phase-1-Burst-Lebenszyklus: Start → Halten → Timer-Ablauf-AUS → min_pause
    ('phase1_burst_lifecycle', 11.75, [
        (0,    {'batt_soc_pct': 71, 'batt_power_w': 3800, 'forecast_rest_kwh': 38}),
        (120,  {}),
        (1800, {}),
        (60,   {}),
    ]),
    # Phase-1b-Probe erfolgreich: Probe-Puls → PV reagiert → Burst verlaengert
    ('phase1b_probe_success', 12.0, [
        (0,    {}),
        (600,  {'batt_soc_pct': 73, 'soc_max': 75, 'batt_power_w': 0,
                'pv_total_w': 1000, 'grid_power_w': 0,
                'forecast_power_profile': [{'hour': 12, 'total_ac_w': 4000},
                                           {'hour': 13, 'total_ac_w': 4000}]}),
        (120,  {'pv_total_w': 1600}),
        (1800, {}),
    ]),
    # Phase-1b-Probe gescheitert: PV reagiert nicht → AUS + Cooldown
    ('phase1b_probe_fail', 12.0, [
        (0,   {}),
        (600, {'batt_soc_pct': 73, 'soc_max': 75, 'batt_power_w': 0,
               'pv_total_w': 1000, 'grid_power_w': 0,
               'forecast_power_profile': [{'hour': 12, 'total_ac_w': 4000},
                                          {'hour': 13, 'total_ac_w': 4000}]}),
        (120, {'pv_total_w': 1050}),
    ]),
    # Kurz-Burst-Sperre: 2× kurzer Burst (<7 Min) → EIN-Sperre blockt Folge-Burst
    ('kurz_burst_sperre', 11.75, [
        (0,   {'batt_soc_pct': 71, 'batt_power_w': 3800, 'forecast_rest_kwh': 38}),
        (60,  {'batt_power_w': -1500}),
        (360, {'batt_power_w': 3800}),
        (60,  {'batt_power_w': -1500}),
        (360, {'batt_power_w': 3800}),
    ]),
    # Phase-0-Drain: Start → kontinuierliche Auto-Verlaengerung → AUS nach Fenster
    # (ww_temp bewusst < Drain-Cap 55 °C, damit die Sequenz die Drain-/Timer-Logik
    #  isoliert testet und nicht an der WW-Temp-Schwelle haengt)
    ('drain_lifecycle', 8.0, [
        (0,    {'ww_temp_c': 45, 'forecast_rest_kwh': 50, 'batt_power_w': 500,
                'forecast_power_profile': [{'hour': 9, 'total_ac_w': 5000},
                                           {'hour': 10, 'total_ac_w': 5000}]}),
        (300,  {}),
        (2700, {}),
        (4800, {}),
    ]),
    # Drain-Verzoegerungstimer: Soft-Verbraucher (WP) → verzoegertes AUS (Timer
    # quer zwischen bewerte()/erzeuge_aktionen())
    ('drain_delay_soft', 8.0, [
        (0,   {'ww_temp_c': 45, 'forecast_rest_kwh': 50, 'batt_power_w': 500,
               'wp_power_w': 0,
               'forecast_power_profile': [{'hour': 9, 'total_ac_w': 5000},
                                          {'hour': 10, 'total_ac_w': 5000}]}),
        (300, {'wp_power_w': 800}),
        (360, {'wp_power_w': 800}),
    ]),
    # Extern-Autoritaet vs. weiche WP-Koordinations-Caps: Bediener schaltet HP
    # am Abend EIN (als Extern-EIN erkannt). WW 66 C liegt ueber dem Abend-Cap
    # (65 C, WP-Koordination), aber unter der harten 78-C-Schwelle → HP bleibt
    # EIN (weicher Cap ueberstimmt den Bediener NICHT). Erst WW 79 C (hart)
    # schaltet doch ab — Sicherheitsschwelle bleibt zwingend.
    ('extern_abend_ww_cap_haelt', 15.5, [
        (0,  {'heizpatrone_aktiv': False, 'batt_soc_pct': 90, 'soc_max': 100,
              'ww_temp_c': 66, 'pv_total_w': 1800, 'batt_power_w': 200}),
        (60, {'heizpatrone_aktiv': True}),
        (60, {}),
        (60, {'ww_temp_c': 79}),
    ]),
]


def _run_sequence(name, hour_start, ticks):
    """Fahre EINE Regelinstanz ueber mehrere Ticks; Ergebnis je Tick."""
    _SEQ_CLOCK.epoch = FIXED_EPOCH
    _SEQ_CLOCK.set_hour(hour_start)
    orig_dt, orig_time = geraete.datetime, geraete.time
    orig_cancel = geraete.RegelHeizpatrone._cancel_conflicting_overrides
    orig_logge = geraete.logge_extern
    geraete.datetime = _SeqDateTime
    geraete.time = _SeqTime()
    # DB-abhaengige Override-Annullation neutralisieren (host-/laufzeitunabh.)
    geraete.RegelHeizpatrone._cancel_conflicting_overrides = (
        lambda self, desired_state, geraet='hp': None)
    # Schaltlog-Datei-Seiteneffekt der Extern-Erkennung neutralisieren.
    geraete.logge_extern = lambda *a, **k: None
    ergebnisse = []
    try:
        matrix = copy.deepcopy(lade_matrix())
        matrix['regelkreise']['heizpatrone']['aktiv'] = True
        regel = geraete.RegelHeizpatrone()
        obs = _base_obs()
        letzte_aktion = None
        for advance_s, overrides in ticks:
            if advance_s:
                _SEQ_CLOCK.advance(advance_s)
            if letzte_aktion == 'hp_ein':
                obs.heizpatrone_aktiv = True
            elif letzte_aktion == 'hp_aus':
                obs.heizpatrone_aktiv = False
            for k, v in overrides.items():
                setattr(obs, k, v)
            score = regel.bewerte(obs, matrix)
            aktionen = regel.erzeuge_aktionen(obs, matrix)
            ergebnisse.append({'score': int(score), 'aktionen': _seq_actions(aktionen)})
            letzte_aktion = None
            for a in (aktionen or []):
                if a.get('kommando') in ('hp_ein', 'hp_aus'):
                    letzte_aktion = a.get('kommando')
        return ergebnisse
    finally:
        geraete.datetime = orig_dt
        geraete.time = orig_time
        geraete.RegelHeizpatrone._cancel_conflicting_overrides = orig_cancel
        geraete.logge_extern = orig_logge


def erzeuge_snapshot() -> dict:
    snap = {}
    for aktiv in (True, False):
        for name, hour, ov in SZENARIEN:
            key = f"{name}|aktiv={aktiv}"
            snap[key] = _run_one(name, hour, ov, aktiv)
    for name, hour_start, ticks in SEQ_SZENARIEN:
        for i, res in enumerate(_run_sequence(name, hour_start, ticks)):
            snap[f"seq:{name}|t{i}"] = res
    return snap


def main() -> int:
    update = '--update' in sys.argv
    snap = erzeuge_snapshot()
    # Determinismus-Selbstcheck: zweiter Lauf identisch?
    assert snap == erzeuge_snapshot(), "Snapshot nicht deterministisch!"

    if update or not os.path.exists(GOLDEN):
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, 'w', encoding='utf-8') as f:
            json.dump(snap, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write('\n')
        print(f"Golden {'aktualisiert' if update else 'erstellt'}: {GOLDEN} ({len(snap)} Szenarien)")
        return 0

    golden = json.load(open(GOLDEN, encoding='utf-8'))
    diffs = [k for k in sorted(set(golden) | set(snap)) if golden.get(k) != snap.get(k)]
    if diffs:
        print("CHARACTERIZATION-ABWEICHUNG (Verhalten geaendert!):")
        for k in diffs:
            print(f"  {k}:\n    golden={golden.get(k)}\n    jetzt ={snap.get(k)}")
        return 1
    print(f"OK: HP-Verhalten unveraendert ({len(snap)} Szenarien gegen Golden).")
    return 0


if __name__ == '__main__':
    sys.exit(main())
