"""
Blueprint: System-Status-APIs.

Enthält: /api/battery_status, /api/flow_status, /api/system_info,
         /api/wattpilot/status, /api/wattpilot/history,
         /api/failover_status, /api/backup_status
"""
import sqlite3
import logging
import os
import time
from pathlib import Path
from datetime import datetime
from flask import Blueprint, jsonify, request
import config
from routes.helpers import get_db_connection, get_fronius_api, battery_cache, wattpilot_cache

bp = Blueprint('system', __name__)

# ── Failover-Status Cache (30 s) ──────────────────────────────
_failover_cache = {'ts': 0, 'result': None}
_FAILOVER_CACHE_TTL = 60  # Sekunden (max. 1 SSH-Aufruf pro Minute)
_backup_cache = {'ts': 0, 'result': None}
_BACKUP_CACHE_TTL = 600  # Sekunden (10 Minuten)

# Fritz!DECT Live-Status Cache (eigener, längerer TTL als battery_cache)
_fritzdect_cache = {'ts': 0, 'data': None}
_FRITZDECT_CACHE_TTL = 120  # 2 Minuten (Fritz!Box ist langsam, 1 Bulk-Request ~2s)
_flow_cache = {'ts': 0, 'data': None}


def _build_battery_status_result(now, api):
    """Batterienahe Live-Daten für kompakte UI-Widgets."""
    result = _fetch_fronius_base(api)
    _fetch_battery_energy(now, result)
    _fetch_bms_counters(now, result)
    _fetch_soh(result)
    return result


def _build_flow_status_result(now, api):
    """Flow-/Dashboard-Daten: Batterie plus Automation, Verbraucher und Temperaturen."""
    result = _build_battery_status_result(now, api)
    _fetch_automation_state(now, result)
    _fetch_last_soc_switch(result)
    _fetch_temperatures(result)
    _fetch_hp_status(now, result)
    _fetch_wp_status(result)
    return result


@bp.route('/api/battery_status')
def api_battery_status():
    """
    Batterienahe Live-Daten vom Fronius GEN24.

    Liefert nur Batteriefelder und batteriebezogene Kennzahlen,
    z.B. SOC_MIN/SOC_MAX, aktueller SOC, Lade-/Entladeenergie, SOH,
    SunSpec-Status und BMS-Kennzahlen.
    """
    now = time.time()

    # Cache prüfen (60s gültig)
    if battery_cache['data'] and (now - battery_cache['ts']) < 60:
        return jsonify(battery_cache['data'])

    try:
        api = get_fronius_api()
        if not api:
            return jsonify({"error": "FroniusAPI nicht verfügbar"}), 503

        result = _build_battery_status_result(now, api)

        battery_cache['data'] = result
        battery_cache['ts'] = now
        return jsonify(result)
    except Exception as e:
        logging.error(f"Battery Status Fehler: {e}")
        if battery_cache['data']:
            return jsonify(battery_cache['data'])
        return jsonify({"error": str(e)}), 500


@bp.route('/api/flow_status')
def api_flow_status():
    """Flow-/Dashboard-Payload: Batterie, Automation, Temperaturen und Verbraucher."""
    now = time.time()

    if _flow_cache['data'] and (now - _flow_cache['ts']) < 60:
        return jsonify(_flow_cache['data'])

    try:
        api = get_fronius_api()
        if not api:
            return jsonify({"error": "FroniusAPI nicht verfügbar"}), 503

        result = _build_flow_status_result(now, api)
        _flow_cache['data'] = result
        _flow_cache['ts'] = now
        return jsonify(result)
    except Exception as e:
        logging.error(f"Flow Status Fehler: {e}")
        if _flow_cache['data']:
            return jsonify(_flow_cache['data'])
        return jsonify({"error": str(e)}), 500


# ── Hilfsfunktionen für api_battery_status / api_flow_status ─────────────────────

# SunSpec Model 124 StorCtl_Mod + ChaSt Bezeichner
STORCTL_LABELS = {
    0: 'Automatik',
    1: 'Ladebegrenzung',
    2: 'Entladebegrenzung',
    3: 'Lade+Entladebegrenzung',
}
CHAST_LABELS = {
    1: 'Deaktiviert', 2: 'Leer', 3: 'Entladen',
    4: 'Laden', 5: 'Voll', 6: 'Bereitschaft', 7: 'Selbsttest',
}


def _fetch_fronius_base(api):
    """Basis-Werte vom Fronius GEN24 (SOC_MIN/MAX, Modus etc.) + Modbus-Register."""
    values = api.get_values()
    result = {
        'soc_min': values.get('BAT_M0_SOC_MIN'),
        'soc_max': values.get('BAT_M0_SOC_MAX'),
        'soc_mode': values.get('BAT_M0_SOC_MODE'),
        'grid_charge': values.get('HYB_EVU_CHARGEFROMGRID'),
        'ac_charge': values.get('HYB_BM_CHARGEFROMAC'),
        'pac_min': values.get('HYB_BM_PACMIN'),
        'backup_critical_soc': values.get('HYB_BACKUP_CRITICALSOC'),
        'backup_reserved': values.get('HYB_BACKUP_RESERVED'),
        'em_mode': values.get('HYB_EM_MODE'),
        'batt_energy_method': 'integration_ui_with_counter_fallback',
    }

    # StorCtl_Mod + ChaSt aus ObsState (RAM-DB, aktuell)
    try:
        import json as _json_obs
        _obs_db = '/dev/shm/automation_obs.db'
        with sqlite3.connect(_obs_db) as _odb:
            _orow = _odb.execute('SELECT state_json FROM obs_state LIMIT 1').fetchone()
            if _orow:
                _obs = _json_obs.loads(_orow[0])
                storctl = _obs.get('storctl_mod')
                chast = _obs.get('cha_state')
                result['storctl_mod'] = storctl
                result['storctl_mod_text'] = STORCTL_LABELS.get(storctl, f'Unbekannt ({storctl})')
                result['cha_state'] = chast
                result['cha_state_text'] = CHAST_LABELS.get(chast, f'Unbekannt ({chast})')
    except Exception as _oe:
        logging.debug(f"ObsState StorCtl/ChaSt: {_oe}")

    return result


