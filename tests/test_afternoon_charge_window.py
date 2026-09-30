#!/usr/bin/env python3
"""Test: Ladewunsch »spät nachmittags« — prognose-/SOC-abhängige Startzeit.

Der afternoon_charge_request laedt die Batterie NICHT sofort auf 100 %.
`RegelNachmittagSocMax` berechnet den SOC_MAX-Oeffnungszeitpunkt (im Fenster
start_earliest_h..start_latest_h) so, dass ~100 % erst spaet nachmittags
erreicht werden:
  - hoher SOC + starke Restprognose  -> spaet (Richtung start_latest_h),
  - niedriger SOC / schwache Prognose -> frueh (start_earliest_h, Ladezeit).
Der OperatorOverrideProcessor haelt den Intent nur als Policy-Hold (kein
direkter SOC-Schreibpfad mehr).

Nutzung: python3 tests/test_afternoon_charge_window.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from automation.engine.obs_state import ObsState  # noqa: E402
from automation.engine.operator_overrides import OperatorOverrideProcessor  # noqa: E402
from automation.engine.regeln.soc_steuerung import RegelNachmittagSocMax  # noqa: E402

INTENT = {'target_soc_pct': 100, 'start_earliest_h': 12.0, 'start_latest_h': 15.0}


def _startzeit(soc: float, rest_kwh: float, dyn_start: float) -> float:
    o = ObsState()
    o.batt_soc_pct = soc
    o.forecast_rest_kwh = rest_kwh
    return RegelNachmittagSocMax._berechne_intent_startzeit(o, dyn_start, INTENT)


def _run() -> int:
    fehler = 0
    try:
        # dyn_start (SOC_MAX-Oeffnung, wenn PV unter Schwelle sinkt) an einem
        # starken Tag ~16 h.
        DYN = 16.0

        # 1) Hoher SOC + starke Restprognose -> spaet (start_latest_h=15, an einem
        #    Sommertag ~3-4 h vor Sunset), NICHT sofort. Genau der Nutzerfall.
        assert _startzeit(66, 60, DYN) == 15.0, _startzeit(66, 60, DYN)
        assert _startzeit(80, 40, DYN) == 15.0, _startzeit(80, 40, DYN)

        # 2) Mittlerer SOC -> etwas frueher (dyn_start-1), geklemmt auf 12..15.
        assert _startzeit(60, 30, DYN) == 15.0, _startzeit(60, 30, DYN)
        assert _startzeit(60, 30, 14.0) == 13.0, _startzeit(60, 30, 14.0)

        # 3) Niedriger SOC ODER schwache Restprognose -> sofort ab earliest (12 h),
        #    damit genug Ladezeit bleibt.
        assert _startzeit(30, 60, DYN) == 12.0, _startzeit(30, 60, DYN)
        assert _startzeit(80, 8, DYN) == 12.0, _startzeit(80, 8, DYN)

        # 4) Startzeit bleibt immer im Fenster [earliest, latest].
        assert _startzeit(90, 80, 20.0) == 15.0
        assert _startzeit(90, 80, 10.0) == 12.0

        # 5) Processor ist reiner Policy-Hold (keine direkte SOC-Aktion) — die
        #    SOC-Oeffnung macht die Regel prognosegetragen.
        proc = OperatorOverrideProcessor(db_path='/tmp/_afternoon_test_unused.db')
        assert proc._map_override_to_actions('afternoon_charge_request', INTENT, {}, elapsed_s=0) == []
        assert proc._map_override_to_actions('afternoon_charge_request', INTENT, {}, elapsed_s=5000) == []
        assert proc._active_hold_needs_reapply(
            'afternoon_charge_request', INTENT, {'soc_max': 75}, elapsed_s=5000) is False
    except AssertionError as exc:
        print(f'FAIL: {exc}')
        fehler = 1

    if fehler == 0:
        print('OK: Ladewunsch-Startzeit prognose-/SOC-abhaengig + Processor Policy-Hold.')
    return fehler


if __name__ == '__main__':
    sys.exit(_run())
