"""
collector.attachment_state — Versions-Snapshot + Anknuepfungs-Validierung.

Trigger: Wenn sich Inverter/SmartMeter-Versions-Snapshot zwischen zwei
Polls aendert, wird eine Vollpruefung aller dokumentierten Modbus-,
SunSpec-, Solar-API- und internen-API-Anknuepfungspunkte ausgeloest +
Discovery-Scan + Persistenz.

Persistente Datei: config/fronius_attachment_state.json
"""

import json
import logging
import os
import threading
import time

import requests

import config
import modbus_quellen

from .modbus_client import read_registers_safe
from .sunspec import extract_device_data, read_device_data

ATTACHMENT_STATE_FILE = os.path.join(config.BASE_DIR, 'config', 'fronius_attachment_state.json')
FRONIUS_API_BASE = config.FRONIUS_API_BASE
IP_ADDRESS = modbus_quellen.IP_ADDRESS

attachment_state = {}
attachment_state_lock = threading.Lock()

# Gedrosselter Save: attachment_state alle 60s persistieren (nicht bei jedem 3s-Poll)
_last_attachment_save_ts = 0
_ATTACHMENT_SAVE_INTERVAL = 60


def load_attachment_state():
    """Lade persistierten Versions-/Anknuepfungszustand."""
    global attachment_state
    try:
        if os.path.exists(ATTACHMENT_STATE_FILE):
            with open(ATTACHMENT_STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    with attachment_state_lock:
                        attachment_state = data
                    return
    except Exception as e:
        logging.warning(f"Attachment-State laden fehlgeschlagen: {e}")

    with attachment_state_lock:
        attachment_state = {}


def save_attachment_state():
    """Speichere Versions-/Anknuepfungszustand atomar."""
    try:
        with attachment_state_lock:
            data = dict(attachment_state)

        tmp = f"{ATTACHMENT_STATE_FILE}.tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=True, indent=2, sort_keys=True)
        os.replace(tmp, ATTACHMENT_STATE_FILE)
    except Exception as e:
        logging.warning(f"Attachment-State speichern fehlgeschlagen: {e}")


def update_poll_success():
    """Merke letzten erfolgreichen Poll-Zeitpunkt (in-memory, Save gedrosselt)."""
    global _last_attachment_save_ts
    now = int(time.time())
    with attachment_state_lock:
        attachment_state['last_successful_poll_ts'] = now
        attachment_state['consecutive_errors'] = 0
    if now - _last_attachment_save_ts >= _ATTACHMENT_SAVE_INTERVAL:
        save_attachment_state()
        _last_attachment_save_ts = now


def update_poll_error():
    """Inkrementiere Fehlerzaehler (in-memory, Save nur bei Schwelle)."""
    with attachment_state_lock:
        prev = attachment_state.get('consecutive_errors', 0)
        attachment_state['consecutive_errors'] = prev + 1
    # Sofort persistieren bei erster Fehlerstraehne (>= 3)
    if prev + 1 == 3:
        save_attachment_state()


def update_reconnect_event(trigger: str, success: bool):
    """Persistiere Reconnect-Event sofort (selten, wichtig)."""
    now = int(time.time())
    with attachment_state_lock:
        attachment_state['last_reconnect_event'] = {
            'ts': now,
            'trigger': trigger,
            'success': success,
        }
    save_attachment_state()


def _safe_common_value(devices, key, field):
    try:
        return devices.get(key, {}).get('common', {}).get(field, {}).get('value')
    except Exception:
        return None


def _build_version_snapshot(devices):
    """Erzeuge kompakten Versions-Snapshot aus SunSpec Model 1."""
    return {
        'inverter_vr': _safe_common_value(devices, 'inverter', 'Vr'),
        'inverter_sn': _safe_common_value(devices, 'inverter', 'SN'),
        'prim_sm_vr': _safe_common_value(devices, 'prim_sm', 'Vr'),
        'prim_sm_sn': _safe_common_value(devices, 'prim_sm', 'SN'),
        'sec_sm_f2_vr': _safe_common_value(devices, 'sec_sm_F2', 'Vr'),
        'sec_sm_f2_sn': _safe_common_value(devices, 'sec_sm_F2', 'SN'),
        'sec_sm_wp_vr': _safe_common_value(devices, 'sec_sm_WP', 'Vr'),
        'sec_sm_wp_sn': _safe_common_value(devices, 'sec_sm_WP', 'SN'),
        'sec_sm_f3_vr': _safe_common_value(devices, 'sec_sm_F3', 'Vr'),
        'sec_sm_f3_sn': _safe_common_value(devices, 'sec_sm_F3', 'SN'),
    }


def _collect_models_for_unit(client, unit_id):
    models = read_device_data(client, unit_id, skip_model_ids=[])
    return [m.id for m in (models or [])]


def _discover_sunspec_units(client, max_unit=10):
    """Suche SunSpec-Geraete in kleinem Unit-ID-Bereich (nur bei Versionswechsel)."""
    found = []
    for unit in range(1, max_unit + 1):
        hdr = read_registers_safe(client, 40000, 2, unit)
        if not hdr or hdr[0] != 0x5375 or hdr[1] != 0x6e53:
            continue
        models = read_device_data(client, unit, skip_model_ids=[])
        common = extract_device_data(models or []).get('common', {})
        found.append({
            'unit': unit,
            'models': [m.id for m in (models or [])],
            'device': common.get('Md', {}).get('value'),
            'serial': common.get('SN', {}).get('value'),
            'version': common.get('Vr', {}).get('value'),
        })
    return found


def _validate_all_attachment_points(client):
    """Feste Vollpruefung aller dokumentierten API-/Register-Anknuepfungen."""
    result = {
        'timestamp': int(time.time()),
        'modbus': {},
        'solar_api': {},
        'internal_api': {},
        'discovery': [],
    }

    modbus_points = [
        ('inverter', modbus_quellen.INVERTER, [1, 103, 124, 160]),
        ('prim_sm_f1', modbus_quellen.PRIM_SM_F1, [1, 203]),
        ('sec_sm_f2', modbus_quellen.SEC_SM_F2, [1, 203]),
        ('sec_sm_wp', modbus_quellen.SEC_SM_WP, [1, 203]),
        ('sec_sm_f3', modbus_quellen.SEC_SM_F3, [1, 203]),
    ]

    for name, unit, expected in modbus_points:
        t0 = time.time()
        hdr = read_registers_safe(client, 40000, 2, unit)
        hdr_ok = bool(hdr and hdr[0] == 0x5375 and hdr[1] == 0x6e53)
        models = _collect_models_for_unit(client, unit) if hdr_ok else []
        missing_expected = [m for m in expected if m not in models]
        result['modbus'][name] = {
            'unit': unit,
            'header_ok': hdr_ok,
            'models': models,
            'missing_expected_models': missing_expected,
            'ok': hdr_ok and not missing_expected,
            'duration_ms': int((time.time() - t0) * 1000),
        }

    solar_eps = [
        '/GetPowerFlowRealtimeData.fcgi',
        '/GetInverterRealtimeData.cgi?Scope=System',
        '/GetMeterRealtimeData.cgi?Scope=System',
        '/GetStorageRealtimeData.cgi?Scope=System',
    ]
    for ep in solar_eps:
        t0 = time.time()
        try:
            r = requests.get(f'{FRONIUS_API_BASE}{ep}', timeout=4)
            result['solar_api'][ep] = {
                'status': r.status_code,
                'ok': r.status_code == 200,
                'duration_ms': int((time.time() - t0) * 1000),
            }
        except Exception as e:
            result['solar_api'][ep] = {
                'status': None,
                'ok': False,
                'error': str(e),
                'duration_ms': int((time.time() - t0) * 1000),
            }

    internal_eps = [
        ('/status/common', 200),
        ('/api/config/batteries', 401),
        ('/api/config/common', 401),
    ]
    for ep, expected_status in internal_eps:
        t0 = time.time()
        try:
            r = requests.get(f'http://{IP_ADDRESS}{ep}', timeout=4)
            has_x_auth = 'X-WWW-Authenticate' in r.headers
            ok = (r.status_code == expected_status)
            if expected_status == 401:
                ok = ok and has_x_auth
            result['internal_api'][ep] = {
                'status': r.status_code,
                'expected_status': expected_status,
                'has_x_www_auth': has_x_auth,
                'ok': ok,
                'duration_ms': int((time.time() - t0) * 1000),
            }
        except Exception as e:
            result['internal_api'][ep] = {
                'status': None,
                'expected_status': expected_status,
                'has_x_www_auth': False,
                'ok': False,
                'error': str(e),
                'duration_ms': int((time.time() - t0) * 1000),
            }

    result['discovery'] = _discover_sunspec_units(client, max_unit=10)
    return result


def version_change_check_and_revalidate(client, devices):
    """Trigger: Versionsaenderung erkannt -> Vollpruefung + Discovery + Persistenz."""
    snapshot = _build_version_snapshot(devices)
    now = int(time.time())

    with attachment_state_lock:
        prev_snapshot = attachment_state.get('version_snapshot')

    if not snapshot.get('inverter_vr'):
        return

    # Erstinitialisierung: Snapshot speichern, keine schwere Vollpruefung erzwingen.
    if prev_snapshot is None:
        with attachment_state_lock:
            attachment_state['version_snapshot'] = snapshot
            attachment_state['last_seen_ts'] = now
            attachment_state['initialized_ts'] = now
        save_attachment_state()
        logging.info('Attachment-State initialisiert (kein Versionsvergleich moeglich)')
        return

    if snapshot == prev_snapshot:
        with attachment_state_lock:
            attachment_state['last_seen_ts'] = now
        return

    logging.warning('Versionsaenderung erkannt -> starte Vollpruefung aller Anknuepfungspunkte')
    validation = _validate_all_attachment_points(client)

    with attachment_state_lock:
        attachment_state['previous_version_snapshot'] = prev_snapshot
        attachment_state['version_snapshot'] = snapshot
        attachment_state['last_seen_ts'] = now
        attachment_state['last_version_change_ts'] = now
        attachment_state['last_validation'] = validation

    save_attachment_state()
    logging.warning('Vollpruefung nach Versionsaenderung abgeschlossen und gespeichert')
