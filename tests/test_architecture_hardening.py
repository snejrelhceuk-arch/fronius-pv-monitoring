#!/usr/bin/env python3
"""Regressionstests fuer Architektur-Haertung."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def test_host_role_unknown_blocks_primary_require():
    import host_role

    tmp = tempfile.mkdtemp()
    role_file = os.path.join(tmp, '.role')
    with open(role_file, 'w', encoding='utf-8') as f:
        f.write('werkbank\n')

    old_file = host_role._ROLE_FILE
    old_role = host_role.ROLE
    try:
        host_role._ROLE_FILE = role_file
        assert host_role.get_role() == host_role.UNKNOWN_ROLE
        host_role.ROLE = host_role.UNKNOWN_ROLE
        try:
            host_role.require_primary()
            raise AssertionError('unknown role must not satisfy require_primary')
        except SystemExit as ex:
            assert ex.code == 1
    finally:
        host_role._ROLE_FILE = old_file
        host_role.ROLE = old_role


def test_registry_loads_hard_safety_even_when_disabled():
    from automation.engine import registry
    from automation.engine.aktoren.aktor_batterie import AktorBase
    from automation.engine.regeln.basis import Regel

    class DummyRule(Regel):
        pass

    class DummyActor(AktorBase):
        def ausfuehren(self, aktion):
            return {'ok': True}

        def verifiziere(self, aktion):
            return {'ok': True}

    old_resolve = registry._resolve
    try:
        registry._resolve = lambda dotted: DummyActor if dotted.endswith('Actor') else DummyRule
        rules = registry._instanziiere_regeln([
            ('sls_schutz', 'x.Rule', False),
            ('komfort_reset', 'x.Rule', False),
        ])
        actors = registry._instanziiere_aktoren([
            ('wattpilot', 'x.Actor', False),
            ('waermepumpe', 'x.Actor', False),
        ], dry_run=True)
    finally:
        registry._resolve = old_resolve

    assert len(rules) == 1
    assert 'wattpilot' in actors
    assert 'waermepumpe' not in actors


def test_operator_override_blocks_hp_on_current_low_soc():
    from automation.engine.operator_overrides import OperatorOverrideProcessor

    class FakeActuator:
        def __init__(self):
            self.called = False

        def ausfuehren_plan(self, plan):
            self.called = True
            return [{'ok': True}]

    db = os.path.join(tempfile.mkdtemp(), 'ops.db')
    conn = sqlite3.connect(db)
    conn.execute(
        'CREATE TABLE operator_overrides ('
        'id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, params_json TEXT, '
        'created_at TEXT, respekt_s INTEGER, source TEXT, status TEXT)')
    conn.execute(
        'CREATE TABLE steuerbox_audit ('
        'id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, client_ip TEXT, action TEXT, '
        'params_json TEXT, result_json TEXT, override_id INTEGER, note TEXT)')
    conn.execute('CREATE TABLE obs_state (id INTEGER PRIMARY KEY, ts TEXT, state_json TEXT, tier1_flags TEXT)')
    conn.execute('CREATE TABLE engine_flags (key TEXT PRIMARY KEY, value TEXT)')
    conn.execute('INSERT INTO obs_state (id, ts, state_json, tier1_flags) VALUES (1, ?, ?, ?)', (
        datetime.now(timezone.utc).isoformat(),
        json.dumps({'batt_soc_pct': 10, 'ww_temp_c': 45, 'heizpatrone_aktiv': False}),
        '{}',
    ))
    conn.execute(
        "INSERT INTO operator_overrides "
        "(action, params_json, created_at, respekt_s, source, status) "
        "VALUES ('hp_toggle', '{\"state\": \"on\"}', ?, 3600, 'steuerbox', 'open')",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    conn.close()

    actuator = FakeActuator()
    result = OperatorOverrideProcessor(db).process_pending(actuator, {}, limit=5)

    conn = sqlite3.connect(db)
    status = conn.execute('SELECT status FROM operator_overrides').fetchone()[0]
    note, result_json = conn.execute('SELECT note, result_json FROM steuerbox_audit').fetchone()
    conn.close()

    assert result['failed'] == 1
    assert status == 'failed'
    assert note == 'override blocked by safety guard'
    assert 'soc too low' in result_json
    assert actuator.called is False


def main() -> int:
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'OK  {name}')
            except AssertionError as ex:
                failed += 1
                print(f'FAIL {name}: {ex}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())