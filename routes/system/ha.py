"""Home-Assistant-Lesepfade des system-Blueprints.

Stellt kompakte, read-only JSON-Endpunkte unter /api/ha/* bereit
(Flow, Wattpilot, Automation, Device-/Entitäts-Discovery).
"""
import json
import logging
import sqlite3
import time
from datetime import datetime

from flask import jsonify, request

import config
from host_role import is_failover
from routes.helpers import get_db_connection
from routes.system import bp
from routes.system._shared import _read_wattpilot_db_summary

_ha_cache = {
    'wattpilot': {'ts': 0, 'data': None},
    'flow': {'ts': 0, 'data': None},
    'automation': {'ts': 0, 'data': None},
}


def _read_ha_flow_payload(now: float) -> dict:
    """Kompakte HA-Flow-Daten aus raw_data + Neben-Tabellen lesen."""
    conn = get_db_connection()
    if not conn:
        raise RuntimeError('DB nicht verfügbar')

    try:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM raw_data ORDER BY ts DESC LIMIT 1")
        row = c.fetchone()
        if not row:
            raise RuntimeError('Keine aktuellen raw_data vorhanden')

        latest = dict(row)
        ts = float(latest.get('ts', 0) or 0)
        if now - ts > 120:
            raise RuntimeError('raw_data zu alt')

        wattpilot_power = 0
        c.execute(
            """
            SELECT power_w, car_state FROM wattpilot_readings
            WHERE ts > ?
            ORDER BY ts DESC LIMIT 6
            """,
            (now - 180,),
        )
        wattpilot_rows = c.fetchall()
        if wattpilot_rows:
            for pw, car in wattpilot_rows:
                if car == 2 and (pw or 0) > 0:
                    wattpilot_power = round(pw, 0)
                    break
            if wattpilot_power == 0:
                pw0 = wattpilot_rows[0][0]
                if pw0 is not None:
                    wattpilot_power = round(pw0, 0)

        heizpatrone_power = 0
        klima_power = 0
        c.execute(
            """
            SELECT device_id, power_w FROM fritzdect_readings
            WHERE ts > ?
            ORDER BY ts DESC LIMIT 10
            """,
            (now - 60,),
        )
        for device_id, pw in c.fetchall():
            if device_id == 'heizpatrone':
                heizpatrone_power = max(0, round(pw or 0, 1))
            elif device_id == 'klimaanlage':
                klima_power = max(0, round(pw or 0, 1))
    finally:
        conn.close()

    p_dc1 = latest.get('P_DC1', 0) or 0
    p_dc2 = latest.get('P_DC2', 0) or 0
    p_f2 = latest.get('P_F2', 0) or 0
    p_f3 = latest.get('P_F3', 0) or 0
    p_netz = latest.get('P_Netz', 0) or 0
    i_batt = latest.get('I_Batt_API', 0) or 0
    u_batt = latest.get('U_Batt_API', 0) or 0
    soc_batt = latest.get('SOC_Batt', 0) or 0
    p_wp = latest.get('P_WP', 0) or 0

    f1 = round(p_dc1 + p_dc2, 0)
    f2 = round(p_f2, 0)
    f3 = round(p_f3, 0)
    pv_total_w = round(f1 + f2 + f3, 0)
    battery_power_w = round(i_batt * u_batt, 0)
    grid_power_w = round(p_netz, 0)
    total_consumption_w = round(pv_total_w - battery_power_w + grid_power_w, 0)
    heatpump_w = max(0, round(-p_wp, 0))
    wattpilot_w = max(0, wattpilot_power)
    household_w = max(0, round(total_consumption_w - wattpilot_w - heatpump_w - heizpatrone_power - klima_power, 0))

    return {
        'source': 'db',
        'timestamp': datetime.now().isoformat(),
        'last_update_ts': ts,
        'age_s': round(now - ts),
        'pv_total_w': pv_total_w,
        'grid_power_w': grid_power_w,
        'battery_power_w': battery_power_w,
        'battery_soc_pct': round(soc_batt, 1),
        'consumption_total_w': total_consumption_w,
        'household_w': household_w,
        'wattpilot_w': wattpilot_w,
        'heatpump_w': heatpump_w,
        'heizpatrone_w': heizpatrone_power,
        'klima_w': klima_power,
    }


def _read_obs_state_compact() -> dict:
    """Liest kompakten ObsState-Snapshot aus der RAM-DB."""
    try:
        conn = sqlite3.connect('/dev/shm/automation_obs.db', timeout=2.0)
        row = conn.execute("SELECT state_json FROM obs_state WHERE id=1").fetchone()
        conn.close()
    except Exception:
        return {}

    if not row or not row[0]:
        return {}
    try:
        return json.loads(row[0])
    except Exception:
        return {}


