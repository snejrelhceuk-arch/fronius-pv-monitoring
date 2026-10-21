#!/usr/bin/env python3
"""Test fuer die HP-Steuerung analog Klima-Steckdose.

Die Heizpatrone in der Steuerbox arbeitet wie die Klima-Steckdose:
  - `hp_toggle` schaltet An/Aus mit Respekt-Timer (im Rahmen der Automatik).
  - `hp-regel-aktiv` deaktiviert die HP-Automatik-Regel (`regelkreise.heizpatrone.aktiv`),
    sodass `hp_toggle` auch bei deaktivierter Automatik frei schaltet.
  - Der Tier-1-SLS-Schutz (Phasenstrom > 35A -> HP AUS) bleibt immer aktiv.
Der fruehere `hp_dauerbetrieb`-Intent ist entfernt.

Nutzung: python3 tests/test_hp_regel_aktiv.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def test_dauerbetrieb_nicht_mehr_erlaubt():
    import config as _cfg
    from steuerbox.validators import validate_action
    from werkzeug.exceptions import HTTPException
    assert 'hp_dauerbetrieb' not in _cfg.STEUERBOX_ALLOWED_ACTIONS
    assert not hasattr(_cfg, 'STEUERBOX_HP_DAUERBETRIEB_DEFAULT_S')
    try:
        validate_action('hp_dauerbetrieb', {'state': 'on'},
                        _cfg.STEUERBOX_DEFAULT_RESPEKT_S)
        raise AssertionError('hp_dauerbetrieb haette abgelehnt werden muessen')
    except HTTPException as e:
        assert e.code == 403


def test_hp_toggle_validiert_states_und_hard_guards():
    import config as _cfg
    from steuerbox.validators import validate_action
    from werkzeug.exceptions import HTTPException
    for s in ('on', 'off', 'neutral'):
        norm = validate_action('hp_toggle', {'state': s}, _cfg.STEUERBOX_DEFAULT_RESPEKT_S)
        assert norm['state'] == s
    # Hard Guard: EIN bei kritischem SOC blockiert.
    try:
        validate_action('hp_toggle', {'state': 'on', 'soc_pct': 10},
                        _cfg.STEUERBOX_DEFAULT_RESPEKT_S)
        raise AssertionError('EIN bei SOC 10% haette abgelehnt werden muessen')
    except HTTPException as e:
        assert e.code == 422
    # Hard Guard: EIN bei Uebertemperatur blockiert.
    try:
        validate_action('hp_toggle', {'state': 'on', 'uebertemp_c': 80},
                        _cfg.STEUERBOX_DEFAULT_RESPEKT_S)
        raise AssertionError('EIN bei 80C haette abgelehnt werden muessen')
    except HTTPException as e:
        assert e.code == 422


def test_hp_toggle_mapping_analog_klima():
    from automation.engine.operator_overrides import OperatorOverrideProcessor
    proc = OperatorOverrideProcessor(db_path=':memory:')
    on = proc._map_override_to_actions('hp_toggle', {'state': 'on'}, {})
    assert on == [{'tier': 2, 'aktor': 'fritzdect', 'kommando': 'hp_ein',
                   'grund': 'Steuerbox Override: HP EIN', 'dedup_bypass': True}], on
    off = proc._map_override_to_actions('hp_toggle', {'state': 'off'}, {})
    assert off == [{'tier': 2, 'aktor': 'fritzdect', 'kommando': 'hp_aus',
                    'grund': 'Steuerbox Override: HP AUS', 'dedup_bypass': True}], off
    assert proc._map_override_to_actions('hp_toggle', {'state': 'neutral'}, {}) == []


def test_hp_dauerbetrieb_kein_policy_hold():
    from automation.engine.operator_overrides import OperatorOverrideProcessor
    assert OperatorOverrideProcessor._is_policy_hold_action('hp_dauerbetrieb') is False
    assert OperatorOverrideProcessor._is_policy_hold_action('afternoon_charge_request') is True


def test_hp_regel_aktiv_toggle_in_matrix():
    import steuerbox.steuerbox_api as api
    tmpdir = tempfile.mkdtemp()
    tmp_matrix = os.path.join(tmpdir, 'soc_param_matrix.json')
    shutil.copy(os.path.join(_ROOT, 'config', 'soc_param_matrix.json'), tmp_matrix)
    orig = api.DEFAULT_MATRIX_PATH
    try:
        api.DEFAULT_MATRIX_PATH = tmp_matrix
        res = api._set_regelkreis_aktiv('heizpatrone', False)
        assert res['ok'] and res['aktiv'] is False, res
        assert json.load(open(tmp_matrix))['regelkreise']['heizpatrone']['aktiv'] is False
        res = api._set_regelkreis_aktiv('heizpatrone', True)
        assert res['ok'] and res['aktiv'] is True, res
        assert json.load(open(tmp_matrix))['regelkreise']['heizpatrone']['aktiv'] is True
    finally:
        api.DEFAULT_MATRIX_PATH = orig
        shutil.rmtree(tmpdir, ignore_errors=True)


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
    print('\nAlle HP-Regel-Aktiv-Tests gruen.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
