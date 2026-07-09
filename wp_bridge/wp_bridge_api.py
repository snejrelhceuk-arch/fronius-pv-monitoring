#!/usr/bin/env python3
"""Pi4-Tech WP-Hardware-Bridge — abgesicherter HTTP-Zugang zur WP (Rolle: HW-Bridge).

Endpunkte:
  GET  /health          — Liveness (ohne Auth, minimal).
  GET  /api/wp/status   — WP-Status lesen (Bearer-Token).
  POST /api/wp/write     — Whitelist-Register schreiben (Bearer-Token).

Sicherheit:
  - Bearer-Token (konstante Zeit, fail-closed bei fehlendem Token).
  - Whitelist + Wertebereich (aus wp_modbus._WRITE_REGS).
  - Rate-Limit (global + separat für Schreibbefehle).
  - Audit-Log jeder Schreibaktion.
  - Kein Split-Brain: läuft nur mit WP_BACKEND_MODE=local (sonst Startverweigerung).

Der Dienst führt KEINE Engine-Entscheidungen aus — nur Hardwarezugriff auf Kommando.
"""
from __future__ import annotations

import hmac
import logging
import os
import time
from collections import deque
from functools import wraps

from flask import Flask, jsonify, request

import config
import wp_modbus

LOG = logging.getLogger('wp_bridge')
logging.basicConfig(level=logging.INFO)

# Audit-Log (jede Schreibaktion, keine Secrets)
_AUDIT_PATH = os.path.join(config.BASE_DIR, 'logs', 'wp_bridge_audit.log')
_audit = logging.getLogger('wp_bridge.audit')
_audit.setLevel(logging.INFO)
_audit.propagate = False
try:
    os.makedirs(os.path.dirname(_AUDIT_PATH), exist_ok=True)
    _fh = logging.FileHandler(_AUDIT_PATH)
    _fh.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    _audit.addHandler(_fh)
except OSError as exc:  # pragma: no cover
    LOG.warning('Audit-Log nicht schreibbar (%s): %s', _AUDIT_PATH, exc)

app = Flask(__name__)

# ── Rate-Limit (in-memory sliding window) ────────────────────────────────
_WINDOW_S = 60.0
_hits: dict[str, deque] = {'all': deque(), 'write': deque()}


def _rate_ok(bucket: str, limit: int) -> bool:
    now = time.time()
    dq = _hits[bucket]
    while dq and now - dq[0] > _WINDOW_S:
        dq.popleft()
    if len(dq) >= limit:
        return False
    dq.append(now)
    return True


# ── Auth ─────────────────────────────────────────────────────────────────
def _token_ok(header_value: str) -> bool:
    expected = config.WP_BRIDGE_TOKEN
    if not expected:
        return False  # fail-closed: ohne konfiguriertes Token nichts zulassen
    if not header_value or not header_value.startswith('Bearer '):
        return False
    provided = header_value[len('Bearer '):].strip()
    return hmac.compare_digest(provided, expected)


def require_token(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not config.WP_BRIDGE_TOKEN:
            return jsonify(ok=False, error='bridge_token_not_configured'), 503
        if not _rate_ok('all', config.WP_BRIDGE_RATE_LIMIT_PER_MIN):
            return jsonify(ok=False, error='rate_limited'), 429
        if not _token_ok(request.headers.get('Authorization', '')):
            return jsonify(ok=False, error='unauthorized'), 401
        return fn(*args, **kwargs)
    return wrapper


# ── Endpunkte ──────────────────────────────────────────────────────────────
@app.get('/health')
def health():
    return jsonify(ok=True, service='wp_bridge', backend=config.WP_BACKEND_MODE)


@app.get('/api/wp/status')
@require_token
def wp_status():
    data = wp_modbus.get_wp_status()
    if data is None:
        return jsonify(ok=False, error='wp_read_failed'), 502
    return jsonify(ok=True, data=data)


@app.post('/api/wp/write')
@require_token
def wp_write():
    if not _rate_ok('write', config.WP_BRIDGE_WRITE_LIMIT_PER_MIN):
        return jsonify(ok=False, error='write_rate_limited'), 429

    body = request.get_json(silent=True) or {}
    name = str(body.get('name', '')).strip()
    raw_value = body.get('value')

    if name not in wp_modbus._WRITE_REGS:
        _audit.info('WRITE_DENIED name=%r reason=not_whitelisted from=%s',
                    name, request.remote_addr)
        return jsonify(ok=False, error='not_whitelisted',
                       allowed=list(wp_modbus._WRITE_REGS.keys())), 400

    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        _audit.info('WRITE_DENIED name=%s value=%r reason=not_int from=%s',
                    name, raw_value, request.remote_addr)
        return jsonify(ok=False, error='value_not_int'), 400

    reg = wp_modbus._WRITE_REGS[name]
    if not reg['min'] <= value <= reg['max']:
        _audit.info('WRITE_DENIED name=%s value=%d reason=out_of_range[%d,%d] from=%s',
                    name, value, reg['min'], reg['max'], request.remote_addr)
        return jsonify(ok=False, error='out_of_range',
                       min=reg['min'], max=reg['max']), 400

    ok = wp_modbus.write_register(name, value)
    _audit.info('WRITE name=%s value=%d result=%s from=%s',
                name, value, 'OK' if ok else 'FAIL', request.remote_addr)
    if not ok:
        return jsonify(ok=False, error='write_failed'), 502
    return jsonify(ok=True, name=name, value=value)


def main():
    if config.WP_BACKEND_MODE == 'remote':
        raise SystemExit(
            'wp_bridge darf nur mit WP_BACKEND_MODE=local laufen '
            '(remote würde eine Endlosschleife erzeugen).')
    if not config.WP_BRIDGE_TOKEN:
        LOG.warning('WP_BRIDGE_TOKEN nicht gesetzt — Endpunkte antworten mit 503.')
    LOG.info('WP-Bridge startet auf %s:%d (backend=%s)',
             config.WP_BRIDGE_BIND, config.WP_BRIDGE_PORT, config.WP_BACKEND_MODE)
    app.run(host=config.WP_BRIDGE_BIND, port=config.WP_BRIDGE_PORT, threaded=True)


if __name__ == '__main__':
    main()