def _fetch_automation_state(now, result):
    """Engine-State aus automation_log: SOC-Switches, Aktionen, Phasen."""
    try:
        import json as _json

        with sqlite3.connect(config.DB_PATH) as _adb:
            _24h_ago = int(now) - 86400

            soc_rows = _adb.execute("""
                SELECT ts, kommando, wert, grund, ergebnis
                FROM automation_log
                WHERE aktor = 'batterie'
                  AND kommando IN ('set_soc_min', 'set_soc_max', 'set_soc_mode')
                  AND ts >= datetime(?, 'unixepoch')
                ORDER BY ts DESC
                LIMIT 20
            """, (_24h_ago,)).fetchall()

            result['soc_switches'] = [{
                'ts': r[0], 'kommando': r[1], 'wert': r[2],
                'grund': (r[3] or '')[:120], 'ergebnis': r[4],
            } for r in soc_rows]

            all_rows = _adb.execute("""
                SELECT ts, kommando, wert, grund, ergebnis
                FROM automation_log
                WHERE aktor = 'batterie'
                  AND ts >= datetime(?, 'unixepoch')
                ORDER BY ts DESC
                LIMIT 50
            """, (_24h_ago,)).fetchall()

            result['engine_aktionen'] = [{
                'ts': r[0], 'kommando': r[1], 'wert': r[2],
                'grund': (r[3] or '')[:120], 'ergebnis': r[4],
            } for r in all_rows]

            last_action = _adb.execute("""
                SELECT ts, kommando, wert, grund, ergebnis
                FROM automation_log
                WHERE aktor = 'batterie'
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            if last_action:
                result['last_engine_action'] = {
                    'ts': last_action[0], 'kommando': last_action[1],
                    'wert': last_action[2],
                    'grund': (last_action[3] or '')[:120],
                    'ergebnis': last_action[4],
                }

        # Engine-Vorausschau
        try:
            from automation.engine.automation_daemon import engine_vorausschau
            result['vorausschau'] = engine_vorausschau()
        except Exception as ev:
            logging.debug(f"Vorausschau nicht verfügbar: {ev}")
            result['vorausschau'] = []

        # Scheduler-State (Phasen-Flags, Legacy-Kompatibilität)
        state_file = Path(__file__).resolve().parent.parent / 'config' / 'battery_scheduler_state.json'
        if state_file.exists():
            with open(state_file, 'r') as f:
                sched_state = _json.load(f)
            result['scheduler'] = {
                'morning_done': sched_state.get('morning_done', False),
                'afternoon_done': sched_state.get('afternoon_done', False),
                'balancing_active': sched_state.get('balancing_active', False),
                'evening_rate_active': sched_state.get('evening_rate_active', False),
                'evening_rate_percent': sched_state.get('evening_rate_percent'),
                'manual_override': sched_state.get('manual_override', False),
                'last_date': sched_state.get('last_date'),
            }

        # Automation-Phasen für Tagesübersicht
        _build_automation_phasen(now, result)

    except Exception as e:
        logging.warning(f"Automation-State nicht lesbar: {e}")


def _build_automation_phasen(now, result):
    """Tages-Phasenübersicht aus automation_log + Defaults."""
    try:
        _persist_db = str(Path(__file__).resolve().parent.parent / 'data.db')
        _auto_rows = []
        try:
            with sqlite3.connect(_persist_db) as _alog_db:
                _auto_rows = _alog_db.execute("""
                    SELECT kommando, wert, grund, ts, ergebnis
                    FROM automation_log
                    WHERE aktor = 'batterie'
                      AND ts >= ?
                      AND ergebnis = 'OK'
                    ORDER BY ts ASC
                """, (time.strftime('%Y-%m-%d', time.localtime(now)),)).fetchall()
        except Exception:
            pass

        _phase_log = {}

        for _r in _auto_rows:
            _cmd, _wert = _r[0], _r[1]
            _grund = (_r[2] or '')[:80]
            _ts_str = _r[3][:16].replace('T', ' ') if _r[3] and len(_r[3]) > 15 else None
            _zeit = _ts_str[11:16] if _ts_str and len(_ts_str) >= 16 else None

            if _cmd == 'set_soc_min' and 'Morgen' in _grund:
                _phase_log['morgen'] = {
                    'zeit': _zeit, 'status': 'done',
                    'aktion': f'SOC_MIN → {_wert}%' if _wert else 'SOC_MIN geöffnet',
                    'grund': _grund, 'manuell': False,
                }
            elif _cmd == 'set_soc_max' and 'Nachmittag' in _grund:
                _phase_log['nachmittag'] = {
                    'zeit': _zeit, 'status': 'done',
                    'aktion': f'SOC_MAX → {_wert}%' if _wert else 'SOC_MAX erhöht',
                    'grund': _grund, 'manuell': False,
                }
            elif _cmd in ('auto',) and 'TAG-Phase' in _grund:
                _phase_log['komfort'] = {
                    'zeit': _zeit, 'status': 'done',
                    'aktion': 'Limits aufgehoben',
                    'grund': _grund, 'manuell': False,
                }
            elif _cmd in ('set_soc_min', 'set_soc_max') and 'Komfort-Reset' in _grund:
                _phase_log['komfort'] = {
                    'zeit': _zeit, 'status': 'done',
                    'aktion': 'Komfort-Reset',
                    'grund': _grund, 'manuell': False,
                }

        # ── Kontextreiche Defaults für fehlende Phasen ──
        # ObsState lesen für aktuelle Werte + Prognose
        _obs_soc_min = result.get('soc_min')
        _obs_soc_max = result.get('soc_max')

        # SOC-Grenz-Zeitpunkte aus letzten Switches rekonstruieren
        _soc_switches = result.get('soc_switches', [])
        _last_soc_min_ts = None
        _last_soc_max_ts = None
        for _sw in _soc_switches:
            if _sw.get('kommando') == 'set_soc_min' and _sw.get('ergebnis') == 'OK' and not _last_soc_min_ts:
                _last_soc_min_ts = _sw.get('ts', '')[:16].replace('T', ' ')
            if _sw.get('kommando') == 'set_soc_max' and _sw.get('ergebnis') == 'OK' and not _last_soc_max_ts:
                _last_soc_max_ts = _sw.get('ts', '')[:16].replace('T', ' ')

        # Nachmittag-Prognose: wann wird SOC_MAX auf 100% gesetzt?
        _nachmittag_prognose = ''
        _sunrise_h = None
        _sunset_h = None
        _clearsky_peak = None
        try:
            import json as _json_nmp
            _obs_db_np = '/dev/shm/automation_obs.db'
            with sqlite3.connect(_obs_db_np) as _odb_np:
                _orow_np = _odb_np.execute('SELECT state_json FROM obs_state LIMIT 1').fetchone()
                if _orow_np:
                    _obs_np = _json_nmp.loads(_orow_np[0])
                    _clearsky_peak = _obs_np.get('clearsky_peak_h')
                    _sunrise_h = _obs_np.get('sunrise')
                    _sunset_h = _obs_np.get('sunset')
                    _forecast_kwh = _obs_np.get('forecast_kwh', 0) or 0
                    if _clearsky_peak and _obs_soc_max and _obs_soc_max < 100:
                        _nachmittag_prognose = f'voraussichtlich ~{int(_clearsky_peak)}:00'
        except Exception:
            pass

        def _h_to_hhmm(h):
            """Dezimalstunde → 'HH:MM' String."""
            if h is None:
                return None
            hh = int(h)
            mm = int((h - hh) * 60)
            return f'{hh:02d}:{mm:02d}'

        if 'morgen' not in _phase_log:
            _morgen_zeit_est = _h_to_hhmm(_sunrise_h - 0.5) if _sunrise_h else None
            if _obs_soc_min is not None and _obs_soc_min <= 5:
                _morgen_grund = f'SOC_MIN = {_obs_soc_min}%'
                if _last_soc_min_ts:
                    _morgen_grund += f' seit {_last_soc_min_ts[5:]}'
                else:
                    _morgen_grund += ' (gestern gesetzt)'
                _morgen_grund += ' — Batterie entleeren vor PV-Übernahme'
                _phase_log['morgen'] = {
                    'status': 'done', 'zeit': _last_soc_min_ts[11:16] if _last_soc_min_ts else None,
                    'aktion': f'SOC_MIN = {_obs_soc_min}%',
                    'grund': _morgen_grund, 'manuell': False,
                }
            elif _obs_soc_min is not None and _obs_soc_min >= 25:
                _phase_log['morgen'] = {
                    'status': 'skipped', 'zeit': None,
                    'aktion': f'SOC_MIN bleibt {_obs_soc_min}%',
                    'grund': 'Batterie reicht über die Nacht, kein Öffnen nötig',
                    'manuell': False,
                }
            else:
                _phase_log['morgen'] = {
                    'status': 'pending', 'zeit': f'~{_morgen_zeit_est}' if _morgen_zeit_est else None,
                    'aktion': 'SOC_MIN → 5%',
                    'grund': 'Wartet auf PV-Übernahme-Prognose', 'manuell': False,
                }

        if 'nachmittag' not in _phase_log:
            _nm_zeit_est = _h_to_hhmm(_clearsky_peak) if _clearsky_peak else None
            if _obs_soc_max is not None and _obs_soc_max >= 100:
                _nm_grund = 'SOC_MAX = 100%'
                if _last_soc_max_ts:
                    _nm_grund += f' seit {_last_soc_max_ts[5:]}'
                _phase_log['nachmittag'] = {
                    'status': 'done', 'zeit': _last_soc_max_ts[11:16] if _last_soc_max_ts else None,
                    'aktion': 'SOC_MAX = 100%',
                    'grund': _nm_grund, 'manuell': False,
                }
            else:
                _nm_aktion = f'SOC_MAX {_obs_soc_max}% → 100%'
                _nm_grund = f'SOC_MAX aktuell {_obs_soc_max}%'
                if _nachmittag_prognose:
                    _nm_grund += f', Öffnung {_nachmittag_prognose}'
                else:
                    _nm_grund += ', wartet auf Clear-Sky-Peak'
                _phase_log['nachmittag'] = {
                    'status': 'pending', 'zeit': f'~{_nm_zeit_est}' if _nm_zeit_est else None,
                    'aktion': _nm_aktion,
                    'grund': _nm_grund, 'manuell': False,
                }

        # Komfort-Grenzen aus battery_control.json
        try:
            import json as _json_cfg
            _cfg_path = Path(__file__).resolve().parent.parent / 'config' / 'battery_control.json'
            with open(_cfg_path, 'r') as _cf:
                _bcfg = _json_cfg.load(_cf)
            _k_min = _bcfg.get('soc_grenzen', {}).get('komfort_min', 25)
            _k_max = _bcfg.get('soc_grenzen', {}).get('komfort_max', 75)
        except Exception:
            _k_min, _k_max = 25, 75

        # Komfort-Phase: Abend + Reset zusammengelegt
        _sunset_zeit = _h_to_hhmm(_sunset_h) if _sunset_h else None
        if 'abend' in _phase_log:
            # Already logged as 'abend' → adopt as 'komfort'
            _phase_log['komfort'] = _phase_log.pop('abend')
        elif 'reset' in _phase_log:
            # Already logged as 'reset' → adopt as 'komfort'
            _phase_log['komfort'] = _phase_log.pop('reset')
        else:
            _phase_log['komfort'] = {
                'status': 'pending',
                'zeit': f'~{_sunset_zeit}' if _sunset_zeit else None,
                'aktion': f'Grenzen → {_k_min}–{_k_max}%',
                'grund': f'Komfort-Modus nach Sonnenuntergang'
                         + (f' (~{_sunset_zeit})' if _sunset_zeit else ''),
                'manuell': False,
            }
        # Remove leftover keys if both existed
        _phase_log.pop('abend', None)
        _phase_log.pop('reset', None)

        result['automation_phasen'] = _phase_log
    except Exception as _pe:
        logging.debug(f"Automation-Phasen: {_pe}")


def _fetch_last_soc_switch(result):
    """Letzte SOC-Umschaltung aus automation_log (Fallback: battery_control_log)."""
    try:
        _persist_db = str(Path(__file__).resolve().parent.parent / 'data.db')
        with sqlite3.connect(_persist_db) as _ldb:
            row = _ldb.execute("""
                SELECT ts, kommando, wert, grund, ergebnis
                FROM automation_log
                WHERE aktor = 'batterie'
                  AND kommando IN ('set_soc_min', 'set_soc_max', 'set_soc_mode')
                ORDER BY id DESC LIMIT 1
            """).fetchone()
            if row:
                result['last_soc_switch'] = {
                    'ts':     row[0][:16].replace('T', ' ') if row[0] else '?',
                    'action': row[1], 'param': row[1],
                    'old': None, 'new': row[2],
                    'reason': (row[3] or '')[:90],
                }
            else:
                row = _ldb.execute("""
                    SELECT ts, action, param, old_value, new_value, reason
                    FROM battery_control_log
                    WHERE action IN (
                        'morning_open', 'afternoon_raise', 'comfort_reset',
                        'comfort_defaults', 'balancing_start', 'evening_limit',
                        'evening_auto', 'manual_set'
                    )
                    ORDER BY ts DESC LIMIT 1
                """).fetchone()
                if row:
                    result['last_soc_switch'] = {
                        'ts':     datetime.fromtimestamp(row[0]).strftime('%d.%m %H:%M'),
                        'action': row[1], 'param': row[2],
                        'old': row[3], 'new': row[4],
                        'reason': (row[5] or '')[:90],
                    }
    except Exception as e:
        logging.debug(f"last_soc_switch query: {e}")


def _fetch_battery_energy(now, result):
    """Tages-Batterieenergie (Ladung/Entladung) + aktueller SOC."""
    try:
        conn_b = get_db_connection()
        if conn_b:
            try:
                cb = conn_b.cursor()
                today_start = int(time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1)))
                cb.execute("""
                    SELECT
                        SUM(
                            CASE
                                WHEN U_Batt_API_avg IS NULL OR I_Batt_API_avg IS NULL
                                THEN COALESCE(W_inBatt, 0)
                                WHEN I_Batt_API_avg >= 0
                                THEN (I_Batt_API_avg * U_Batt_API_avg) / 60.0
                                ELSE 0
                            END
                        ) / 1000.0,
                        SUM(
                            CASE
                                WHEN U_Batt_API_avg IS NULL OR I_Batt_API_avg IS NULL
                                THEN COALESCE(W_outBatt, 0)
                                WHEN I_Batt_API_avg < 0
                                THEN (ABS(I_Batt_API_avg) * U_Batt_API_avg) / 60.0
                                ELSE 0
                            END
                        ) / 1000.0
                    FROM data_1min WHERE ts >= ?
                """, (today_start,))
                erow = cb.fetchone()
                result['batt_charge_kwh'] = round(erow[0] or 0, 2) if erow else 0
                result['batt_discharge_kwh'] = round(erow[1] or 0, 2) if erow else 0

                cb.execute("SELECT SOC_Batt FROM raw_data ORDER BY ts DESC LIMIT 1")
                soc_row = cb.fetchone()
                result['current_soc'] = round(soc_row[0], 1) if soc_row and soc_row[0] is not None else None
            finally:
                conn_b.close()
    except Exception as e:
        logging.warning(f"Batterie-Tageswerte Fehler: {e}")


def _fetch_bms_counters(now, result):
    """BMS Lifetime-Counter + Tages-Fixpunkt-Deltas."""
    try:
        import json as _json_bms
        import requests as _req_bms

        _bms_url = f'http://{config.INVERTER_IP}/components/BatteryManagementSystem/readable'
        _bms_resp = _req_bms.get(_bms_url, timeout=2)
        if _bms_resp.status_code != 200:
            return

        _bms_payload = _bms_resp.json()
        _channels = None
        _bms_data = _bms_payload.get('Body', {}).get('Data', {})

        if isinstance(_bms_data, dict):
            for _comp in _bms_data.values():
                _candidate = (_comp or {}).get('channels', {})
                if _candidate:
                    _channels = _candidate
                    break

        if not _channels:
            return

        _ws_charge = _channels.get('BAT_ENERGYACTIVE_LIFETIME_CHARGED_F64')
        _ws_discharge = _channels.get('BAT_ENERGYACTIVE_LIFETIME_DISCHARGED_F64')
        if _ws_charge is None or _ws_discharge is None:
            return

        _bms_charge_life_kwh = float(_ws_charge) / 3600000.0
        _bms_discharge_life_kwh = float(_ws_discharge) / 3600000.0

        result['bms_lifetime_charge_kwh'] = round(_bms_charge_life_kwh, 3)
        result['bms_lifetime_discharge_kwh'] = round(_bms_discharge_life_kwh, 3)

        _today_start_ts = int(time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1)))
        _start_charge, _start_discharge = None, None
        _checkpoint_created = False

        # Primär: DB energy_checkpoints
        try:
            _conn_cp = get_db_connection()
            if _conn_cp:
                try:
                    _cp_row = _conn_cp.execute("""
                        SELECT W_Batt_Charge_BMS, W_Batt_Discharge_BMS
                        FROM energy_checkpoints
                        WHERE ts = ? AND checkpoint_type = 'day_start'
                        LIMIT 1
                    """, (_today_start_ts,)).fetchone()
                    if _cp_row and _cp_row[0] is not None and _cp_row[1] is not None:
                        _start_charge = _cp_row[0] / 1000.0
                        _start_discharge = _cp_row[1] / 1000.0
                        result['bms_checkpoint_source'] = 'energy_checkpoints'
                finally:
                    _conn_cp.close()
        except Exception:
            pass

        # Fallback: JSON-Checkpoint-Datei
        if _start_charge is None or _start_discharge is None:
            _checkpoint_path = Path(__file__).resolve().parent.parent / 'config' / 'battery_bms_checkpoints.json'
            _today_key = datetime.fromtimestamp(now).strftime('%Y-%m-%d')
            _cp_data = {'days': {}}

            if _checkpoint_path.exists():
                try:
                    with open(_checkpoint_path, 'r') as _fcp:
                        _loaded = _json_bms.load(_fcp)
                        if isinstance(_loaded, dict):
                            _cp_data = _loaded
                            if 'days' not in _cp_data or not isinstance(_cp_data['days'], dict):
                                _cp_data['days'] = {}
                except Exception:
                    _cp_data = {'days': {}}

            _days = _cp_data['days']
            if _today_key not in _days:
                _days[_today_key] = {
                    'charge_kwh': _bms_charge_life_kwh,
                    'discharge_kwh': _bms_discharge_life_kwh,
                    'captured_ts': int(now)
                }
                _checkpoint_created = True
                with open(_checkpoint_path, 'w') as _fcp:
                    _json_bms.dump(_cp_data, _fcp, indent=2)

            _start_charge = _days[_today_key].get('charge_kwh')
            _start_discharge = _days[_today_key].get('discharge_kwh')
            result['bms_checkpoint_source'] = 'battery_bms_checkpoints.json'

        if _start_charge is not None and _start_discharge is not None:
            _delta_charge = max(0.0, _bms_charge_life_kwh - float(_start_charge))
            _delta_discharge = max(0.0, _bms_discharge_life_kwh - float(_start_discharge))

            result['bms_day_charge_kwh'] = round(_delta_charge, 3)
            result['bms_day_discharge_kwh'] = round(_delta_discharge, 3)
            if _checkpoint_created:
                result['batt_discharge_check'] = {
                    'ok': None, 'status': 'checkpoint_initialized',
                    'method': 'calc_vs_bms_fixpoint',
                }
            elif _delta_discharge < 0.2:
                result['batt_discharge_check'] = {
                    'ok': None, 'status': 'warmup',
                    'method': 'calc_vs_bms_fixpoint',
                }
            else:
                _calc_discharge = float(result.get('batt_discharge_kwh') or 0.0)
                _diff = abs(_calc_discharge - _delta_discharge)
                _threshold = max(0.25, _delta_discharge * 0.25)
                result['batt_discharge_check'] = {
                    'ok': _diff <= _threshold,
                    'diff_kwh': round(_diff, 3),
                    'threshold_kwh': round(_threshold, 3),
                    'method': 'calc_vs_bms_fixpoint',
                }
    except Exception as e:
        logging.debug(f"BMS Counter Check Fehler: {e}")


def _fetch_temperatures(result):
    """WR-, Batterie- und F2-Temperaturen + BMS-Live-Daten aus Fronius /components/readable."""
    # F1 (GEN24)
    try:
        import requests as _req
        _comp_resp = _req.get(
            f'http://{config.INVERTER_IP}/components/readable', timeout=3)
        if _comp_resp.status_code == 200:
            _comp_data = _comp_resp.json()
            _data = _comp_data.get('Body', {}).get('Data', {})

            # Dynamische Schlüsselsuche (FW ≥1.39: benannte Keys statt "0"/"16580608")
            _inv_key = next((k for k in _data if 'Inverter' in k), '0')
            _batt_key = next((k for k in _data if 'Storage' in k or 'BYD' in k), '16580608')

            _wr_ch = _data.get(_inv_key, {}).get('channels', {})
            for attr, key in [
                ('wr_temp_intern', 'DEVICE_TEMPERATURE_AMBIENTMEAN_01_F32'),
                ('wr_temp_ac',     'MODULE_TEMPERATURE_MEAN_01_F32'),
                ('wr_temp_dc',     'MODULE_TEMPERATURE_MEAN_03_F32'),
                ('wr_temp_dc_batt', 'MODULE_TEMPERATURE_MEAN_04_F32'),
            ]:
                _t = _wr_ch.get(key)
                if _t is not None:
                    result[attr] = round(_t, 1)

            _batt_dev = _data.get(_batt_key, {})
            _batt_ch = _batt_dev.get('channels', {})
            _batt_attr = _batt_dev.get('attributes', {})
            for attr, key in [
                ('battery_temp',     'BAT_TEMPERATURE_CELL_F64'),
                ('battery_temp_max', 'BAT_TEMPERATURE_CELL_MAX_F64'),
                ('battery_temp_min', 'BAT_TEMPERATURE_CELL_MIN_F64'),
            ]:
                _t = _batt_ch.get(key)
                if _t is not None:
                    result[attr] = round(_t, 1)

            # ── BMS-Live-Daten (SOH, Kapazität, Lifetime, Firmware) ──
            _soh = _batt_ch.get('BAT_VALUE_STATE_OF_HEALTH_RELATIVE_U16')
            if _soh is not None:
                result['soh'] = round(float(_soh), 1)
                result['soh_source'] = 'bms_live'

            # Kapazitäten (Ws → kWh)
            _max_cap = _batt_ch.get('BAT_ENERGYACTIVE_MAX_CAPACITY_F64')
            _est_cap = _batt_ch.get('BAT_ENERGYACTIVE_ESTIMATION_MAX_CAPACITY_F64')
            if _max_cap is not None:
                result['bms_max_capacity_kwh'] = round(float(_max_cap) / 3_600_000, 2)
            if _est_cap is not None:
                result['bms_est_capacity_kwh'] = round(float(_est_cap) / 3_600_000, 2)

            # Lifetime Lade-/Entladeenergie (Ws → kWh)
            _lt_chg = _batt_ch.get('BAT_ENERGYACTIVE_LIFETIME_CHARGED_F64')
            _lt_dis = _batt_ch.get('BAT_ENERGYACTIVE_LIFETIME_DISCHARGED_F64')
            if _lt_chg is not None:
                result['bms_lifetime_charged_kwh'] = round(float(_lt_chg) / 3_600_000, 1)
            if _lt_dis is not None:
                result['bms_lifetime_discharged_kwh'] = round(float(_lt_dis) / 3_600_000, 1)

            # Vollzyklen-Schätzung (Lifetime-Entladung / Nenn-Kapazität)
            if _lt_dis is not None and _max_cap and float(_max_cap) > 0:
                result['bms_full_cycles'] = round(float(_lt_dis) / float(_max_cap), 0)

            # BMS-Firmware & Seriennummer
            _serial = (_batt_attr.get('serial') or '').strip()
            if _serial:
                result['bms_serial'] = _serial
            _sw = _batt_attr.get('sw_version')
            if _sw:
                result['bms_firmware'] = str(_sw)
            _hw = _batt_attr.get('hw_version')
            if _hw:
                result['bms_hw_version'] = str(_hw)

    except Exception as e:
        logging.debug(f"F1 temperatures fetch: {e}")

    # Fallback: Wenn keine WR-Temperaturen verfügbar, 'n/v' setzen
    for _tk in ('wr_temp_intern', 'wr_temp_ac', 'wr_temp_dc', 'wr_temp_dc_batt',
                'battery_temp', 'battery_temp_max', 'battery_temp_min'):
        if _tk not in result:
            result[_tk] = 'n/v'

    # F2 (Symo 10.0)
    try:
        import requests as _req2
        _f2_api = os.environ.get('PV_SECONDARY_INVERTER_API', 'http://192.0.2.123/components/readable')
        _f2_resp = _req2.get(_f2_api, timeout=2)
        if _f2_resp.status_code == 200:
            _f2_data = _f2_resp.json().get('Body', {}).get('Data', {})
            _f2_inv_key = next((k for k in _f2_data if 'Inverter' in k), '0')
            _f2_ch = _f2_data.get(_f2_inv_key, {}).get('channels', {})
            for attr, key in [
                ('f2_temp_intern', 'DEVICE_TEMPERATURE_AMBIENTMEAN_01_F32'),
                ('f2_temp_ac',     'MODULE_TEMPERATURE_MEAN_01_F32'),
                ('f2_temp_dc',     'MODULE_TEMPERATURE_MEAN_03_F32'),
                ('f2_temp_dc2',    'MODULE_TEMPERATURE_MEAN_04_F32'),
            ]:
                _t = _f2_ch.get(key)
                if _t is not None:
                    result[attr] = round(_t, 1)
    except Exception as e:
        logging.debug(f"F2 temperatures fetch: {e}")

    # Fallback: Wenn keine F2-Temperaturen verfügbar, 'n/v' setzen
    for _tk2 in ('f2_temp_intern', 'f2_temp_ac', 'f2_temp_dc', 'f2_temp_dc2'):
        if _tk2 not in result:
            result[_tk2] = 'n/v'


def _fetch_hp_status(now, result):
    """Fritz!DECT Heizpatronen-Status: Log-Daten + Live-Abfrage."""
    # Log-Daten aus schaltlog.txt (Engine schreibt HP-Events nur dorthin)
    import re as _re_hp
    try:
        _schaltlog_path = str(Path(__file__).resolve().parent.parent / 'logs' / 'schaltlog.txt')
        _today_str = time.strftime('%Y-%m-%d', time.localtime(now))
        hp_aktionen = []
        klima_aktionen = []
        hp_seen = set()
        klima_seen = set()
        _hp_pattern = _re_hp.compile(
            r'^\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'ENGINE\s+fritzdect\s+'
            r'(hp_ein|hp_aus)\S*\s+'
            r'(OK|FEHLER)\s*(.*)')
        _klima_pattern = _re_hp.compile(
            r'^\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'ENGINE\s+fritzdect\s+'
            r'(klima_ein|klima_aus)\S*\s+'
            r'(OK|FEHLER)\s*(.*)')
        _hp_extern_pattern = _re_hp.compile(
            r'^\s*~?\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'EXTERN\s+fritzdect\s+HP\s+extern\s+(EIN|AUS)\s+--\s*(.*)',
            _re_hp.IGNORECASE)
        _klima_extern_pattern = _re_hp.compile(
            r'^\s*~?\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'EXTERN\s+fritzdect\s+Klima\s+extern\s+(EIN|AUS)\s+--\s*(.*)',
            _re_hp.IGNORECASE)
        if os.path.exists(_schaltlog_path):
            with open(_schaltlog_path, 'r') as _slf:
                for _line in _slf:
                    _m = _hp_pattern.match(_line)
                    if _m:
                        _datum, _zeit, _cmd, _erg, _grund = _m.groups()
                        if _datum == _today_str and _erg == 'OK':
                            _grund_txt = (_grund or '').strip()[:120]
                            _key = (_datum, _zeit, _cmd, 'OK', _grund_txt, 'automation')
                            if _key in hp_seen:
                                continue
                            hp_seen.add(_key)
                            hp_aktionen.append({
                                'ts': f'{_datum} {_zeit[:5]}',
                                'kommando': _cmd,
                                'wert': '',
                                'grund': _grund_txt,
                                'ergebnis': _erg,
                                'quelle': 'automation',
                            })
                        continue

                    _mk = _klima_pattern.match(_line)
                    if _mk:
                        _datum, _zeit, _cmd, _erg, _grund = _mk.groups()
                        if _datum == _today_str and _erg == 'OK':
                            _grund_txt = (_grund or '').strip()[:120]
                            _key = (_datum, _zeit, _cmd, 'OK', _grund_txt, 'automation')
                            if _key in klima_seen:
                                continue
                            klima_seen.add(_key)
                            klima_aktionen.append({
                                'ts': f'{_datum} {_zeit[:5]}',
                                'kommando': _cmd,
                                'wert': '',
                                'grund': _grund_txt,
                                'ergebnis': _erg,
                                'quelle': 'automation',
                            })
                        continue

                    _mx = _hp_extern_pattern.match(_line)
                    if _mx:
                        _datum, _zeit, _state, _grund = _mx.groups()
                        if _datum == _today_str:
                            _cmd = 'hp_ein' if str(_state).upper() == 'EIN' else 'hp_aus'
                            _grund_txt = (_grund or 'Manuell/extern geschaltet').strip()[:120]
                            _key = (_datum, _zeit, _cmd, 'EXTERN', _grund_txt, 'extern')
                            if _key in hp_seen:
                                continue
                            hp_seen.add(_key)
                            hp_aktionen.append({
                                'ts': f'{_datum} {_zeit[:5]}',
                                'kommando': _cmd,
                                'wert': '',
                                'grund': _grund_txt,
                                'ergebnis': 'EXTERN',
                                'quelle': 'extern',
                            })
                        continue

                    _mxk = _klima_extern_pattern.match(_line)
                    if _mxk:
                        _datum, _zeit, _state, _grund = _mxk.groups()
                        if _datum == _today_str:
                            _cmd = 'klima_ein' if str(_state).upper() == 'EIN' else 'klima_aus'
                            _grund_txt = (_grund or 'Manuell/extern geschaltet').strip()[:120]
                            _key = (_datum, _zeit, _cmd, 'EXTERN', _grund_txt, 'extern')
                            if _key in klima_seen:
                                continue
                            klima_seen.add(_key)
                            klima_aktionen.append({
                                'ts': f'{_datum} {_zeit[:5]}',
                                'kommando': _cmd,
                                'wert': '',
                                'grund': _grund_txt,
                                'ergebnis': 'EXTERN',
                                'quelle': 'extern',
                            })
            # Neueste zuerst
            hp_aktionen.reverse()
            hp_aktionen = hp_aktionen[:20]
            klima_aktionen.reverse()
            klima_aktionen = klima_aktionen[:20]

        result['hp_aktionen'] = hp_aktionen
        result['klima_aktionen'] = klima_aktionen
        result['hp_bursts_heute'] = sum(
            1 for a in hp_aktionen
            if a['kommando'] == 'hp_ein' and a['ergebnis'] == 'OK')
    except Exception as _he:
        logging.debug(f"HP-Log (schaltlog): {_he}")
        result['hp_aktionen'] = []
        result['klima_aktionen'] = []
        result['hp_bursts_heute'] = 0

    # Live-Status von Fritz!Box (eigener Cache 120s)
    try:
        global _fritzdect_cache
        if _fritzdect_cache['data'] and (now - _fritzdect_cache['ts']) < _FRITZDECT_CACHE_TTL:
            fritz_live = _fritzdect_cache['data']
        else:
            fritz_live = None
            try:
                from automation.engine.aktoren.aktor_fritzdect import (
                    _load_fritz_config, _get_session_id, _aha_device_info
                )
                _fcfg = _load_fritz_config()
                _fhost = _fcfg.get('fritz_ip', '192.168.178.1')
                _fain = _fcfg.get('ain', '')
                _fuser = _fcfg.get('fritz_user', '')
                _fpass = _fcfg.get('fritz_password', '')

                if _fain and _fuser and _fpass:
                    _fsid = _get_session_id(_fhost, _fuser, _fpass)
                    if _fsid:
                        fritz_live = _aha_device_info(_fhost, _fain, _fsid)
            except Exception as _fe:
                logging.debug(f"Fritz!DECT Live-Query: {_fe}")

            _fritzdect_cache = {'ts': now, 'data': fritz_live}

        if fritz_live and fritz_live.get('state') is not None:
            state_raw = str(fritz_live.get('state')).strip()
            zustand = 'EIN' if state_raw == '1' else 'AUS' if state_raw == '0' else '?'
            power_w = (fritz_live.get('power_mw') or 0) / 1000
            hp_aktionen = result.get('hp_aktionen', [])
            last_hp = hp_aktionen[0] if hp_aktionen else {}
            result['hp_status'] = {
                'zustand': zustand, 'live': True,
                'power_w': round(power_w, 1),
                'energy_wh': fritz_live.get('energy_wh'),
                'name': fritz_live.get('name'),
                'seit': last_hp.get('ts'),
                'grund': last_hp.get('grund', ''),
                'kommando': last_hp.get('kommando'),
            }
        else:
            hp_aktionen = result.get('hp_aktionen', [])
            if hp_aktionen:
                last = hp_aktionen[0]
                result['hp_status'] = {
                    'zustand': 'EIN' if last['kommando'] == 'hp_ein' and last['ergebnis'] == 'OK' else 'AUS',
                    'live': False, 'seit': last['ts'],
                    'grund': last['grund'], 'kommando': last['kommando'],
                }
            else:
                result['hp_status'] = {
                    'zustand': '?', 'live': False, 'seit': None,
                    'grund': '', 'kommando': None,
                }
    except Exception as _hle:
        logging.debug(f"HP-Live-Status: {_hle}")
        result['hp_status'] = {
            'zustand': '?', 'live': False, 'seit': None,
            'grund': '', 'kommando': None,
        }


def _fetch_wp_status(result):
    """Wärmepumpe Dimplex – Temperaturen aus ObsState (ABCD: kein direkter Modbus in B).

    Daten werden vom DataCollector (C-Rolle) via wp_modbus.py gesammelt
    und in /dev/shm/automation_obs.db → obs_state abgelegt.
    """
    try:
        import json as _json_wp
        _obs_db_wp = '/dev/shm/automation_obs.db'
        with sqlite3.connect(_obs_db_wp) as _odb_wp:
            _orow_wp = _odb_wp.execute('SELECT state_json FROM obs_state LIMIT 1').fetchone()
            if _orow_wp:
                _obs_wp = _json_wp.loads(_orow_wp[0])
                wp = {}
                _field_map = {
                    'vorlauf': 'wp_vorlauf_c',
                    'ruecklauf': 'wp_ruecklauf_c',
                    'ruecklauf_soll': 'wp_ruecklauf_soll_c',
                    'ww_ist': 'ww_temp_c',
                    'quelle_ein': 'wp_quelle_ein_c',
                    'quelle_aus': 'wp_quelle_aus_c',
                    'ww_soll': 'wp_ww_soll_c',
                }
                for api_key, obs_key in _field_map.items():
                    val = _obs_wp.get(obs_key)
                    if val is not None:
                        wp[api_key] = val
                if wp:
                    wp['quelle'] = 'obs_state'
                    result['wp_status'] = wp
                else:
                    result['wp_status'] = {'error': 'keine WP-Daten in ObsState'}
            else:
                result['wp_status'] = {'error': 'obs_state leer'}
    except Exception as _we:
        logging.debug(f"WP-Status (ObsState): {_we}")
        result['wp_status'] = {'error': str(_we)}


def _fetch_soh(result):
    """SOH-Fallback aus battery_control.json (nur wenn BMS-Live nicht verfügbar)."""
    if result.get('soh') is not None:
        return  # BMS-Live-Wert bereits von _fetch_temperatures gesetzt
    try:
        import json as _json2
        _batt_cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'config', 'battery_control.json')
        with open(_batt_cfg_path, 'r') as _f:
            _batt_cfg = _json2.load(_f)
        result['soh'] = float(_batt_cfg.get('batterie', {}).get('soh_prozent', 92.0))
        result['soh_source'] = 'config_fallback'
    except Exception:
        result['soh'] = 92.0
        result['soh_source'] = 'default'

# ═══════════════════════════════════════════════════════════════
# SYSTEM INFO ENDPOINT
# ═══════════════════════════════════════════════════════════════

@bp.route('/api/system_info')
def api_system_info():
    """Live-Systeminfos: CPU, RAM, Temp, Uptime, DB-Größe."""
    import subprocess, platform
    result = {}
    try:
        # CPU-Auslastung (1-min Load Average)
        load1, load5, load15 = os.getloadavg()
        result['cpu_load'] = {'1min': round(load1, 2), '5min': round(load5, 2), '15min': round(load15, 2)}

        # CPU-Cores
        result['cpu_cores'] = os.cpu_count() or 1

        # RAM
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
            mem = {}
            for line in lines:
                parts = line.split()
                if parts[0] in ('MemTotal:', 'MemAvailable:', 'MemFree:'):
                    mem[parts[0].rstrip(':')] = int(parts[1])  # kB
            total_mb = mem.get('MemTotal', 0) / 1024
            avail_mb = mem.get('MemAvailable', mem.get('MemFree', 0)) / 1024
            used_mb = total_mb - avail_mb
            result['ram'] = {
                'total_mb': round(total_mb),
                'used_mb': round(used_mb),
                'avail_mb': round(avail_mb),
                'percent': round(used_mb / total_mb * 100, 1) if total_mb > 0 else 0
            }
        except Exception:
            result['ram'] = None

        # CPU-Temperatur
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp_mc = int(f.read().strip())
            result['cpu_temp_c'] = round(temp_mc / 1000, 1)
        except Exception:
            result['cpu_temp_c'] = None

        # Uptime
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_s = float(f.read().split()[0])
            days = int(uptime_s // 86400)
            hours = int((uptime_s % 86400) // 3600)
            mins = int((uptime_s % 3600) // 60)
            result['uptime'] = f"{days}d {hours}h {mins}m"
            result['uptime_seconds'] = round(uptime_s)
        except Exception:
            result['uptime'] = None

        # Hostname + Modell
        result['hostname'] = platform.node()
        try:
            with open('/proc/device-tree/model', 'r') as f:
                result['model'] = f.read().strip().rstrip('\x00')
        except Exception:
            result['model'] = platform.machine()

        # Python Version
        result['python'] = platform.python_version()

        # DB-Größe (tmpfs)
        try:
            db_path = '/dev/shm/fronius_data.db'
            if os.path.exists(db_path):
                size_bytes = os.path.getsize(db_path)
                result['db_size_mb'] = round(size_bytes / 1024 / 1024, 1)
            else:
                result['db_size_mb'] = None
        except Exception:
            result['db_size_mb'] = None

        # Disk (SD-Card / Root)
        try:
            st = os.statvfs('/')
            total_gb = (st.f_frsize * st.f_blocks) / (1024**3)
            free_gb = (st.f_frsize * st.f_bavail) / (1024**3)
            result['disk'] = {
                'total_gb': round(total_gb, 1),
                'free_gb': round(free_gb, 1),
                'percent': round((1 - free_gb / total_gb) * 100, 1) if total_gb > 0 else 0
            }
        except Exception:
            result['disk'] = None

    except Exception as e:
        logging.error(f"System Info Fehler: {e}")
        return jsonify({"error": str(e)}), 500

    return jsonify(result)


# ═══════════════════════════════════════════════════════════════
# WATTPILOT ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@bp.route('/api/wattpilot/status')
def wattpilot_status():
    """Live-Status vom Wattpilot (mit 30s Cache)."""
    now = time.time()

    # 30s Cache
    if wattpilot_cache['data'] and (now - wattpilot_cache['ts']) < 30:
        return jsonify(wattpilot_cache['data'])

    try:
        from wattpilot_api import WattpilotClient
        client = WattpilotClient()
        summary = client.get_status_summary()
        wattpilot_cache['data'] = summary
        wattpilot_cache['ts'] = now
        return jsonify(summary)
    except Exception as e:
        logging.warning(f"Wattpilot offline: {e}")
        if wattpilot_cache['data']:
            return jsonify(wattpilot_cache['data'])
        # Offline ist normaler Betriebszustand → 200 (nicht 500)
        return jsonify({"online": False, "error_message": str(e), "timestamp": datetime.now().isoformat()})


@bp.route('/api/wattpilot/history')
def wattpilot_history():
    """Wattpilot-Tagesverbrauch für einen Monat (aus wattpilot_daily)."""
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)

        if not year or not month:
            now = datetime.now()
            year = now.year
            month = now.month

        first_day = datetime(year, month, 1)
        if month == 12:
            last_day = datetime(year + 1, 1, 1)
        else:
            last_day = datetime(year, month + 1, 1)

        first_ts = int(first_day.timestamp())
        last_ts = int(last_day.timestamp())

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500

        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ts, energy_wh, max_power_w, charging_hours, sessions
                FROM wattpilot_daily
                WHERE ts >= ? AND ts < ?
                ORDER BY ts
            """, (first_ts, last_ts))

            rows = cursor.fetchall()
        except Exception:
            rows = []  # Tabelle existiert noch nicht
        finally:
            conn.close()

        datapoints = []
        for row in rows:
            ts, energy_wh, max_power, charging_h, sessions = row
            datapoints.append({
                'timestamp': ts,
                'date': datetime.fromtimestamp(ts).strftime('%Y-%m-%d'),
                'day': datetime.fromtimestamp(ts).day,
                'energy_kwh': round((energy_wh or 0) / 1000, 2),
                'energy_wh': round(energy_wh or 0, 1),
                'max_power_w': round(max_power or 0, 0),
                'charging_hours': round(charging_h or 0, 1),
                'sessions': sessions or 0
            })

        return jsonify({
            'year': year,
            'month': month,
            'datapoints': datapoints,
            'total_kwh': round(sum(dp['energy_kwh'] for dp in datapoints), 2)
        })

    except Exception as e:
        logging.error(f"Wattpilot History Fehler: {e}")
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  Failover-Status  (nur auf Primary relevant)
# ══════════════════════════════════════════════════════════════
@bp.route('/api/failover_status')
def api_failover_status():
    """
    Prüft den Failover-Host via SSH:
    Liest den Timestamp der Sync-Marker-Datei (.state/last_mirror_sync.ok).
    Wenn ≤ 15 Min alt → live, ≤ 30 Min → stale, sonst → down.
    Fallback: SSH-Connect prüfen (Host da, aber Sync kaputt).
    Cache: 60 Sekunden — max. 1 SSH-Aufruf pro Minute.
    """
    import subprocess

    now = time.time()
    if now - _failover_cache['ts'] < _FAILOVER_CACHE_TTL and _failover_cache['result'] is not None:
        return jsonify(_failover_cache['result'])

    failover_ip = getattr(config, 'FAILOVER_IP', None)
    failover_user = getattr(config, 'FAILOVER_USER', 'failover-user')
    failover_pv_base = getattr(config, 'FAILOVER_PV_BASE',
                               '/srv/pv-system')

    if not failover_ip:
        result = {'status': 'unknown', 'detail': 'FAILOVER_IP nicht konfiguriert'}
        _failover_cache.update(ts=now, result=result)
        return jsonify(result)

    marker = f'{failover_pv_base}/.state/last_mirror_sync.ok'
    ssh_target = f'{failover_user}@{failover_ip}'

    try:
        # SSH: Marker-Timestamp lesen (stat -c %Y = modtime als epoch)
        proc = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=3', '-o', 'StrictHostKeyChecking=no',
             ssh_target, f'stat -c %Y "{marker}" 2>/dev/null || echo 0'],
            capture_output=True, text=True, timeout=6
        )
        marker_ts = int(proc.stdout.strip() or '0')
        age_sec = int(now - marker_ts) if marker_ts > 0 else -1

        if age_sec < 0:
            result = {'status': 'stale', 'age': None,
                      'detail': 'Sync-Marker nicht gefunden'}
        elif age_sec <= 900:   # ≤ 15 Min
            result = {'status': 'live', 'age': age_sec,
                      'detail': f'Mirror OK ({age_sec // 60} Min)'}
        elif age_sec <= 1800:  # ≤ 30 Min
            result = {'status': 'stale', 'age': age_sec,
                      'detail': f'Mirror veraltet ({age_sec // 60} Min)'}
        else:
            result = {'status': 'stale', 'age': age_sec,
                      'detail': f'Mirror zu alt ({age_sec // 60} Min)'}

    except subprocess.TimeoutExpired:
        result = {'status': 'down', 'age': None,
                  'detail': 'SSH-Timeout (Failover-Host nicht erreichbar)'}
    except Exception as e:
        result = {'status': 'down', 'age': None,
                  'detail': f'Fehler: {e}'}

    _failover_cache.update(ts=now, result=result)
    return jsonify(result)


