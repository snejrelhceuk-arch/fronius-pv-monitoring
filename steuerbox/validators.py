"""Validatoren fuer die Steuerbox (Schicht E)."""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Any

from flask import abort, request

import config


def check_allowlist() -> None:
    """Prueft die Client-IP gegen die CIDR-Allowlist."""
    remote_addr = (request.remote_addr or '').strip()
    if not remote_addr:
        abort(403, description='missing client ip')

    try:
        client_ip = ip_address(remote_addr)
    except ValueError:
        abort(403, description='invalid client ip')

    for entry in config.STEUERBOX_ALLOWLIST:
        try:
            if client_ip in ip_network(entry, strict=False):
                return
        except ValueError:
            continue

    abort(403, description='ip not allowed')


# Token-Auth entfernt: Authentifizierung erfolgt via mTLS (nginx Reverse Proxy).


def _expect_in(value: Any, field: str, allowed: set[str]) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{field} must be string')
    normalized = value.strip().lower()
    if normalized not in allowed:
        raise ValueError(f'{field} invalid: {normalized}')
    return normalized


def validate_action(action: str, params: dict[str, Any], respekt_s: int) -> dict[str, Any]:
    """Validiert Aktion + Parameter inkl. Hard Guards.

    Gibt normalisierte Parameter zur weiteren Verarbeitung zurueck.
    """
    if action not in config.STEUERBOX_ALLOWED_ACTIONS:
        abort(403, description=f'action not allowed: {action}')

    if respekt_s < config.STEUERBOX_MIN_RESPEKT_S or respekt_s > config.STEUERBOX_MAX_RESPEKT_S:
        abort(422, description='respekt_s out of range')

    normalized: dict[str, Any] = {}

    if action == 'wp_mode':
        normalized['mode'] = _expect_in(params.get('mode'), 'mode', {'max', 'std', 'min', 'neutral'})

    elif action == 'battery_mode':
        normalized['mode'] = _expect_in(params.get('mode'), 'mode', {'komfort', 'auto'})

    elif action in {'hp_toggle', 'klima_toggle', 'lueftung_toggle'}:
        state = _expect_in(params.get('state'), 'state', {'on', 'off', 'neutral'})
        normalized['state'] = state

        # Hard Guard: Heizpatrone darf nicht EIN bei kritischem SOC/Uebertemperatur.
        if action == 'hp_toggle' and state == 'on':
            soc_pct = params.get('soc_pct')
            uebertemp_c = params.get('uebertemp_c')
            if isinstance(soc_pct, (int, float)) and soc_pct <= config.STEUERBOX_HP_NOTAUS_SOC_PCT:
                abort(422, description='hp blocked: soc too low')
            if isinstance(uebertemp_c, (int, float)) and uebertemp_c >= config.STEUERBOX_HP_UEBERTEMP_C:
                abort(422, description='hp blocked: overtemperature')

    elif action == 'wattpilot_mode':
        normalized['mode'] = _expect_in(params.get('mode'), 'mode', {'eco', 'default', 'neutral'})

    elif action == 'wattpilot_start_stop':
        normalized['command'] = _expect_in(params.get('command'), 'command', {'start', 'stop', 'neutral'})

    elif action == 'wattpilot_amp':
        amp = params.get('amp')
        if isinstance(amp, str) and amp.lower().strip() == 'neutral':
            normalized['amp'] = 'neutral'
        elif amp in (8, 24):
            normalized['amp'] = int(amp)
        else:
            abort(422, description='amp must be 8, 24 or neutral')

    # Optionale Guard-Parameter fuer SOC/WP (falls in Zukunft mitgeschickt)
    if 'soc_min_pct' in params:
        val = params.get('soc_min_pct')
        if not isinstance(val, (int, float)) or val < config.STEUERBOX_SOC_MIN_PCT:
            abort(422, description='soc_min_pct below hard guard')
    if 'soc_max_pct' in params:
        val = params.get('soc_max_pct')
        if not isinstance(val, (int, float)) or val > config.STEUERBOX_SOC_MAX_PCT:
            abort(422, description='soc_max_pct above hard guard')
    if 'wp_offset_k' in params:
        val = params.get('wp_offset_k')
        if not isinstance(val, (int, float)) or val < config.STEUERBOX_WP_OFFSET_MIN_K:
            abort(422, description='wp_offset_k below hard guard')

    return normalized
