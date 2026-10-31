#!/usr/bin/env python3
"""Tests fuer den Lade-Auto-Resolver (HA read-only).

Prueft die Identifizierungslogik (zoe1->Zoe-jk, zoe2->Zoe-X, Citroen) und die
sichere Inaktivitaet ohne Konfiguration/Token.

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


def _patch(monkeypatch, states: dict, enabled=True, token='x'):
    import config
    from routes.system import ha_cars
    monkeypatch.setattr(config, 'HA_READ_ENABLED', enabled, raising=False)
    monkeypatch.setattr(config, 'HA_READ_TOKEN', token, raising=False)
    monkeypatch.setattr(config, 'HA_READ_BASE_URL', 'http://ha.test:8123', raising=False)
    monkeypatch.setattr(config, 'HA_READ_CAR_ENTITIES', '', raising=False)
    import requests
    monkeypatch.setattr(requests, 'Session', lambda: _FakeSession(states))
    # Cache zuruecksetzen
    ha_cars._CACHE['ts'] = 0.0
    ha_cars._CACHE['value'] = None
    return ha_cars


def test_ohne_token_inaktiv(monkeypatch):
    ha = _patch(monkeypatch, {}, enabled=True, token='')
    assert ha.resolve_charging_car({'charging': True}) is None


def test_nicht_ladend_fragt_ha_nicht(monkeypatch):
    ha = _patch(monkeypatch, {'sensor.zoe2_ladezustand': 'Wird geladen'})
    assert ha.resolve_charging_car({'charging': False}) is None


def test_zoe_x_laedt(monkeypatch):
    ha = _patch(monkeypatch, {
        'sensor.zoe1_ladezustand': 'Nicht in Ladung',
        'sensor.zoe2_ladezustand': 'Wird geladen',
    })
    assert ha.resolve_charging_car({'charging': True}) == 'Zoe-X'


def test_zoe_jk_hat_prioritaet(monkeypatch):
    ha = _patch(monkeypatch, {
        'sensor.zoe1_ladezustand': 'Wird geladen',
        'sensor.zoe2_ladezustand': 'Wird geladen',
    })
    assert ha.resolve_charging_car({'charging': True}) == 'Zoe-jk'


def test_citroen_binary(monkeypatch):
    ha = _patch(monkeypatch, {
        'sensor.zoe1_ladezustand': 'unavailable',
        'sensor.zoe2_ladezustand': 'unknown',
        'binary_sensor.chris_citroen_batterie_ladt': 'on',
    })
    assert ha.resolve_charging_car({'charging': True}) == 'Citroën'


def test_kein_auto_erkannt(monkeypatch):
    ha = _patch(monkeypatch, {
        'sensor.zoe1_ladezustand': 'unavailable',
        'sensor.zoe2_ladezustand': 'Nicht in Ladung',
        'binary_sensor.chris_citroen_batterie_ladt': 'off',
    })
    assert ha.resolve_charging_car({'charging': True}) is None


def test_config_override(monkeypatch):
    import config
    ha = _patch(monkeypatch, {'sensor.custom_car': 'laedt'})
    monkeypatch.setattr(config, 'HA_READ_CAR_ENTITIES',
                        'sensor.custom_car|laedt|MeinAuto', raising=False)
    assert ha.resolve_charging_car({'charging': True}) == 'MeinAuto'


if __name__ == '__main__':
    import pytest
    raise SystemExit(pytest.main([__file__, '-v']))
