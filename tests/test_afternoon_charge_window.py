#!/usr/bin/env python3
"""Test fuer das Fensterstart-Timing des afternoon_charge_request-Overrides.

Regression fuer den Fall »Ladewunsch vor 12:00 gedrueckt«: Das Zwei-Phasen-
Timing (Phase 1 SOC_MAX -> Phase 2 Fronius-Auto) muss ab Fensterstart
(start_earliest_h) zaehlen, nicht ab created_at. Frueher sprang ein Tastendruck
VOR dem Fenster bei Fensteroeffnung direkt in Phase 2 -> SOC_MAX wurde nie
gesetzt (Batterie blieb auf Morgen-Deckel).

Nutzung: python3 tests/test_afternoon_charge_window.py
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import automation.engine.operator_overrides as oo  # noqa: E402

PROC = oo.OperatorOverrideProcessor(db_path='/tmp/_afternoon_test_unused.db')
PARAMS = {'target_soc_pct': 100, 'start_earliest_h': 12.0}


class _FixedDateTime(_dt.datetime):
    _fixed = _dt.datetime(2026, 9, 30, 12, 0, 30)

    @classmethod
    def now(cls, tz=None):  # noqa: A003
        return cls._fixed

    @classmethod
    def utcnow(cls):
        return cls._fixed


def _at(h, m, s=0):
    _FixedDateTime._fixed = _dt.datetime(2026, 9, 30, h, m, s)


def _kommandos(plan):
    return [(a.get('kommando'), a.get('wert')) for a in (plan or [])]


def _run() -> int:
    orig = oo.datetime
    oo.datetime = _FixedDateTime
    fehler = 0
    try:
        # elapsed_s ab created_at simuliert einen Tastendruck um 11:46 (~14 min
        # vor Fensterstart) -> ohne Fix waere elapsed_s hier laengst > 60 s.
        elapsed_vorfenster = 870

        # 1) Vor dem Fenster (11:50): kein Kommando (Policy-Hold).
        _at(11, 50)
        plan = PROC._map_override_to_actions('afternoon_charge_request', PARAMS, {}, elapsed_s=600)
        assert plan == [], f'vor Fenster erwartet [], bekam {_kommandos(plan)}'
        assert oo._afternoon_window_elapsed_s(PARAMS, 600) is None

        # 2) Fenster gerade offen (12:00:30, ~30 s im Fenster) trotz elapsed 870:
        #    Phase 1 -> SOC_MAX = target (frueher faelschlich Phase 2).
        _at(12, 0, 30)
        plan = PROC._map_override_to_actions('afternoon_charge_request', PARAMS, {}, elapsed_s=elapsed_vorfenster)
        assert _kommandos(plan) == [('set_soc_max', 100)], \
            f'Fensteroeffnung erwartet set_soc_max=100, bekam {_kommandos(plan)}'

        # 3) Reapply in Phase 1 nur solange SOC_MAX noch nicht am Ziel.
        assert PROC._active_hold_needs_reapply(
            'afternoon_charge_request', PARAMS, {'soc_max': 75}, elapsed_s=elapsed_vorfenster) is True
        assert PROC._active_hold_needs_reapply(
            'afternoon_charge_request', PARAMS, {'soc_max': 100}, elapsed_s=elapsed_vorfenster) is False

        # 4) > 60 s nach Fensterstart (12:05): Phase 2 -> Fronius-Auto.
        _at(12, 5)
        plan = PROC._map_override_to_actions('afternoon_charge_request', PARAMS, {}, elapsed_s=elapsed_vorfenster)
        assert _kommandos(plan) == [('set_soc_mode', 'auto')], \
            f'Phase 2 erwartet set_soc_mode=auto, bekam {_kommandos(plan)}'
        assert PROC._active_hold_needs_reapply(
            'afternoon_charge_request', PARAMS, {'soc_mode': 'manual'}, elapsed_s=elapsed_vorfenster) is True
        assert PROC._active_hold_needs_reapply(
            'afternoon_charge_request', PARAMS, {'soc_mode': 'auto'}, elapsed_s=elapsed_vorfenster) is False

        # 5) In-Fenster-Tastendruck (Open-Row, elapsed_s=0) setzt sofort SOC_MAX.
        _at(12, 30)
        plan = PROC._map_override_to_actions('afternoon_charge_request', PARAMS, {}, elapsed_s=0)
        assert _kommandos(plan) == [('set_soc_max', 100)], \
            f'In-Fenster-Open erwartet set_soc_max=100, bekam {_kommandos(plan)}'
    except AssertionError as exc:
        print(f'FAIL: {exc}')
        fehler = 1
    finally:
        oo.datetime = orig

    if fehler == 0:
        print('OK: afternoon_charge_request Fensterstart-Timing korrekt (5 Faelle).')
    return fehler


if __name__ == '__main__':
    sys.exit(_run())