@bp.route('/api/backup_status')
def api_backup_status():
    """
    Prüft den Backup-Pfad auf Pi5 via SSH (Existenz Zielverzeichnis).

    Status:
      - up:   Zielverzeichnis vorhanden
      - down: Zielverzeichnis fehlt oder SSH-Fehler

    Cache: 10 Minuten (kein häufiger SSH-Check nötig).
    """
    import subprocess

    now = time.time()
    if now - _backup_cache['ts'] < _BACKUP_CACHE_TTL and _backup_cache['result'] is not None:
        return jsonify(_backup_cache['result'])

    pi5_host = getattr(config, 'PI5_BACKUP_HOST', None)
    pi5_db_path = getattr(config, 'PI5_BACKUP_DB_PATH', '/srv/pv-system/data.db')
    default_gfs_base = os.path.join(os.path.dirname(pi5_db_path), 'backup', 'db')
    target_dir = getattr(config, 'PI5_BACKUP_GFS_BASE', default_gfs_base)

    if not pi5_host:
        result = {'status': 'down', 'detail': 'PI5_BACKUP_HOST nicht konfiguriert', 'target_dir': target_dir}
        _backup_cache.update(ts=now, result=result)
        return jsonify(result)

    try:
        # Prüfe Erreichbarkeit UND Aktualität der Backup-DB
        proc = subprocess.run(
            [
                'ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
                pi5_host,
                f'test -d "{target_dir}" && stat -c%Y "{pi5_db_path}" 2>/dev/null || echo 0'
            ],
            capture_output=True, text=True, timeout=8
        )

        out = (proc.stdout or '').strip()
        try:
            remote_mtime = int(out)
        except ValueError:
            remote_mtime = 0

        if remote_mtime == 0:
            result = {
                'status': 'down',
                'detail': 'Zielverzeichnis oder DB fehlt/nicht erreichbar',
                'target_dir': target_dir,
                'checked_at': int(now),
            }
        else:
            age_h = (now - remote_mtime) / 3600
            if age_h <= 12:
                result = {
                    'status': 'up',
                    'detail': f'Backup aktuell (vor {age_h:.1f}h)',
                    'target_dir': target_dir,
                    'checked_at': int(now),
                    'backup_age_hours': round(age_h, 1),
                }
            else:
                result = {
                    'status': 'stale',
                    'detail': f'Backup veraltet! Letzte Aktualisierung vor {age_h:.0f}h',
                    'target_dir': target_dir,
                    'checked_at': int(now),
                    'backup_age_hours': round(age_h, 1),
                }
    except subprocess.TimeoutExpired:
        result = {
            'status': 'down',
            'detail': 'SSH-Timeout zu Pi5',
            'target_dir': target_dir,
            'checked_at': int(now),
        }
    except Exception as e:
        result = {
            'status': 'down',
            'detail': f'Fehler: {e}',
            'target_dir': target_dir,
            'checked_at': int(now),
        }

    _backup_cache.update(ts=now, result=result)
    return jsonify(result)
