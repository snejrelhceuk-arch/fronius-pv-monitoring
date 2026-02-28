"""
Blueprint: System-Status-APIs.

Enthält: /api/battery_status, /api/system_info,
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


@bp.route('/api/battery_status')
def api_battery_status():
    """
    Aktuelle Batterie-Konfiguration vom Fronius GEN24.
    Liefert SOC_MIN, SOC_MAX, Modus, Netzladung, Notstrom-Reserve.
    Plus: Scheduler-Status (Entladerate, Phasen-Flags).
    Cache: 60 Sekunden (Werte ändern sich selten).
    """
    import time as _time

    # Cache prüfen (60s gültig)
    now = _time.time()
    if battery_cache['data'] and (now - battery_cache['ts']) < 60:
        return jsonify(battery_cache['data'])

    try:
        api = get_fronius_api()
        if not api:
            return jsonify({"error": "FroniusAPI nicht verfügbar"}), 503

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
        }

        result['batt_energy_method'] = 'integration_ui_with_counter_fallback'

        # Automation Engine State (echte Daten aus automation_log)
        try:
            import json as _json

            with sqlite3.connect(config.DB_PATH) as _adb:
                _24h_ago = int(now) - 86400

                # Vergangene SOC-Umschaltungen (letzte 24 h) — nur SOC-Befehle
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
                    'ts': r[0],
                    'kommando': r[1],
                    'wert': r[2],
                    'grund': (r[3] or '')[:120],
                    'ergebnis': r[4],
                } for r in soc_rows]

                # ALLE Engine-Aktionen der letzten 24 h (inkl. Lade-/Entladerate, hold)
                all_rows = _adb.execute("""
                    SELECT ts, kommando, wert, grund, ergebnis
                    FROM automation_log
                    WHERE aktor = 'batterie'
                      AND ts >= datetime(?, 'unixepoch')
                    ORDER BY ts DESC
                    LIMIT 50
                """, (_24h_ago,)).fetchall()

                result['engine_aktionen'] = [{
                    'ts': r[0],
                    'kommando': r[1],
                    'wert': r[2],
                    'grund': (r[3] or '')[:120],
                    'ergebnis': r[4],
                } for r in all_rows]

                # Letzter Engine-Zyklus: Gewinner-Regel + Score
                last_action = _adb.execute("""
                    SELECT ts, kommando, wert, grund, ergebnis
                    FROM automation_log
                    WHERE aktor = 'batterie'
                    ORDER BY id DESC LIMIT 1
                """).fetchone()
                if last_action:
                    result['last_engine_action'] = {
                        'ts': last_action[0],
                        'kommando': last_action[1],
                        'wert': last_action[2],
                        'grund': (last_action[3] or '')[:120],
                        'ergebnis': last_action[4],
                    }

            # Engine-Vorausschau (Dry-Run aller Regeln auf aktuellem Zustand)
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

            # ── Automation-Phasen für Tagesübersicht ──────────────────
            # Kombiniert battery_control_log (heutige Aktionen) mit
            # Scheduler-State (Flags), um pro Phase den Status zu zeigen.
            try:
                _sched = result.get('scheduler', {})
                _today_start = int(now) - int(now) % 86400  # UTC midnight
                # Lokale Mitternacht (genauer):
                import calendar
                _local_midnight = int(_time.mktime(
                    _time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1)))

                with sqlite3.connect(config.DB_PATH) as _pdb:
                    _log_rows = _pdb.execute("""
                        SELECT action, param, old_value, new_value, reason,
                               datetime(ts, 'unixepoch', 'localtime') as ts_local,
                               manual, forecast_kwh, cloud_avg
                        FROM battery_control_log
                        WHERE ts >= ?
                        ORDER BY ts ASC
                    """, (_local_midnight,)).fetchall()

                _phase_log = {}
                for _r in _log_rows:
                    _action = _r[0]
                    _entry = {
                        'zeit': _r[5][11:16] if _r[5] and len(_r[5]) > 15 else None,
                        'aktion': '',
                        'grund': (_r[4] or '')[:80],
                        'manuell': bool(_r[6]),
                        'prognose_kwh': _r[7],
                        'wolken': _r[8],
                    }
                    if _action == 'morning_open':
                        _entry['aktion'] = f"SOC_MIN {_r[2]}→{_r[3]}%"
                        _entry['status'] = 'done'
                        _phase_log['morgen'] = _entry
                    elif _action == 'morning_skip':
                        _entry['aktion'] = 'Übersprungen'
                        _entry['status'] = 'skipped'
                        _phase_log['morgen'] = _entry
                    elif _action == 'afternoon_raise':
                        _entry['aktion'] = f"SOC_MAX {_r[2]}→{_r[3]}%"
                        _entry['status'] = 'done'
                        _phase_log['nachmittag'] = _entry
                    elif _action == 'evening_limit':
                        _entry['aktion'] = f"Entladerate {_r[2]}→{_r[3]}%"
                        _entry['status'] = 'active'
                        _phase_log['abend'] = _entry
                    elif _action == 'evening_auto':
                        _entry['aktion'] = 'Limit aufgehoben'
                        _entry['status'] = 'done'
                        _phase_log['abend'] = _entry
                    elif _action == 'comfort_reset':
                        _entry['aktion'] = 'Komfort-Reset'
                        _entry['status'] = 'done'
                        _phase_log['reset'] = _entry

                # Fehlende Phasen mit State-Flags auffüllen
                if 'morgen' not in _phase_log:
                    _phase_log['morgen'] = {
                        'status': 'done' if _sched.get('morning_done') else 'pending',
                        'zeit': None,
                        'aktion': '—' if _sched.get('morning_done') else 'SOC_MIN → 5%',
                        'grund': '', 'manuell': False,
                    }
                if 'nachmittag' not in _phase_log:
                    _phase_log['nachmittag'] = {
                        'status': 'done' if _sched.get('afternoon_done') else 'pending',
                        'zeit': None,
                        'aktion': '—' if _sched.get('afternoon_done') else 'SOC_MAX → 100%',
                        'grund': '', 'manuell': False,
                    }
                _rate = _sched.get('evening_rate_percent')
                if 'abend' not in _phase_log:
                    _phase_log['abend'] = {
                        'status': 'active' if _sched.get('evening_rate_active') else 'pending',
                        'zeit': None,
                        'aktion': f"Entladerate {_rate}%" if _rate else 'Entladerate-Limit',
                        'grund': '', 'manuell': False,
                    }
                # Reset-Phase: Komfort-Bereich wiederherstellen
                # Lese Komfort-Grenzen aus Config für Zielwerte
                try:
                    import json as _json_cfg
                    _cfg_path = Path(__file__).resolve().parent.parent / 'config' / 'battery_control.json'
                    with open(_cfg_path, 'r') as _cf:
                        _bcfg = _json_cfg.load(_cf)
                    _k_min = _bcfg.get('soc_grenzen', {}).get('komfort_min', 25)
                    _k_max = _bcfg.get('soc_grenzen', {}).get('komfort_max', 75)
                except Exception:
                    _k_min, _k_max = 25, 75
                if 'reset' not in _phase_log:
                    _phase_log['reset'] = {
                        'status': 'pending',
                        'zeit': None,
                        'aktion': f'SOC_MIN → {_k_min}%, SOC_MAX → {_k_max}%',
                        'grund': 'Komfort-Reset (nächster Tageswechsel)',
                        'manuell': False,
                    }

                result['automation_phasen'] = _phase_log
            except Exception as _pe:
                logging.debug(f"Automation-Phasen: {_pe}")
        except Exception as e:
            logging.warning(f"Automation-State nicht lesbar: {e}")

        # Letzte SOC-Umschaltung (zuerst automation_log, Fallback battery_control_log)
        try:
            with sqlite3.connect(config.DB_PATH) as _ldb:
                # Neue Quelle: automation_log
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
                        'action': row[1],
                        'param':  row[1],
                        'old':    None,
                        'new':    row[2],
                        'reason': (row[3] or '')[:90],
                    }
                else:
                    # Legacy-Fallback: battery_control_log
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
                            'action': row[1],
                            'param':  row[2],
                            'old':    row[3],
                            'new':    row[4],
                            'reason': (row[5] or '')[:90],
                        }
        except Exception as e:
            logging.debug(f"last_soc_switch query: {e}")

        # Tages-Batterieenergie + SOC/SOH aus Echtzeit
        try:
            conn_b = get_db_connection()
            if conn_b:
                try:
                    cb = conn_b.cursor()
                    today_start = int(_time.mktime(_time.localtime(now)[:3] + (0,0,0, 0,0, -1)))
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
                    # Aktuellen SOC aus letztem raw_data Eintrag
                    cb.execute("SELECT SOC_Batt FROM raw_data ORDER BY ts DESC LIMIT 1")
                    soc_row = cb.fetchone()
                    result['current_soc'] = round(soc_row[0], 1) if soc_row and soc_row[0] is not None else None
                finally:
                    conn_b.close()
        except Exception as e:
            logging.warning(f"Batterie-Tageswerte Fehler: {e}")

        # BMS-Lifetime-Counter + Tages-Fixpunkt-Deltas
        try:
            import json as _json_bms
            import requests as _req_bms

            _bms_url = f'http://{config.INVERTER_IP}/components/BatteryManagementSystem/readable'
            _bms_resp = _req_bms.get(_bms_url, timeout=2)
            if _bms_resp.status_code == 200:
                _bms_payload = _bms_resp.json()
                _channels = None
                _bms_data = _bms_payload.get('Body', {}).get('Data', {})

                if isinstance(_bms_data, dict):
                    for _comp in _bms_data.values():
                        _candidate = (_comp or {}).get('channels', {})
                        if _candidate:
                            _channels = _candidate
                            break

                if _channels:
                    _ws_charge = _channels.get('BAT_ENERGYACTIVE_LIFETIME_CHARGED_F64')
                    _ws_discharge = _channels.get('BAT_ENERGYACTIVE_LIFETIME_DISCHARGED_F64')

                    if _ws_charge is not None and _ws_discharge is not None:
                        _bms_charge_life_kwh = float(_ws_charge) / 3600000.0
                        _bms_discharge_life_kwh = float(_ws_discharge) / 3600000.0

                        result['bms_lifetime_charge_kwh'] = round(_bms_charge_life_kwh, 3)
                        result['bms_lifetime_discharge_kwh'] = round(_bms_discharge_life_kwh, 3)

                        _checkpoint_created = False
                        _today_start_ts = int(_time.mktime(_time.localtime(now)[:3] + (0,0,0, 0,0, -1)))
                        _start_charge = None
                        _start_discharge = None

                        # Primär: feste day_start Checkpoints in DB
                        try:
                            _conn_cp = get_db_connection()
                            if _conn_cp:
                                try:
                                    _cur_cp = _conn_cp.cursor()
                                    _cur_cp.execute("""
                                        SELECT W_Batt_Charge_BMS, W_Batt_Discharge_BMS
                                        FROM energy_checkpoints
                                        WHERE ts = ? AND checkpoint_type = 'day_start'
                                        LIMIT 1
                                    """, (_today_start_ts,))
                                    _cp_row = _cur_cp.fetchone()
                                    if _cp_row and _cp_row[0] is not None and _cp_row[1] is not None:
                                        # DB speichert in Wh, wir rechnen in kWh
                                        _start_charge = _cp_row[0] / 1000.0
                                        _start_discharge = _cp_row[1] / 1000.0
                                        result['bms_checkpoint_source'] = 'energy_checkpoints'
                                finally:
                                    _conn_cp.close()
                        except Exception:
                            pass

                        # Fallback: bestehende JSON-Checkpoint-Datei
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
                                    'ok': None,
                                    'status': 'checkpoint_initialized',
                                    'method': 'calc_vs_bms_fixpoint'
                                }
                            elif _delta_discharge < 0.2:
                                result['batt_discharge_check'] = {
                                    'ok': None,
                                    'status': 'warmup',
                                    'method': 'calc_vs_bms_fixpoint'
                                }
                            else:
                                _calc_discharge = float(result.get('batt_discharge_kwh') or 0.0)
                                _diff = abs(_calc_discharge - _delta_discharge)
                                _threshold = max(0.25, _delta_discharge * 0.25)
                                result['batt_discharge_check'] = {
                                    'ok': _diff <= _threshold,
                                    'diff_kwh': round(_diff, 3),
                                    'threshold_kwh': round(_threshold, 3),
                                    'method': 'calc_vs_bms_fixpoint'
                                }
        except Exception as e:
            logging.debug(f"BMS Counter Check Fehler: {e}")

        # Temperaturen aus Fronius /components/readable (WR + Batterie)
        try:
            import requests as _req
            _comp_url = f'http://{config.INVERTER_IP}/components/readable'
            _comp_resp = _req.get(_comp_url, timeout=3)
            if _comp_resp.status_code == 200:
                _comp_data = _comp_resp.json()
                # WR-Temperaturen (Device 0 = Inverter)
                _wr_ch = _comp_data.get('Body', {}).get('Data', {}).get('0', {}).get('channels', {})
                _t = _wr_ch.get('DEVICE_TEMPERATURE_AMBIENTMEAN_01_F32')
                if _t is not None:
                    result['wr_temp_intern'] = round(_t, 1)
                _t = _wr_ch.get('MODULE_TEMPERATURE_MEAN_01_F32')
                if _t is not None:
                    result['wr_temp_ac'] = round(_t, 1)
                _t = _wr_ch.get('MODULE_TEMPERATURE_MEAN_03_F32')
                if _t is not None:
                    result['wr_temp_dc'] = round(_t, 1)
                _t = _wr_ch.get('MODULE_TEMPERATURE_MEAN_04_F32')
                if _t is not None:
                    result['wr_temp_dc_batt'] = round(_t, 1)
                # Batterie-Temperaturen (Device 16580608 = BYD Battery)
                _batt_ch = _comp_data.get('Body', {}).get('Data', {}).get('16580608', {}).get('channels', {})
                _t = _batt_ch.get('BAT_TEMPERATURE_CELL_F64')
                if _t is not None:
                    result['battery_temp'] = round(_t, 1)
                _t = _batt_ch.get('BAT_TEMPERATURE_CELL_MAX_F64')
                if _t is not None:
                    result['battery_temp_max'] = round(_t, 1)
                _t = _batt_ch.get('BAT_TEMPERATURE_CELL_MIN_F64')
                if _t is not None:
                    result['battery_temp_min'] = round(_t, 1)
        except Exception as e:
            logging.debug(f"F1 temperatures fetch: {e}")

        # F2-Temperaturen (Fronius Symo 10.0, 192.0.2.123)
        try:
            import requests as _req2
            _f2_url = 'http://192.0.2.123/components/readable'
            _f2_resp = _req2.get(_f2_url, timeout=2)
            if _f2_resp.status_code == 200:
                _f2_data = _f2_resp.json()
                _f2_ch = _f2_data.get('Body', {}).get('Data', {}).get('0', {}).get('channels', {})
                _t = _f2_ch.get('DEVICE_TEMPERATURE_AMBIENTMEAN_01_F32')
                if _t is not None:
                    result['f2_temp_intern'] = round(_t, 1)
                _t = _f2_ch.get('MODULE_TEMPERATURE_MEAN_01_F32')
                if _t is not None:
                    result['f2_temp_ac'] = round(_t, 1)
                _t = _f2_ch.get('MODULE_TEMPERATURE_MEAN_03_F32')
                if _t is not None:
                    result['f2_temp_dc'] = round(_t, 1)
                _t = _f2_ch.get('MODULE_TEMPERATURE_MEAN_04_F32')
                if _t is not None:
                    result['f2_temp_dc2'] = round(_t, 1)
        except Exception as e:
            logging.debug(f"F2 temperatures fetch: {e}")

        # ── HP-Automation (Fritz!DECT Heizpatrone) ─────────────
        # Log-Daten aus automation_log (Schalthistorie)
        try:
            with sqlite3.connect(config.DB_PATH) as _hdb:
                _24h_ago_hp = int(now) - 86400
                hp_rows = _hdb.execute("""
                    SELECT ts, kommando, wert, grund, ergebnis
                    FROM automation_log
                    WHERE aktor = 'fritzdect'
                      AND ts >= datetime(?, 'unixepoch')
                    ORDER BY ts DESC
                    LIMIT 10
                """, (_24h_ago_hp,)).fetchall()

                hp_aktionen = [{
                    'ts': r[0][:16].replace('T', ' ') if r[0] else '?',
                    'kommando': r[1],
                    'wert': r[2],
                    'grund': (r[3] or '')[:120],
                    'ergebnis': r[4],
                } for r in hp_rows]

                result['hp_aktionen'] = hp_aktionen
                hp_ein_count = sum(1 for a in hp_aktionen if a['kommando'] == 'hp_ein' and a['ergebnis'] == 'OK')
                result['hp_bursts_heute'] = hp_ein_count
        except Exception as _he:
            logging.debug(f"HP-Log: {_he}")
            result['hp_aktionen'] = []
            result['hp_bursts_heute'] = 0

        # Live-Status von der Fritz!Box (getdevicelistinfos, 1 Bulk-Request)
        # Eigener Cache (120s) — überlebt battery_cache-Invalidierung
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
                result['hp_status'] = {
                    'zustand': zustand,
                    'live': True,
                    'power_w': round(power_w, 1),
                    'energy_wh': fritz_live.get('energy_wh'),
                    'name': fritz_live.get('name'),
                    'seit': result.get('hp_aktionen', [{}])[0].get('ts') if result.get('hp_aktionen') else None,
                    'grund': result.get('hp_aktionen', [{}])[0].get('grund', '') if result.get('hp_aktionen') else '',
                    'kommando': result.get('hp_aktionen', [{}])[0].get('kommando') if result.get('hp_aktionen') else None,
                }
            else:
                # Fritz!Box nicht erreichbar → Fallback auf Log
                hp_aktionen = result.get('hp_aktionen', [])
                if hp_aktionen:
                    last = hp_aktionen[0]
                    result['hp_status'] = {
                        'zustand': 'EIN' if last['kommando'] == 'hp_ein' and last['ergebnis'] == 'OK' else 'AUS',
                        'live': False,
                        'seit': last['ts'],
                        'grund': last['grund'],
                        'kommando': last['kommando'],
                    }
                else:
                    result['hp_status'] = {'zustand': '?', 'live': False, 'seit': None, 'grund': '', 'kommando': None}
        except Exception as _hle:
            logging.debug(f"HP-Live-Status: {_hle}")
            result['hp_status'] = {'zustand': '?', 'live': False, 'seit': None, 'grund': '', 'kommando': None}

        # SOH aus config
        try:
            import json as _json2
            _batt_cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'battery_control.json')
            with open(_batt_cfg_path, 'r') as _f:
                _batt_cfg = _json2.load(_f)
            result['soh'] = float(_batt_cfg.get('batterie', {}).get('soh_prozent', 92.0))
        except Exception:
            result['soh'] = 92.0

        battery_cache['data'] = result
        battery_cache['ts'] = now
        return jsonify(result)
    except Exception as e:
        logging.error(f"Battery Status Fehler: {e}")
        # Bei Fehler: alten Cache zurückgeben falls vorhanden
        if battery_cache['data']:
            return jsonify(battery_cache['data'])
        return jsonify({"error": str(e)}), 500


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
    Prüft den Failover-Host (failover-host) via SSH:
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
    failover_user = getattr(config, 'FAILOVER_USER', 'jk')
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
                  'detail': 'SSH-Timeout (failover-host nicht erreichbar)'}
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
        proc = subprocess.run(
            [
                'ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
                pi5_host,
                f'test -d "{target_dir}" && echo up || echo down'
            ],
            capture_output=True, text=True, timeout=8
        )

        out = (proc.stdout or '').strip().lower()
        if out == 'up':
            result = {
                'status': 'up',
                'detail': 'Zielverzeichnis erreichbar',
                'target_dir': target_dir,
                'checked_at': int(now),
            }
        else:
            result = {
                'status': 'down',
                'detail': 'Zielverzeichnis fehlt/nicht erreichbar',
                'target_dir': target_dir,
                'checked_at': int(now),
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
