#!/usr/bin/env python3
"""Steuerbox Flask-Dienst (Schicht E): Intent-API + Operator-UI."""

from __future__ import annotations

import logging
import socket
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request

import config
from host_role import is_failover
from steuerbox.intent_handler import get_audit, get_status, handle_intent
from steuerbox.validators import check_allowlist

LOG = logging.getLogger('steuerbox')
logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder='templates', static_folder='static')


def _asset_version(relative_path: str) -> int:
    asset_path = Path(app.static_folder) / relative_path
    try:
        return int(asset_path.stat().st_mtime)
    except OSError:
        return 0


def _check_port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        return True
    except OSError:
        return False


@app.before_request
def _security_gate() -> None:
    # Sicherheit: TLS (nginx) + IP-Allowlist (LAN only).
    check_allowlist()

    if request.path.startswith('/api/ops/') and request.method != 'OPTIONS':
        if request.method != 'GET' and is_failover():
            abort(403, description='failover host is read-only')


@app.route('/')
def index():
    return render_template(
        'cockpit.html',
        host_role='failover' if is_failover() else 'primary',
        default_respekt_s=config.STEUERBOX_DEFAULT_RESPEKT_S,
        min_respekt_s=config.STEUERBOX_MIN_RESPEKT_S,
        max_respekt_s=config.STEUERBOX_MAX_RESPEKT_S,
        css_version=_asset_version('css/cockpit.css'),
        js_version=_asset_version('js/cockpit.js'),
        favicon_version=_asset_version('img/favicon-steuerbox.svg'),
    )


@app.route('/api/ops/intent', methods=['POST'])
def api_intent():
    payload = request.get_json(silent=True) or {}
    action = (payload.get('action') or '').strip()
    params = payload.get('params') or {}
    respekt_s = payload.get('respekt_s')

    if not action:
        abort(422, description='missing action')
    if not isinstance(params, dict):
        abort(422, description='params must be object')

    result = handle_intent(
        action=action,
        params=params,
        client_ip=request.remote_addr or '',
        respekt_s=respekt_s,
    )

    return jsonify(
        {
            'ok': True,
            'override_id': result.override_id,
            'created_at': result.created_at,
            'respekt_s': result.respekt_s,
            'respekt_remaining_s': result.respekt_remaining_s,
            'status': result.status,
        }
    )


@app.route('/api/ops/status', methods=['GET'])
def api_status():
    limit = int(request.args.get('limit', 50))
    return jsonify(get_status(limit=limit))


@app.route('/api/ops/audit', methods=['GET'])
def api_audit():
    limit = int(request.args.get('limit', 50))
    return jsonify(get_audit(limit=limit))


@app.route('/api/ops/health', methods=['GET'])
def api_health():
    return jsonify(
        {
            'ok': True,
            'service': 'steuerbox',
            'role': 'failover' if is_failover() else 'primary',
            'port': config.STEUERBOX_PORT,
        }
    )


if __name__ == '__main__':
    print('=== PV Steuerbox ===')
    print(f'URL: http://localhost:{config.STEUERBOX_PORT}')

    if config.STEUERBOX_PORT == config.WEB_API_PORT:
        print('FEHLER: Steuerbox-Port darf nicht WEB_API_PORT entsprechen.')
        raise SystemExit(1)

    if not _check_port_available(config.STEUERBOX_HOST, config.STEUERBOX_PORT):
        print(f'FEHLER: Port {config.STEUERBOX_PORT} ist bereits belegt.')
        raise SystemExit(1)

    app.run(
        host=config.STEUERBOX_HOST,
        port=config.STEUERBOX_PORT,
        debug=False,
        threaded=True,
        use_reloader=False,
    )
