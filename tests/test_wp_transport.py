#!/usr/bin/env python3
"""Tests für die WP-Transport-Abstraktion (local/remote) und die Pi4-Tech Bridge.

Deckt ab:
  - local-Modus dispatcht auf die Serial-Pfade (unverändert)
  - remote-Modus dispatcht auf HTTP + Fehlerpfade sind fail-safe
  - Whitelist/Wertebereich werden VOR jedem HTTP geprüft
  - Bridge: Auth (fail-closed), Whitelist, Wertebereich, Rate-Limit

Nutzung:
  python3 tests/test_wp_transport.py
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config  # noqa: E402
import wp_modbus  # noqa: E402


class _FakeResp:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


def _reset_cache():
    wp_modbus._WP_CACHE = {'ts': 0, 'data': None}


class TestTransportDispatch(unittest.TestCase):
    def setUp(self):
        _reset_cache()
        self._mode = config.WP_BACKEND_MODE
        self._url = config.WP_REMOTE_BASE_URL
        self._tok = config.WP_REMOTE_TOKEN

    def tearDown(self):
        config.WP_BACKEND_MODE = self._mode
        config.WP_REMOTE_BASE_URL = self._url
        config.WP_REMOTE_TOKEN = self._tok
        _reset_cache()

    def test_local_poll_dispatch(self):
        config.WP_BACKEND_MODE = 'local'
        with mock.patch.object(wp_modbus, '_poll_local',
                               return_value={'ww_ist': 50.0}) as m_local, \
             mock.patch.object(wp_modbus, '_poll_remote') as m_remote:
            data = wp_modbus.get_wp_status()
        self.assertEqual(data, {'ww_ist': 50.0})
        m_local.assert_called_once()
        m_remote.assert_not_called()

    def test_local_write_dispatch(self):
        config.WP_BACKEND_MODE = 'local'
        with mock.patch.object(wp_modbus, '_write_register_local',
                               return_value=True) as m_local, \
             mock.patch.object(wp_modbus, '_write_register_remote') as m_remote:
            ok = wp_modbus.write_register('ww_soll', 55)
        self.assertTrue(ok)
        m_local.assert_called_once()
        m_remote.assert_not_called()

    def test_remote_poll_dispatch(self):
        config.WP_BACKEND_MODE = 'remote'
        config.WP_REMOTE_BASE_URL = 'http://bridge.invalid:8091'
        config.WP_REMOTE_TOKEN = 'tok'
        resp = _FakeResp(200, {'ok': True, 'data': {'ww_ist': 48.0}})
        with mock.patch('requests.get', return_value=resp) as m_get:
            data = wp_modbus.get_wp_status()
        self.assertEqual(data, {'ww_ist': 48.0})
        args, kwargs = m_get.call_args
        self.assertTrue(args[0].endswith('/api/wp/status'))
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer tok')

    def test_remote_write_dispatch(self):
        config.WP_BACKEND_MODE = 'remote'
        config.WP_REMOTE_BASE_URL = 'http://bridge.invalid:8091'
        config.WP_REMOTE_TOKEN = 'tok'
        resp = _FakeResp(200, {'ok': True, 'name': 'ww_soll', 'value': 55})
        with mock.patch('requests.post', return_value=resp) as m_post:
            ok = wp_modbus.write_register('ww_soll', 55)
        self.assertTrue(ok)
        args, kwargs = m_post.call_args
        self.assertTrue(args[0].endswith('/api/wp/write'))
        self.assertEqual(kwargs['json'], {'name': 'ww_soll', 'value': 55})

    def test_remote_validation_before_http(self):
        """Whitelist/Range werden geprüft, BEVOR ein HTTP-Call passiert."""
        config.WP_BACKEND_MODE = 'remote'
        config.WP_REMOTE_BASE_URL = 'http://bridge.invalid:8091'
        with mock.patch('requests.post') as m_post:
            self.assertFalse(wp_modbus.write_register('nicht_erlaubt', 10))
            self.assertFalse(wp_modbus.write_register('ww_soll', 999))  # out of range
        m_post.assert_not_called()

    def test_remote_http_error_is_failsafe(self):
        config.WP_BACKEND_MODE = 'remote'
        config.WP_REMOTE_BASE_URL = 'http://bridge.invalid:8091'
        with mock.patch('requests.get', return_value=_FakeResp(502, {})):
            self.assertIsNone(wp_modbus.get_wp_status())
        with mock.patch('requests.post', return_value=_FakeResp(500, {}, 'boom')):
            self.assertFalse(wp_modbus.write_register('ww_soll', 55))

    def test_remote_connection_error_is_failsafe(self):
        config.WP_BACKEND_MODE = 'remote'
        config.WP_REMOTE_BASE_URL = 'http://bridge.invalid:8091'
        with mock.patch('requests.get', side_effect=OSError('no route')):
            self.assertIsNone(wp_modbus.get_wp_status())
        with mock.patch('requests.post', side_effect=OSError('no route')):
            self.assertFalse(wp_modbus.write_register('ww_soll', 55))


class TestBridge(unittest.TestCase):
    def setUp(self):
        from wp_bridge import wp_bridge_api
        self.api = wp_bridge_api
        self.client = wp_bridge_api.app.test_client()
        self._tok = config.WP_BRIDGE_TOKEN
        self._mode = config.WP_BACKEND_MODE
        config.WP_BRIDGE_TOKEN = 'secret-token'
        config.WP_BACKEND_MODE = 'local'
        # Rate-Limit-Fenster zurücksetzen
        for dq in wp_bridge_api._hits.values():
            dq.clear()

    def tearDown(self):
        config.WP_BRIDGE_TOKEN = self._tok
        config.WP_BACKEND_MODE = self._mode
        for dq in self.api._hits.values():
            dq.clear()

    def _auth(self):
        return {'Authorization': 'Bearer secret-token'}

    def test_health_no_auth(self):
        r = self.client.get('/health')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['ok'])

    def test_status_requires_token(self):
        r = self.client.get('/api/wp/status')
        self.assertEqual(r.status_code, 401)

    def test_status_with_token(self):
        with mock.patch.object(wp_modbus, 'get_wp_status',
                               return_value={'ww_ist': 47.0}):
            r = self.client.get('/api/wp/status', headers=self._auth())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()['data'], {'ww_ist': 47.0})

    def test_status_token_missing_config_is_503(self):
        config.WP_BRIDGE_TOKEN = ''
        r = self.client.get('/api/wp/status', headers=self._auth())
        self.assertEqual(r.status_code, 503)

    def test_write_valid(self):
        with mock.patch.object(wp_modbus, 'write_register',
                               return_value=True) as m_w:
            r = self.client.post('/api/wp/write',
                                 json={'name': 'ww_soll', 'value': 55},
                                 headers=self._auth())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['ok'])
        m_w.assert_called_once_with('ww_soll', 55)

    def test_write_not_whitelisted(self):
        with mock.patch.object(wp_modbus, 'write_register') as m_w:
            r = self.client.post('/api/wp/write',
                                 json={'name': 'boese', 'value': 1},
                                 headers=self._auth())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['error'], 'not_whitelisted')
        m_w.assert_not_called()

    def test_write_out_of_range(self):
        with mock.patch.object(wp_modbus, 'write_register') as m_w:
            r = self.client.post('/api/wp/write',
                                 json={'name': 'ww_soll', 'value': 999},
                                 headers=self._auth())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()['error'], 'out_of_range')
        m_w.assert_not_called()

    def test_write_rate_limit(self):
        config.WP_BRIDGE_WRITE_LIMIT_PER_MIN = 2
        with mock.patch.object(wp_modbus, 'write_register', return_value=True):
            codes = [
                self.client.post('/api/wp/write',
                                 json={'name': 'ww_soll', 'value': 55},
                                 headers=self._auth()).status_code
                for _ in range(4)
            ]
        self.assertEqual(codes[:2], [200, 200])
        self.assertIn(429, codes[2:])


if __name__ == '__main__':
    unittest.main(verbosity=2)
