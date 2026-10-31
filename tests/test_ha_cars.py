#!/usr/bin/env python3
"""Tests fuer den Lade-Auto-Resolver (HA read-only) inkl. Session-Latch.

Prueft die Identifizierungslogik (zoe1->Zoe-jk, zoe2->Zoe-X, Citroen), die
sichere Inaktivitaet ohne Konfiguration/Token sowie das Persistieren des
Auto-Namens ueber Ladepausen/-ende bis zum naechsten Anstecken (session_wh-Reset).

Nutzung: python3 -m pytest tests/test_ha_cars.py
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class _FakeResp:
    def __init__(self, state):
        self._state = state
        self.status_code = 200 if state is not None else 404

    def json(self):
        return {'state': self._state}


class _FakeSession:
    def __init__(self, states: dict):
        self._states = states

    def get(self, url, headers=None, timeout=None):
        entity = url.rsplit('/', 1)[-1]
        return _FakeResp(self._states.get(entity))


def _patch(monkeypatch, tmp_path, states: dict, enabled=True, token='x'):
    import config
    from routes.system import ha_cars
    monkeypatch.setattr(config, 'HA_READ_ENABLED', enabled, raising=False)
    monkeypatch.setattr(config, 'HA_READ_TOKEN', token, raising=False)
    monkeypatch.setattr(config, 'HA_READ_BASE_URL', 'http://ha.test:8123', raising=False)
    monkeypatch.setattr(config, 'HA_READ_CAR_ENTITIES', '', raising=False)
    import requests
    monkeypatch.setattr(requests, 'Session', lambda: _FakeSession(states))
    # Latch in tmp (keine Seiteneffekte in config/), HA-Cache zuruecksetzen.
    monkeypatch.setattr(ha_cars, '_LATCH_PATH', tmp_path / 'latch.json', raising=False)
    ha_cars._HA_CACHE['ts'] = 0.0
    ha_cars._HA_CACHE['value'] = None
    return ha_cars


def _wp(session_wh=0.0, charging=True, car_state=2):
    return {'energy_session_wh': session_wh, 'charging': charging, 'car_state': car_state}


def test_ohne_token_inaktiv(monkeypatch, tmp_path):
    ha = _patch(monkeypatch, tmp_path, {}, enabled=True, token='')
    assert ha.resolve_charging_car(_wp()) is None


def test_zoe_x_laedt(monkeypatch, tmp_path):
    ha = _patch(monkeypatch, tmp_path, {
        'sensor.zoe1_ladezustand': 'not_in_charge',
        'sensor.zoe2_ladezustand': 'charge_in_progress',
    })
    assert ha.resolve_charging_car(_wp(session_wh=500)) == 'Zoe-X'


def test_zoe_jk_hat_prioritaet(monkeypatch, tmp_path):
    ha = _patch(monkeypatch, tmp_path, {
        'sensor.zoe1_ladezustand': 'charge_in_progress',
        'sensor.zoe2_ladezustand': 'charge_in_progress',
    })
    assert ha.resolve_charging_car(_wp()) == 'Zoe-jk'


def test_citroen_binary(monkeypatch, tmp_path):
    ha = _patch(monkeypatch, tmp_path, {
        'sensor.zoe1_ladezustand': 'unavailable',
        'sensor.zoe2_ladezustand': 'not_in_charge',
        'binary_sensor.chris_citroen_batterie_ladt': 'on',
    })
    assert ha.resolve_charging_car(_wp()) == 'Citroën'


def test_kein_auto_erkannt(monkeypatch, tmp_path):
    ha = _patch(monkeypatch, tmp_path, {
        'sensor.zoe1_ladezustand': 'unavailable',
        'sensor.zoe2_ladezustand': 'not_in_charge',
        'binary_sensor.chris_citroen_batterie_ladt': 'off',
    })
    assert ha.resolve_charging_car(_wp()) is None


def test_name_persistiert_nach_ladeende(monkeypatch, tmp_path):
    """Zoe-X laedt -> Name erkannt; danach Ladeende (nicht mehr identifizierbar)
    -> Name bleibt bestehen (gleiche Session, session_wh haelt)."""
    ha = _patch(monkeypatch, tmp_path, {
        'sensor.zoe2_ladezustand': 'charge_in_progress',
    })
    assert ha.resolve_charging_car(_wp(session_wh=500, charging=True)) == 'Zoe-X'
    # Ladeende: HA meldet kein ladendes Auto mehr, car_state=4 (Vollstaendig)
    ha2 = _patch(monkeypatch, tmp_path, {
        'sensor.zoe2_ladezustand': 'not_in_charge',
    })
    assert ha2.resolve_charging_car(_wp(session_wh=6900, charging=False, car_state=4)) == 'Zoe-X'
    # Auto abgesteckt (kein Auto), session_wh haelt -> Name bleibt
    assert ha2.resolve_charging_car(_wp(session_wh=6900, charging=False, car_state=1)) == 'Zoe-X'


def test_neues_auto_setzt_latch_zurueck(monkeypatch, tmp_path):
    """Nach session_wh-Reset (neues Auto) wird neu aufgeloest."""
    ha = _patch(monkeypatch, tmp_path, {
        'sensor.zoe2_ladezustand': 'charge_in_progress',
    })
    assert ha.resolve_charging_car(_wp(session_wh=6900, charging=True)) == 'Zoe-X'
    # Neues Auto angesteckt: session_wh faellt zurueck, jetzt laedt Citroen
    ha2 = _patch(monkeypatch, tmp_path, {
        'sensor.zoe2_ladezustand': 'not_in_charge',
        'binary_sensor.chris_citroen_batterie_ladt': 'on',
    })
    assert ha2.resolve_charging_car(_wp(session_wh=50, charging=True)) == 'Citroën'


def test_neue_session_haelt_alten_namen_bis_neu_identifiziert(monkeypatch, tmp_path):
    """Neues Auto angesteckt (session_wh-Reset), aber noch nicht ladend/
    identifizierbar -> alter Name bleibt bestehen (verschwindet NICHT), bis ein
    neues Auto beim Laden positiv erkannt wird."""
    ha = _patch(monkeypatch, tmp_path, {
        'sensor.zoe2_ladezustand': 'charge_in_progress',
    })
    assert ha.resolve_charging_car(_wp(session_wh=6900, charging=True)) == 'Zoe-X'
    # session_wh faellt zurueck (abgesteckt/neue Session), nichts identifizierbar
    ha2 = _patch(monkeypatch, tmp_path, {
        'sensor.zoe2_ladezustand': 'not_in_charge',
    })
    assert ha2.resolve_charging_car(_wp(session_wh=0, charging=False, car_state=3)) == 'Zoe-X'
    # Ladeende/Abstecken mit Reset, aber weiterhin nicht identifizierbar -> haelt
    assert ha2.resolve_charging_car(_wp(session_wh=0, charging=False, car_state=1)) == 'Zoe-X'


def test_config_override_multi_state(monkeypatch, tmp_path):
    import config
    ha = _patch(monkeypatch, tmp_path, {'sensor.custom_car': 'charge_in_progress'})
    monkeypatch.setattr(config, 'HA_READ_CAR_ENTITIES',
                        'sensor.custom_car|laedt/charge_in_progress|MeinAuto', raising=False)
    assert ha.resolve_charging_car(_wp()) == 'MeinAuto'


def test_steuerbox_card_match():
    import config
    assert 'wp_mode' in config.STEUERBOX_ALLOWED_ACTIONS


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
