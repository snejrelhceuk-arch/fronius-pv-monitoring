#!/usr/bin/env python3
"""
Characterization golden-master fuer die ausgelagerten Geraete-Regeln.

Friert das IST-Verhalten (Score + erzeugte Aktionen) von
  - RegelWattpilotBattSchutz  (geraete_wattpilot_schutz.py)
  - RegelKlimaanlage          (geraete_klimaanlage.py)
  - RegelFussbodenheizungNacht(geraete_fbh_nacht.py)
ueber ein kuratiertes Szenario-Gitter ein. Ergaenzt den bestehenden
HP-Characterization-Test und bildet zusammen mit ihm das Sicherheitsnetz fuer
den geplanten bewerte()/erzeuge_aktionen()-Dedup-Refactor.

Deterministik:
  - frische Regel je Szenario (kein akkumulierter State, kein EXTERN)
  - datetime.now()/utcnow() und time.time() auf feste Werte gepatcht (je Modul)
  - Klima: DB-abhaengiger Steuerbox-Hold wird auf (None, 0) gestubbt, damit der
    Test host-/laufzeitunabhaengig bleibt (keine Produktions-DB noetig)
  - erfasst werden nur verhaltensrelevante Felder (kommando/aktor/wert)

Nutzung:
  python3 tests/test_geraete_characterization.py            # vergleicht gegen Golden
  python3 tests/test_geraete_characterization.py --update   # Golden neu schreiben
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
import automation.engine.regeln.geraete_wattpilot_schutz as wp_mod  # noqa: E402
import automation.engine.regeln.geraete_klimaanlage as klima_mod  # noqa: E402
import automation.engine.regeln.geraete_fbh_nacht as fbh_mod  # noqa: E402
import automation.engine.regeln.waermepumpe as wpump_mod  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden',
                      'geraete_golden.json')
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


def _set_hour(hour: float) -> None:
    _FixedDateTime._fixed = _dt.datetime(2026, 6, 29, int(hour), int(round((hour % 1) * 60)))


def _actions(aktionen) -> list:
    return [{'kommando': a.get('kommando'), 'aktor': a.get('aktor'), 'wert': a.get('wert')}
            for a in (aktionen or [])]


# ═════════════════════════════════════════════════════════════
# RegelWattpilotBattSchutz
# ═════════════════════════════════════════════════════════════
def _wp_obs() -> ObsState:
    o = ObsState()
    o.sunset = 17.0
    o.soc_mode = 'auto'
    o.batt_soc_pct = 50.0
    o.soc_min = 10
    o.batt_power_w = 0.0
    o.ev_charging = False
    o.ev_power_w = 0.0
    o.ev_eco_mode = False
    return o


WP_SZENARIEN = [
    ('kein_ev',          12.0, {}),
    ('ev_soc_niedrig',   12.0, {'ev_charging': True, 'ev_power_w': 7000, 'batt_power_w': -2000, 'batt_soc_pct': 13}),
    ('ev_soc_ok',        12.0, {'ev_charging': True, 'ev_power_w': 7000, 'batt_power_w': -2000, 'batt_soc_pct': 60}),
    ('ev_batt_laedt',    12.0, {'ev_charging': True, 'ev_power_w': 7000, 'batt_power_w': 500,  'batt_soc_pct': 13}),
    ('ev_sunset_soc25',  15.5, {'ev_charging': True, 'ev_power_w': 7000, 'batt_power_w': -2000, 'batt_soc_pct': 22}),
]


def _run_wp(name, hour, overrides, aktiv):
    _set_hour(hour)
    orig_dt = wp_mod.datetime
    wp_mod.datetime = _FixedDateTime
    try:
        matrix = copy.deepcopy(lade_matrix())
        matrix['regelkreise']['wattpilot_battschutz']['aktiv'] = aktiv
        obs = _wp_obs()
        for k, v in overrides.items():
            setattr(obs, k, v)
        regel = wp_mod.RegelWattpilotBattSchutz()
        score = regel.bewerte(obs, matrix)
        aktionen = regel.erzeuge_aktionen(obs, matrix)
        return {'score': int(score), 'aktionen': _actions(aktionen)}
    finally:
        wp_mod.datetime = orig_dt


# ═════════════════════════════════════════════════════════════
# RegelKlimaanlage
# ═════════════════════════════════════════════════════════════
def _klima_obs() -> ObsState:
    o = ObsState()
    o.sunrise = 7.5
    o.sunset = 20.0
    o.batt_soc_pct = 95.0
    o.klima_aktiv = False
    o.klima_power_w = 0.0
    o.klima_temp_c = 25.0
    o.forecast_kwh = 120.0
    o.forecast_rest_kwh = 100.0
    return o


KLIMA_SZENARIEN = [
    ('klima_ein_noetig',    12.0, {'klima_aktiv': False, 'klima_temp_c': 25.0}),
    ('klima_aus_noetig',    12.0, {'klima_aktiv': True,  'klima_power_w': 1000.0, 'klima_temp_c': 10.0}),
    ('klima_idle_off',      12.0, {'klima_aktiv': False, 'klima_temp_c': 10.0}),
    ('klima_sunset_stop',   21.0, {'klima_aktiv': True,  'klima_power_w': 1000.0, 'batt_soc_pct': 85.0}),
    ('klima_vor_fenster',    6.0, {'klima_aktiv': False, 'klima_temp_c': 25.0}),
]


def _run_klima(name, hour, overrides, aktiv):
    _set_hour(hour)
    orig_dt, orig_time = klima_mod.datetime, klima_mod.time
    orig_hold = klima_mod.RegelKlimaanlage._aktiver_steuerbox_klima_hold
    klima_mod.datetime = _FixedDateTime
    klima_mod.time = _FakeTime()
    # DB-abhaengigen Steuerbox-Hold neutralisieren (host-/laufzeitunabhaengig)
    klima_mod.RegelKlimaanlage._aktiver_steuerbox_klima_hold = staticmethod(lambda: (None, 0))
    try:
        matrix = copy.deepcopy(lade_matrix())
        matrix['regelkreise']['klimaanlage']['aktiv'] = aktiv
        obs = _klima_obs()
        for k, v in overrides.items():
            setattr(obs, k, v)
        regel = klima_mod.RegelKlimaanlage()
        score = regel.bewerte(obs, matrix)
        aktionen = regel.erzeuge_aktionen(obs, matrix)
        return {'score': int(score), 'aktionen': _actions(aktionen)}
    finally:
        klima_mod.datetime = orig_dt
        klima_mod.time = orig_time
        klima_mod.RegelKlimaanlage._aktiver_steuerbox_klima_hold = orig_hold


# ═════════════════════════════════════════════════════════════
# RegelFussbodenheizungNacht
# ═════════════════════════════════════════════════════════════
def _fbh_obs() -> ObsState:
    return ObsState()


FBH_SZENARIEN = [
    ('fbh_ein_fenster',   3.5,  False),
    ('fbh_aus_nachlauf',  5.5,  False),
    ('fbh_ausserhalb',   12.0,  False),
    ('fbh_ein_done',      3.5,  True),   # EIN-Flanke heute bereits erledigt
]


def _run_fbh(name, hour, ein_done, aktiv):
    _set_hour(hour)
    orig_dt_fbh, orig_dt_wp = fbh_mod.datetime, wpump_mod.datetime
    orig_done = wpump_mod._absenkung_done
    fbh_mod.datetime = _FixedDateTime
    wpump_mod.datetime = _FixedDateTime
    wpump_mod._absenkung_done = {}
    if ein_done:
        wpump_mod._absenkung_done['fbh_ein'] = _FixedDateTime.now().date()
    try:
        matrix = copy.deepcopy(lade_matrix())
        matrix['regelkreise']['fussbodenheizung']['aktiv'] = aktiv
        obs = _fbh_obs()
        regel = fbh_mod.RegelFussbodenheizungNacht()
        score = regel.bewerte(obs, matrix)
        aktionen = regel.erzeuge_aktionen(obs, matrix)
        return {'score': int(score), 'aktionen': _actions(aktionen)}
    finally:
        fbh_mod.datetime = orig_dt_fbh
        wpump_mod.datetime = orig_dt_wp
        wpump_mod._absenkung_done = orig_done


def erzeuge_snapshot() -> dict:
    snap = {}
    for aktiv in (True, False):
        for name, hour, ov in WP_SZENARIEN:
            snap[f'wp:{name}|aktiv={aktiv}'] = _run_wp(name, hour, ov, aktiv)
        for name, hour, ov in KLIMA_SZENARIEN:
            snap[f'klima:{name}|aktiv={aktiv}'] = _run_klima(name, hour, ov, aktiv)
        for name, hour, ein_done in FBH_SZENARIEN:
            snap[f'fbh:{name}|aktiv={aktiv}'] = _run_fbh(name, hour, ein_done, aktiv)
    return snap


def main() -> int:
    update = '--update' in sys.argv
    snap = erzeuge_snapshot()
    assert snap == erzeuge_snapshot(), 'Snapshot nicht deterministisch!'

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
        print('CHARACTERIZATION-ABWEICHUNG (Verhalten geaendert!):')
        for k in diffs:
            print(f'  {k}:\n    golden={golden.get(k)}\n    jetzt ={snap.get(k)}')
        return 1
    print(f'OK: Geraete-Verhalten unveraendert ({len(snap)} Szenarien gegen Golden).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
