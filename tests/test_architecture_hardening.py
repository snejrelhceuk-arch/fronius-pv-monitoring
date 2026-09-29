#!/usr/bin/env python3
"""Regressionstests fuer Architektur-Haertung."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from collections import defaultdict, deque
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


def test_actuator_logs_actor_exception_as_failure():
    from automation.engine import actuator as actuator_mod
    from automation.engine.actuator import Actuator

    class RaisingActor:
        dry_run = False

        def ausfuehren(self, aktion):
            raise RuntimeError('boom')

        def verifiziere(self, aktion):
            raise AssertionError('must not verify failed action')

    db = os.path.join(tempfile.mkdtemp(), 'persist.db')
    act = Actuator.__new__(Actuator)
    act.dry_run = False
    act._persist_conn = None
    act._persist_db_path = db
    act._aktoren = {'dummy': RaisingActor()}
    act._letzte_aktion = {}
    act._letzte_fehler = {}
    act._aktionshistorie = defaultdict(deque)
    act._letzte_oszillationswarnung = {}

    old_logge_engine = actuator_mod.logge_engine
    try:
        actuator_mod.logge_engine = lambda **kwargs: None
        result = act.ausfuehren({
            'aktor': 'dummy',
            'kommando': 'crash',
            'wert': 1,
            'grund': 'test exception boundary',
        })
    finally:
        actuator_mod.logge_engine = old_logge_engine
        act.close()

    assert result['ok'] is False
    assert result['exception_type'] == 'RuntimeError'

    conn = sqlite3.connect(db)
    row = conn.execute(
        'SELECT aktor, kommando, ergebnis, detail FROM automation_log'
    ).fetchone()
    conn.close()

    assert row == ('dummy', 'crash', 'FEHLER', 'Exception: boom')


def test_collector_uses_wattpilot_readonly_facade():
    from wattpilot_read_api import WattpilotReadOnly

    collector_path = os.path.join(_ROOT, 'collector', 'wattpilot.py')
    with open(collector_path, encoding='utf-8') as f:
        source = f.read()

    assert 'from wattpilot_api import WattpilotClient' not in source
    assert 'from wattpilot_read_api import WattpilotReadOnly' in source
    assert not hasattr(WattpilotReadOnly, 'set_value')


def test_architecture_audit_allows_wattpilot_read_facade_only():
    from tools import audit_architecture

    findings = audit_architecture.writable_client_findings()
    paths = {item['path'] for item in findings}

    assert 'wattpilot_read_api.py' not in paths
    assert 'collector/wattpilot.py' not in paths


def test_db_connection_ro_blocks_writes():
    import db_utils

    db = os.path.join(tempfile.mkdtemp(), 'web_ro.db')
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE sample (id INTEGER PRIMARY KEY)')
    conn.commit()
    conn.close()

    old_db_path = db_utils.config.DB_PATH
    try:
        db_utils.config.DB_PATH = db
        ro_conn = db_utils.get_db_connection_ro()
        try:
            ro_conn.execute('INSERT INTO sample (id) VALUES (1)')
            raise AssertionError('read-only connection allowed a write')
        except sqlite3.OperationalError:
            pass
        finally:
            ro_conn.close()
    finally:
        db_utils.config.DB_PATH = old_db_path


def test_nq_timer_catalog_matches_primary_install_map():
    from diagnos.config import CRIT, WARN, NQ_TIMERS

    timers = dict(NQ_TIMERS)
    expected = {
        'pv-nq-agg-transfer.timer': CRIT,
        'pv-nq-aggregate.timer': CRIT,
        'pv-nq-energy-rollup.timer': CRIT,
        'pv-nq-primary-cap.timer': CRIT,
        'pv-nq-event-transfer.timer': WARN,
        'pv-nq-analysis.timer': WARN,
        'pv-nq-analysis-hf-nf.timer': WARN,
        'pv-nq-energy-rollup-month.timer': WARN,
        'pv-nq-energy-rollup-year.timer': WARN,
        'pv-nq-backup.timer': WARN,
    }

    assert timers == expected


def test_health_reports_missing_systemd_working_directory():
    from diagnos import health

    class FakeRunResult:
        def __init__(self, stdout, returncode=0):
            self.stdout = stdout
            self.stderr = ''
            self.returncode = returncode

    def fake_run(cmd, capture_output=True, text=True, timeout=5):
        if cmd[:2] == ['systemctl', 'list-unit-files']:
            return FakeRunResult('pv-web.service enabled\npv-nq.service static\n')
        if cmd[:3] == ['systemctl', 'show', 'pv-web.service']:
            return FakeRunResult('LoadState=loaded\nWorkingDirectory=/missing/pv-system\n')
        if cmd[:3] == ['systemctl', 'show', 'pv-nq.service']:
            return FakeRunResult('LoadState=loaded\nWorkingDirectory=/ok/pv-system\n')
        raise AssertionError(cmd)

    old_run = health.subprocess.run
    old_isdir = health.os.path.isdir
    try:
        health.subprocess.run = fake_run
        health.os.path.isdir = lambda path: path == '/ok/pv-system'
        result = health.check_pv_unit_working_directories()
    finally:
        health.subprocess.run = old_run
        health.os.path.isdir = old_isdir

    assert result['severity'] == health.CRIT
    assert result['missing'] == {'pv-web.service': '/missing/pv-system'}


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