def _build_ha_device_info() -> dict:
    role = 'failover' if is_failover() else 'primary'
    return {
        'identifier': f'pv_system_{role}',
        'name': 'PV-System Erlau',
        'manufacturer': 'PV-System',
        'model': 'GEN24 Orchestrator',
        'sw_version': 'unreleased',
        'role': role,
    }


def _read_ha_automation_payload(now: float) -> dict:
    """HA-freundlicher Status für SOC-/Intent-Kooperation."""
    try:
        from automation.engine.operator_intents import read_active_afternoon_charge_intent

        intent = read_active_afternoon_charge_intent(force_refresh=True)
    except Exception:
        intent = None

    obs = _read_obs_state_compact()
    payload = {
        'source': 'automation_obs',
        'timestamp': datetime.now().isoformat(),
        'device': _build_ha_device_info(),
        'battery_soc_pct': obs.get('batt_soc_pct'),
        'soc_min_pct': obs.get('soc_min'),
        'soc_max_pct': obs.get('soc_max'),
        'soc_mode': obs.get('soc_mode'),
        'forecast_rest_kwh': obs.get('forecast_rest_kwh'),
        'sunset_h': obs.get('sunset'),
        'heizpatrone_aktiv': bool(obs.get('heizpatrone_aktiv', False)),
        'afternoon_charge_active': bool(intent),
        'afternoon_charge_target_soc_pct': None,
        'afternoon_charge_pause_hp': None,
        'afternoon_charge_remaining_s': 0,
        'afternoon_charge_until_h': None,
    }

    if intent:
        payload['afternoon_charge_target_soc_pct'] = int(intent.get('target_soc_pct', 100))
        payload['afternoon_charge_pause_hp'] = bool(intent.get('pause_hp_until_target', False))
        payload['afternoon_charge_remaining_s'] = int(intent.get('respekt_remaining_s', 0))
        payload['afternoon_charge_until_h'] = intent.get('until_hour')

    return payload


@bp.route('/api/ha')
def ha_index():
    """Discovery-Index für Home-Assistant-Lesepfade."""
    return jsonify({
        'name': 'pv-system ha export',
        'version': 1,
        'timestamp': datetime.now().isoformat(),
        'endpoints': [
            {
                'path': '/api/ha/wattpilot',
                'poll_seconds': 15,
                'source': 'db',
                'description': 'Kompakter Wattpilot-Status für HA',
            },
            {
                'path': '/api/ha/flow',
                'poll_seconds': 15,
                'source': 'db',
                'description': 'Kompakte Flow-/Verbrauchsdaten für HA',
            },
            {
                'path': '/api/ha/automation',
                'poll_seconds': 10,
                'source': 'automation_obs',
                'description': 'SOC-/Intent-Status für HA-Automation',
            },
            {
                'path': '/api/ha/device',
                'poll_seconds': 300,
                'source': 'static',
                'description': 'Geräte-Metadaten für HA Device-Mapping',
            },
            {
                'path': '/api/ha/entities',
                'poll_seconds': 300,
                'source': 'static',
                'description': 'Entitätskatalog inkl. JSON-Keys und Schreibaktionen',
            },
        ],
    })


@bp.route('/api/ha/device')
def ha_device_info():
    """Geräte-Metadaten für die Zuordnung von Entitäten in HA."""
    return jsonify({
        'device': _build_ha_device_info(),
        'timestamp': datetime.now().isoformat(),
    })


@bp.route('/api/ha/automation')
def ha_automation_status():
    """HA-freundlicher Status für Intent-/SOC-Kooperation."""
    now = time.time()
    cache = _ha_cache['automation']
    if cache['data'] and (now - cache['ts']) < 10:
        return jsonify(cache['data'])

    payload = _read_ha_automation_payload(now)
    cache['data'] = payload
    cache['ts'] = now
    return jsonify(payload)


