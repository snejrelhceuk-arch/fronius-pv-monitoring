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


def _expect_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        norm = value.strip().lower()
        if norm in {'1', 'true', 'yes', 'on'}:
            return True
        if norm in {'0', 'false', 'no', 'off'}:
            return False
    raise ValueError(f'{field} must be bool')


def validate_action(action: str, params: dict[str, Any], respekt_s: int) -> dict[str, Any]:
    """Validiert Aktion + Parameter inkl. Hard Guards.

    Gibt normalisierte Parameter zur weiteren Verarbeitung zurueck.
    """
    if action not in config.STEUERBOX_ALLOWED_ACTIONS:
        abort(403, description=f'action not allowed: {action}')

    max_respekt_s = config.STEUERBOX_MAX_RESPEKT_S
    if action == 'afternoon_charge_request':
        max_respekt_s = config.STEUERBOX_AFTERNOON_MAX_RESPEKT_S

    if respekt_s < config.STEUERBOX_MIN_RESPEKT_S or respekt_s > max_respekt_s:
        abort(422, description='respekt_s out of range')

    normalized: dict[str, Any] = {}

    if action == 'wp_mode':
        normalized['mode'] = _expect_in(params.get('mode'), 'mode', {'max', 'std', 'min', 'neutral'})

    elif action == 'battery_mode':
        normalized['mode'] = _expect_in(params.get('mode'), 'mode', {'komfort', 'auto'})

    elif action == 'afternoon_charge_request':
        target_soc_pct = params.get('target_soc_pct', 100)
        if not isinstance(target_soc_pct, (int, float)):
            abort(422, description='target_soc_pct invalid')

        target_soc = int(target_soc_pct)
        if target_soc < config.STEUERBOX_AFTERNOON_MIN_TARGET_SOC_PCT:
            abort(422, description='target_soc_pct below afternoon minimum')
        if target_soc > config.STEUERBOX_SOC_MAX_PCT:
            abort(422, description='target_soc_pct above hard guard')

        pause_hp = params.get('pause_hp_until_target', True)
        try:
            pause_hp_norm = _expect_bool(pause_hp, 'pause_hp_until_target')
        except ValueError as exc:
            abort(422, description=str(exc))

        start_earliest_h = params.get('start_earliest_h', 12.0)
        start_latest_h = params.get('start_latest_h', 15.0)
        if not isinstance(start_earliest_h, (int, float)):
            abort(422, description='start_earliest_h invalid')
        if not isinstance(start_latest_h, (int, float)):
            abort(422, description='start_latest_h invalid')

        start_earliest = float(start_earliest_h)
        start_latest = float(start_latest_h)
        if not (0.0 <= start_earliest <= 24.0):
            abort(422, description='start_earliest_h out of range')
        if not (0.0 <= start_latest <= 24.0):
            abort(422, description='start_latest_h out of range')
        if start_earliest > start_latest:
            abort(422, description='start_earliest_h must be <= start_latest_h')

        normalized['target_soc_pct'] = target_soc
        normalized['pause_hp_until_target'] = pause_hp_norm
        normalized['start_earliest_h'] = round(start_earliest, 2)
        normalized['start_latest_h'] = round(start_latest, 2)

        until_hour = params.get('until_hour')
        if until_hour is not None:
            if not isinstance(until_hour, (int, float)):
                abort(422, description='until_hour invalid')
            until_hour_f = float(until_hour)
            if not (0.0 <= until_hour_f <= 24.0):
                abort(422, description='until_hour out of range')
            normalized['until_hour'] = round(until_hour_f, 2)

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
