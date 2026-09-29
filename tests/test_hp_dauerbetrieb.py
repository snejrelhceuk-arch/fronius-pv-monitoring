#!/usr/bin/env python3
"""Test fuer HP-Dauerbetrieb (Steuerbox-Ersatzheizung bei WP-Defekt).

Prueft die Regel-Logik in geraete_heizpatrone.py bei aktivem hp_dauerbetrieb-
Intent (gestubbt): erzwingt HP EIN auch nachts / bei niedrigem SOC (aus dem
Netz), haelt sie, stoppt nur bei WW >= 78 C (mit Hysterese) und weicht einem
laufenden WP (kein Zwang, wenn die Waermepumpe selbst heizt).

Nutzung: python3 tests/test_hp_dauerbetrieb.py
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import time as _real_time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from automation.engine.obs_state import ObsState  # noqa: E402
from automation.engine.param_matrix import lade_matrix  # noqa: E402
import automation.engine.regeln.geraete_heizpatrone as geraete  # noqa: E402

FIXED_EPOCH = 1782000000.0


class _FixedDateTime(_dt.datetime):
    _fixed = _dt.datetime(2026, 6, 29, 22, 0)  # Nacht (nach Sunset 17:00)

    @classmethod
    def now(cls, tz=None):  # noqa: A003
        return cls._fixed

    @classmethod
    def utcnow(cls):
        return cls._fixed


class _FakeTime:
    def time(self):
        return FIXED_EPOCH

    def __getattr__(self, name):
        return getattr(_real_time, name)


def _obs(**ov) -> ObsState:
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
    o.forecast_rest_kwh = 0.0
    o.ww_temp_c = 55.0
    o.wp_power_w = 0.0
    o.ev_charging = False
    o.ev_power_w = 0.0
    o.heizpatrone_aktiv = False
    for k, v in ov.items():
        setattr(o, k, v)
    return o


class _Patch:
    """Patcht Zeit + DB-abhaengige Helfer + Intent-Reader (host-unabhaengig)."""

    def __enter__(self):
        self._dt = geraete.datetime
        self._tm = geraete.time
        self._cancel = geraete.RegelHeizpatrone._cancel_conflicting_overrides
        self._logge = geraete.logge_extern
        self._dauer = geraete.read_active_hp_dauerbetrieb_intent
        self._aft = geraete.read_active_afternoon_charge_intent
        geraete.datetime = _FixedDateTime
        geraete.time = _FakeTime()
        geraete.RegelHeizpatrone._cancel_conflicting_overrides = (
            lambda self, desired_state, geraet='hp': None)
        geraete.logge_extern = lambda *a, **k: None
        geraete.read_active_afternoon_charge_intent = lambda *a, **k: None
        geraete.read_active_hp_dauerbetrieb_intent = lambda *a, **k: None
        return self

    def __exit__(self, *a):
        geraete.datetime = self._dt
        geraete.time = self._tm
        geraete.RegelHeizpatrone._cancel_conflicting_overrides = self._cancel
        geraete.logge_extern = self._logge
        geraete.read_active_hp_dauerbetrieb_intent = self._dauer
        geraete.read_active_afternoon_charge_intent = self._aft

    @staticmethod
    def set_dauer(active: bool):
        if active:
            geraete.read_active_hp_dauerbetrieb_intent = (
                lambda *a, **k: {'override_id': 1, 'status': 'active',
                                 'respekt_remaining_s': 3600})
        else:
            geraete.read_active_hp_dauerbetrieb_intent = lambda *a, **k: None


def _run(regel, obs, matrix):
    score = regel.bewerte(obs, matrix)
    aktionen = regel.erzeuge_aktionen(obs, matrix)
    return int(score), [a.get('kommando') for a in (aktionen or [])]


def test_dauer_erzwingt_ein_nachts_bei_niedrigem_soc():
    with _Patch() as p:
        p.set_dauer(True)
        matrix = lade_matrix()
        regel = geraete.RegelHeizpatrone()
        obs = _obs(heizpatrone_aktiv=False, batt_soc_pct=8, ww_temp_c=50, pv_total_w=0)
        score, cmds = _run(regel, obs, matrix)
        assert cmds == ['hp_ein'], f'erwartet hp_ein (Zwang nachts/8% SOC), bekam {cmds}'
        assert score > 0


def test_dauer_haelt_wenn_ein():
    with _Patch() as p:
        p.set_dauer(True)
        matrix = lade_matrix()
        regel = geraete.RegelHeizpatrone()
        obs = _obs(heizpatrone_aktiv=True, batt_soc_pct=8, ww_temp_c=50)
        _, cmds = _run(regel, obs, matrix)
        assert cmds == [], f'erwartet halten (keine Aktion), bekam {cmds}'


def test_dauer_aus_bei_uebertemp():
    with _Patch() as p:
        p.set_dauer(True)
        matrix = lade_matrix()
        regel = geraete.RegelHeizpatrone()
        obs = _obs(heizpatrone_aktiv=True, ww_temp_c=79)
        _, cmds = _run(regel, obs, matrix)
        assert cmds == ['hp_aus'], f'erwartet hp_aus (WW 79C hart), bekam {cmds}'


def test_dauer_weicht_laufendem_wp():
    with _Patch() as p:
        p.set_dauer(True)
        matrix = lade_matrix()
        regel = geraete.RegelHeizpatrone()
        # WP laeuft (800W >= drain_max_wp_w) -> kein Zwang; normale Nacht-Logik
        # laesst HP aus.
        obs = _obs(heizpatrone_aktiv=False, wp_power_w=800, batt_soc_pct=8, ww_temp_c=50)
        _, cmds = _run(regel, obs, matrix)
        assert cmds == [], f'erwartet kein Zwang (WP laeuft), bekam {cmds}'


def test_inaktiv_kein_zwang():
    with _Patch() as p:
        p.set_dauer(False)   # kein Dauerbetrieb-Intent
        matrix = lade_matrix()
        regel = geraete.RegelHeizpatrone()
        obs = _obs(heizpatrone_aktiv=False, batt_soc_pct=8, ww_temp_c=50)
        _, cmds = _run(regel, obs, matrix)
        assert cmds == [], f'ohne Intent kein Zwang, bekam {cmds}'


def test_hysterese():
    with _Patch() as p:
        p.set_dauer(True)
        matrix = lade_matrix()
        regel = geraete.RegelHeizpatrone()
        # 1) WW 79 -> AUS + Sperre
        _, c1 = _run(regel, _obs(heizpatrone_aktiv=True, ww_temp_c=79), matrix)
        assert c1 == ['hp_aus'], f't1 erwartet hp_aus, bekam {c1}'
        # 2) WW 75 (>= 78-5) -> weiter gesperrt -> keine Aktion
        _, c2 = _run(regel, _obs(heizpatrone_aktiv=False, ww_temp_c=75), matrix)
        assert c2 == [], f't2 erwartet halten-aus, bekam {c2}'
        # 3) WW 72 (< 73) -> Sperre faellt -> wieder EIN
        _, c3 = _run(regel, _obs(heizpatrone_aktiv=False, ww_temp_c=72), matrix)
        assert c3 == ['hp_ein'], f't3 erwartet hp_ein (Hysterese frei), bekam {c3}'


# ── Integrationstests: Intent-Kette (Validator / Respekt / Policy-Hold / Reader) ──

def test_validator_akzeptiert_states_und_kappt_respekt():
    import config as _cfg
    from steuerbox.validators import validate_action
    from werkzeug.exceptions import HTTPException
    for s in ('on', 'off', 'neutral'):
        norm = validate_action('hp_dauerbetrieb', {'state': s},
                               _cfg.STEUERBOX_HP_DAUERBETRIEB_DEFAULT_S)
        assert norm['state'] == s
    try:
        validate_action('hp_dauerbetrieb', {'state': 'on'},
                        _cfg.STEUERBOX_HP_DAUERBETRIEB_MAX_S + 1)
        raise AssertionError('respekt > 24h haette abgelehnt werden muessen')
    except HTTPException as e:
        assert e.code == 422
    try:
        validate_action('hp_dauerbetrieb',
                        {'state': 'on', 'uebertemp_c': 80},
                        _cfg.STEUERBOX_HP_DAUERBETRIEB_DEFAULT_S)
        raise AssertionError('EIN bei 80C haette abgelehnt werden muessen')
    except HTTPException as e:
        assert e.code == 422


def test_resolve_respekt_default_und_cap():
    import config as _cfg
    from steuerbox.intent_handler import _resolve_effective_respekt_s
    assert _resolve_effective_respekt_s('hp_dauerbetrieb', {}, None, None) == \
        _cfg.STEUERBOX_HP_DAUERBETRIEB_DEFAULT_S
    assert _resolve_effective_respekt_s(
        'hp_dauerbetrieb', {}, _cfg.STEUERBOX_HP_DAUERBETRIEB_MAX_S + 10000, None) == \
        _cfg.STEUERBOX_HP_DAUERBETRIEB_MAX_S


def test_neutral_und_off_geben_frei():
    from steuerbox.intent_handler import _is_neutral_action
    assert _is_neutral_action('hp_dauerbetrieb', {'state': 'off'}) is True
    assert _is_neutral_action('hp_dauerbetrieb', {'state': 'neutral'}) is True
    assert _is_neutral_action('hp_dauerbetrieb', {'state': 'on'}) is False


def test_policy_hold_flag():
    from automation.engine.operator_overrides import OperatorOverrideProcessor
    assert OperatorOverrideProcessor._is_policy_hold_action('hp_dauerbetrieb') is True


def test_reader_liest_aktiven_override():
    import sqlite3
    import tempfile
    from datetime import datetime, timezone
    from automation.engine.operator_intents import _read_hp_dauerbetrieb_intent
    db = os.path.join(tempfile.mkdtemp(), 'ops.db')
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE operator_overrides ('
        'id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, params_json TEXT, '
        'created_at TEXT, respekt_s INTEGER, source TEXT, status TEXT)')
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    conn.execute(
        "INSERT INTO operator_overrides "
        '(action, params_json, created_at, respekt_s, source, status) '
        "VALUES ('hp_dauerbetrieb', '{\"state\": \"on\"}', ?, 3600, 'steuerbox', 'active')",
        (now_iso,))
    conn.commit()
    conn.close()
    got = _read_hp_dauerbetrieb_intent(db)
    assert got is not None and got['respekt_remaining_s'] > 3000, f'reader on: {got}'
    conn = sqlite3.connect(db)
    conn.execute("UPDATE operator_overrides SET params_json='{\"state\": \"off\"}'")
    conn.commit()
    conn.close()
    assert _read_hp_dauerbetrieb_intent(db) is None, 'off muss None liefern'


def main() -> int:
    fehler = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'OK  {name}')
            except AssertionError as e:
                fehler += 1
                print(f'FAIL {name}: {e}')
    if fehler:
        print(f'\n{fehler} Test(s) fehlgeschlagen.')
        return 1
    print('\nAlle HP-Dauerbetrieb-Tests gruen.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
