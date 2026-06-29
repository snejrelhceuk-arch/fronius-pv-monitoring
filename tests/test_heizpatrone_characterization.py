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
import automation.engine.regeln.geraete as geraete  # noqa: E402

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
]


def _run_one(name, hour, overrides, matrix_aktiv):
    """Frische Regel, fixe Zeit, ObsState bauen, bewerte()+erzeuge_aktionen()."""
    _FixedDateTime._fixed = _dt.datetime(2026, 6, 29, int(hour), int(round((hour % 1) * 60)))
    orig_dt, orig_time = geraete.datetime, geraete.time
    geraete.datetime = _FixedDateTime
    geraete.time = _FakeTime()
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


def erzeuge_snapshot() -> dict:
    snap = {}
    for aktiv in (True, False):
        for name, hour, ov in SZENARIEN:
            key = f"{name}|aktiv={aktiv}"
            snap[key] = _run_one(name, hour, ov, aktiv)
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