@bp.route('/api/ha/entities')
def ha_entities_catalog():
    """Maschinenlesbarer Entitätskatalog für eine einfache HA-Anbindung."""
    base_url = request.host_url.rstrip('/')
    steuerbox_url = f'http://{request.host.split(":")[0]}:{config.STEUERBOX_PORT}'
    payload = {
        'name': 'pv-system ha entities',
        'version': 1,
        'timestamp': datetime.now().isoformat(),
        'device': _build_ha_device_info(),
        'endpoints': {
            'flow': f'{base_url}/api/ha/flow',
            'wattpilot': f'{base_url}/api/ha/wattpilot',
            'automation': f'{base_url}/api/ha/automation',
        },
        'entities': [
            {'key': 'pv_total_w', 'source': '/api/ha/flow', 'unit': 'W', 'suggested_entity': 'sensor.pv_system_pv_total_w'},
            {'key': 'grid_power_w', 'source': '/api/ha/flow', 'unit': 'W', 'suggested_entity': 'sensor.pv_system_grid_power_w'},
            {'key': 'battery_soc_pct', 'source': '/api/ha/flow', 'unit': '%', 'suggested_entity': 'sensor.pv_system_battery_soc_pct'},
            {'key': 'household_w', 'source': '/api/ha/flow', 'unit': 'W', 'suggested_entity': 'sensor.pv_system_household_w'},
            {'key': 'wattpilot_w', 'source': '/api/ha/flow', 'unit': 'W', 'suggested_entity': 'sensor.pv_system_wattpilot_w'},
            {'key': 'charging', 'source': '/api/ha/wattpilot', 'unit': 'bool', 'suggested_entity': 'binary_sensor.pv_system_wattpilot_charging'},
            {'key': 'power_w', 'source': '/api/ha/wattpilot', 'unit': 'W', 'suggested_entity': 'sensor.pv_system_wattpilot_power_w'},
            {'key': 'soc_max_pct', 'source': '/api/ha/automation', 'unit': '%', 'suggested_entity': 'sensor.pv_system_soc_max_pct'},
            {'key': 'afternoon_charge_active', 'source': '/api/ha/automation', 'unit': 'bool', 'suggested_entity': 'binary_sensor.pv_system_afternoon_charge_active'},
            {'key': 'afternoon_charge_remaining_s', 'source': '/api/ha/automation', 'unit': 's', 'suggested_entity': 'sensor.pv_system_afternoon_charge_remaining_s'},
        ],
        'write_actions': [
            {
                'name': 'afternoon_charge_request',
                'method': 'POST',
                'url': f'{steuerbox_url}/api/ops/intent',
                'json': {
                    'action': 'afternoon_charge_request',
                    'params': {
                        'target_soc_pct': 100,
                        'pause_hp_until_target': False,
                        'start_earliest_h': 12.0,
                        'start_latest_h': 15.0,
                    },
                },
            },
        ],
    }
    return jsonify(payload)


@bp.route('/api/ha/wattpilot')
def ha_wattpilot_status():
    """HA-freundlicher, flacher Wattpilot-Status aus lokaler DB."""
    now = time.time()
    cache = _ha_cache['wattpilot']
    if cache['data'] and (now - cache['ts']) < 15:
        return jsonify(cache['data'])

    try:
        summary = _read_wattpilot_db_summary(now)
        payload = {
            'online': summary['online'],
            'stale': summary['age_s'] > 180,
            'age_s': summary['age_s'],
            'last_update_ts': summary['last_update_ts'],
            'charging': summary['charging'],
            'power_w': summary['power_w'],
            'car_state': summary['car_state'],
            'car_state_text': summary['car_state_text'],
            'energy_total_kwh': summary['energy_total_kwh'],
            'energy_session_kwh': summary['energy_session_kwh'],
            'temperature_c': summary['temperature_c'],
            'phase_mode_raw': summary['phase_mode_raw'],
            'phase_mode_text': summary['phase_mode'],
            'amp': summary['amp'],
            'trx': summary['trx'],
            'lmo': summary['lmo'],
            'frc': summary['frc'],
            'source': 'db',
            'timestamp': summary['timestamp'],
        }
        cache['data'] = payload
        cache['ts'] = now
        return jsonify(payload)
    except Exception as e:
        logging.warning(f"HA Wattpilot-Status nicht verfügbar: {e}")
        if cache['data']:
            return jsonify(cache['data'])
        return jsonify({'online': False, 'error_message': str(e), 'timestamp': datetime.now().isoformat()})


@bp.route('/api/ha/flow')
def ha_flow_status():
    """HA-freundliche, flache Flow-Daten aus lokaler DB."""
    now = time.time()
    cache = _ha_cache['flow']
    if cache['data'] and (now - cache['ts']) < 15:
        return jsonify(cache['data'])

    try:
        payload = _read_ha_flow_payload(now)
        cache['data'] = payload
        cache['ts'] = now
        return jsonify(payload)
    except Exception as e:
        logging.warning(f"HA Flow-Status nicht verfügbar: {e}")
        if cache['data']:
            return jsonify(cache['data'])
        return jsonify({'error_message': str(e), 'timestamp': datetime.now().isoformat()})
