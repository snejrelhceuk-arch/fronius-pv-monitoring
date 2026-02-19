"""
Blueprint: System-Status-APIs.

Enthält: /api/battery_status, /api/system_info,
         /api/wattpilot/status, /api/wattpilot/history
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

        # Scheduler-State hinzufügen (wenn vorhanden)
        try:
            import json as _json
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
        except Exception as e:
            logging.warning(f"Scheduler-State nicht lesbar: {e}")

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

        # F2-Temperaturen (Fronius Symo 10.0, 192.168.2.123)
        try:
            import requests as _req2
            _f2_url = 'http://192.168.2.123/components/readable'
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
