#!/usr/bin/env python3
"""Charakterisierung: Schutz-Regeln schlagen Optimierungs-Regeln pro Kommando.

Absicherung gegen Wiederhol-Schaltungen (Ping-Pong): Setzt eine Schutz-Regel
in einem Zyklus z. B. ``set_soc_min`` (Wattpilot-Schutz → 25 %), darf eine
Optimierungs-Regel dasselbe Kommando NICHT überschreiben (Komfort-Reset → 20 %).
Andere Kommandos der Optim-Regel bleiben erlaubt.

Nutzung: python3 tests/test_engine_schutz_vs_optim.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import automation.engine.engine as engine_mod  # noqa: E402
from automation.engine.engine import Engine  # noqa: E402


class _FakeObs:
    alarm_batt_temp = False
    alarm_batt_kritisch = False


class _FakeRegel:
    def __init__(self, name, score, aktionen, zyklus='fast', aktor='batterie'):
        self.name = name
        self._score = score
        self._aktionen = aktionen
        self.engine_zyklus = zyklus
        self.aktor = aktor
        self.regelkreis = name

    def bewerte(self, obs, matrix):
        return self._score

    def erzeuge_aktionen(self, obs, matrix):
        return [dict(a) for a in self._aktionen]


class _RecordingActuator:
    def __init__(self):
        self.calls = []

    def ausfuehren_plan(self, aktionen):
        self.calls.extend(aktionen)
        return [{'kommando': a.get('kommando'), 'wert': a.get('wert'), 'ok': True}
                for a in aktionen]


def _build_engine(regeln, actuator):
    eng = Engine.__new__(Engine)
    eng._regeln = regeln
    eng._matrix = {}
    eng.actuator = actuator
    eng._ram_db_conn = None
    eng._get_ram_db = lambda: object()
    return eng


def _run() -> int:
    fehler = 0
    orig_read = engine_mod.read_obs_state
    orig_aut = engine_mod.soc_automation_aktiv
    engine_mod.read_obs_state = lambda conn: _FakeObs()
    engine_mod.soc_automation_aktiv = lambda matrix: True
    try:
        schutz = _FakeRegel(
            'wattpilot_schutz', 130,
            [{'tier': 2, 'aktor': 'batterie', 'kommando': 'set_soc_min', 'wert': 25}])
        optim = _FakeRegel(
            'komfort_reset', 50,
            [{'tier': 2, 'aktor': 'batterie', 'kommando': 'set_soc_min', 'wert': 20},
             {'tier': 2, 'aktor': 'batterie', 'kommando': 'set_soc_max', 'wert': 80}])
        act = _RecordingActuator()
        eng = _build_engine([schutz, optim], act)
        eng.zyklus('fast')

        soc_min_calls = [c for c in act.calls if c['kommando'] == 'set_soc_min']
        soc_max_calls = [c for c in act.calls if c['kommando'] == 'set_soc_max']

        # Schutz-Wert 25 bleibt; Optim-20 wird unterdrückt (kein Ping-Pong).
        assert len(soc_min_calls) == 1, soc_min_calls
        assert soc_min_calls[0]['wert'] == 25, soc_min_calls
        assert all(c['wert'] != 20 for c in soc_min_calls), soc_min_calls
        # Nicht-kollidierendes Optim-Kommando (set_soc_max) bleibt erlaubt.
        assert len(soc_max_calls) == 1 and soc_max_calls[0]['wert'] == 80, soc_max_calls
    except AssertionError as exc:
        print(f'FAIL: {exc}')
        fehler = 1
    finally:
        engine_mod.read_obs_state = orig_read
        engine_mod.soc_automation_aktiv = orig_aut

    if fehler == 0:
        print('OK: Schutz > Optimierung je Kommando (Ping-Pong-Absicherung).')
    return fehler


if __name__ == '__main__':
    sys.exit(_run())
