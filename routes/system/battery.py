"""Batterie- und Flow-Status-Endpunkte des system-Blueprints.

Enthaelt den eng gekoppelten Cluster rund um /api/battery_status und
/api/flow_status: Fronius-Basiswerte, Batterieenergie, BMS-Counter,
Temperaturen, Schaltlog (HP/Klima), WP-Status sowie die Aggregations-
funktionen ``_build_battery_status_result`` / ``_build_flow_status_result``.

Automation-State/Phasen werden aus ``routes.system.automation`` bezogen.
"""
import logging
import os
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path

from flask import jsonify

import config
from routes.helpers import (
    get_db_connection,
    get_fronius_api,
    battery_cache,
    api_error_response,
)
from routes.system import bp
from routes.system.automation import _fetch_automation_state

# Repo-Root: routes/system/battery.py -> parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Fritz!DECT Live-Status Cache (eigener, längerer TTL als battery_cache)
_fritzdect_cache = {'ts': 0, 'data': None}
_FRITZDECT_CACHE_TTL = 120  # 2 Minuten (Fritz!Box ist langsam, 1 Bulk-Request ~2s)
_flow_cache = {'ts': 0, 'data': None}

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

    result['pv_forecast_emoji'] = '❓'
    result['pv_forecast_quality'] = None
    result['pv_forecast_expected_kwh'] = None
    result['pv_forecast_clearsky_kwh'] = None
    result['pv_forecast_ratio_pct'] = None

    # PV-Prognose-Emoji und Qualität ergänzen
    try:
        from routes.helpers import get_forecast, get_stored_forecast
        from solar_geometry import SolarGeometry

        target_date = date.today()
        target_date_str = target_date.isoformat()
        day_fc = None
        forecast = get_forecast()
        if forecast:
            day_fc = forecast.get_day_forecast(target_date)

        # Fallback: gespeicherte Prognose für heute nutzen, wenn Live-Forecast fehlt.
        if not day_fc:
            day_fc = get_stored_forecast(target_date_str)

        if day_fc:
            expected_kwh = day_fc.get('expected_kwh') if day_fc else None
            clearsky_kwh = day_fc.get('clearsky_kwh') if day_fc else None
            ratio_pct = None

            if clearsky_kwh is None:
                try:
                    cs_curve = SolarGeometry().get_clearsky_day_curve(target_date, interval_min=15)
                    if cs_curve:
                        total_wh = 0.0
                        for point in cs_curve:
                            total_ac = point.get('total_ac', 0) or 0
                            total_wh += max(0.0, float(total_ac)) * 0.25
                        if total_wh > 0:
                            clearsky_kwh = round(total_wh / 1000.0, 1)
                except Exception as cs_err:
                    logging.debug(f"PV-ClearSky für Flow-Status nicht verfügbar: {cs_err}")

            quality = day_fc.get('quality') if day_fc else None
            if expected_kwh is not None and clearsky_kwh and clearsky_kwh > 0:
                ratio_pct = (float(expected_kwh) / float(clearsky_kwh)) * 100.0
                if ratio_pct < 40.0:
                    quality = 'schlecht'
                elif ratio_pct < 70.0:
                    quality = 'mittel'
                else:
                    quality = 'gut'

            # Emoji-Mapping wie in solar_forecast.py
            def _quality_emoji(quality):
                return {'gut': '☀️', 'mittel': '⛅', 'schlecht': '☁️'}.get(quality, '❓')
            emoji = _quality_emoji(quality)
            result['pv_forecast_emoji'] = emoji
            result['pv_forecast_quality'] = quality
            result['pv_forecast_expected_kwh'] = round(float(expected_kwh), 1) if expected_kwh is not None else None
            result['pv_forecast_clearsky_kwh'] = clearsky_kwh
            result['pv_forecast_ratio_pct'] = round(ratio_pct, 1) if ratio_pct is not None else None
    except Exception as e:
        logging.warning(f"PV-Prognose-Emoji konnte nicht geladen werden: {e}")

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
        return api_error_response(e)


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
        return api_error_response(e)


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


def _fetch_last_soc_switch(result):
    """Letzte SOC-Umschaltung aus automation_log."""
    try:
        _persist_db = str(_REPO_ROOT / 'data.db')
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
            _checkpoint_path = _REPO_ROOT / 'config' / 'battery_bms_checkpoints.json'
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

    # F2 (Gen24 10kW)
    try:
        import requests as _req2
        _f2_api = config.load_local_setting('PV_SECONDARY_INVERTER_API', 'http://192.0.2.123/components/readable')
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
    """Schaltprotokoll der letzten 24h aus schaltlog.txt (von Schicht C geschrieben).

    Liefert HP-, Klima-, WP-Sollwert- und Batt-SOC-Schaltvorgänge.
    Doppel-Logging (ENGINE Steuerbox-Override + EXTERN-Detection desselben
    physischen Schaltvorgangs) wird unterdrückt: EXTERN-Einträge die innerhalb
    ±DOUBLET_WINDOW_S zu einem ENGINE-Event mit "Steuerbox Override"-Grund
    passen, werden als Duplikat verworfen.
    """
    import re as _re_hp
    DOUBLET_WINDOW_S = 120  # ±2 Min: Übergangs-Fenster für ENGINE/EXTERN-Doppel
    BATT_DEDUP_WINDOW_S = 90  # gleiche EXTERN-Drift mehrfach geloggt → entdoppeln
    cutoff_24h = now - 86400

    def _parse_ts(_d, _t):
        try:
            return time.mktime(time.strptime(f'{_d} {_t}', '%Y-%m-%d %H:%M:%S'))
        except Exception:
            return None

    try:
        _schaltlog_path = str(_REPO_ROOT / 'logs' / 'schaltlog.txt')

        _hp_engine_pat = _re_hp.compile(
            r'^\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'ENGINE\s+fritzdect\s+(hp_ein|hp_aus)\S*\s+(OK|FEHLER)\s*(.*)')
        _klima_engine_pat = _re_hp.compile(
            r'^\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'ENGINE\s+fritzdect\s+(klima_ein|klima_aus)\S*\s+(OK|FEHLER)\s*(.*)')
        _hp_extern_pat = _re_hp.compile(
            r'^\s*~?\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'EXTERN\s+fritzdect\s+HP\s+extern\s+(EIN|AUS)\s+--\s*(.*)',
            _re_hp.IGNORECASE)
        _klima_extern_pat = _re_hp.compile(
            r'^\s*~?\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'EXTERN\s+fritzdect\s+Klima\s+extern\s+(EIN|AUS)\s+--\s*(.*)',
            _re_hp.IGNORECASE)
        _wp_engine_pat = _re_hp.compile(
            r'^\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'ENGINE\s+waermepumpe\s+(set_ww_soll|set_heiz_soll)=(\S+)\s+'
            r'(OK|FEHLER)\s*(.*)')
        _batt_engine_pat = _re_hp.compile(
            r'^\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'ENGINE\s+batterie\s+(set_soc_min|set_soc_max|set_soc_mode)=(\S+)\s+'
            r'(OK|FEHLER)\s*(.*)')
        _batt_extern_pat = _re_hp.compile(
            r'^\s*~?\s*(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2})\s+'
            r'EXTERN\s+batterie\s+(SOC_MIN|SOC_MAX|SOC_MODE)\s+(\S+)\s+--\s*(.*)',
            _re_hp.IGNORECASE)

        # Phase 1: Roh-Events (im 24h-Fenster) sammeln
        hp_events, klima_events = [], []
        wp_events, batt_events = [], []

        if os.path.exists(_schaltlog_path):
            with open(_schaltlog_path, 'r') as _slf:
                for _line in _slf:
                    _m = _hp_engine_pat.match(_line)
                    if _m:
                        _d, _t, _cmd, _erg, _g = _m.groups()
                        _ep = _parse_ts(_d, _t)
                        if _ep is not None and _ep >= cutoff_24h:
                            hp_events.append({
                                'epoch': _ep, 'ts': f'{_d} {_t[:5]}',
                                'kommando': _cmd, 'wert': '',
                                'grund': (_g or '').strip()[:120],
                                'ergebnis': _erg, 'quelle': 'automation',
                            })
                        continue
                    _m = _klima_engine_pat.match(_line)
                    if _m:
                        _d, _t, _cmd, _erg, _g = _m.groups()
                        _ep = _parse_ts(_d, _t)
                        if _ep is not None and _ep >= cutoff_24h:
                            klima_events.append({
                                'epoch': _ep, 'ts': f'{_d} {_t[:5]}',
                                'kommando': _cmd, 'wert': '',
                                'grund': (_g or '').strip()[:120],
                                'ergebnis': _erg, 'quelle': 'automation',
                            })
                        continue
                    _m = _hp_extern_pat.match(_line)
                    if _m:
                        _d, _t, _state, _g = _m.groups()
                        _ep = _parse_ts(_d, _t)
                        if _ep is not None and _ep >= cutoff_24h:
                            _cmd = 'hp_ein' if _state.upper() == 'EIN' else 'hp_aus'
                            hp_events.append({
                                'epoch': _ep, 'ts': f'{_d} {_t[:5]}',
                                'kommando': _cmd, 'wert': '',
                                'grund': (_g or 'Manuell/extern').strip()[:120],
                                'ergebnis': 'EXTERN', 'quelle': 'extern',
                            })
                        continue
                    _m = _klima_extern_pat.match(_line)
                    if _m:
                        _d, _t, _state, _g = _m.groups()
                        _ep = _parse_ts(_d, _t)
                        if _ep is not None and _ep >= cutoff_24h:
                            _cmd = 'klima_ein' if _state.upper() == 'EIN' else 'klima_aus'
                            klima_events.append({
                                'epoch': _ep, 'ts': f'{_d} {_t[:5]}',
                                'kommando': _cmd, 'wert': '',
                                'grund': (_g or 'Manuell/extern').strip()[:120],
                                'ergebnis': 'EXTERN', 'quelle': 'extern',
                            })
                        continue
                    _m = _wp_engine_pat.match(_line)
                    if _m:
                        _d, _t, _cmd, _wert, _erg, _g = _m.groups()
                        _ep = _parse_ts(_d, _t)
                        if _ep is not None and _ep >= cutoff_24h and _erg == 'OK':
                            wp_events.append({
                                'epoch': _ep, 'ts': f'{_d} {_t[:5]}',
                                'kommando': _cmd, 'wert': _wert,
                                'grund': (_g or '').strip()[:120],
                                'ergebnis': _erg, 'quelle': 'automation',
                            })
                        continue
                    _m = _batt_engine_pat.match(_line)
                    if _m:
                        _d, _t, _cmd, _wert, _erg, _g = _m.groups()
                        _ep = _parse_ts(_d, _t)
                        if _ep is not None and _ep >= cutoff_24h:
                            batt_events.append({
                                'epoch': _ep, 'ts': f'{_d} {_t[:5]}',
                                'kommando': _cmd, 'wert': _wert.strip('"'),
                                'grund': (_g or '').strip()[:120],
                                'ergebnis': _erg, 'quelle': 'automation',
                            })
                        continue
                    _m = _batt_extern_pat.match(_line)
                    if _m:
                        _d, _t, _key, _val, _g = _m.groups()
                        _ep = _parse_ts(_d, _t)
                        if _ep is not None and _ep >= cutoff_24h:
                            _cmd_map = {'SOC_MIN': 'set_soc_min',
                                        'SOC_MAX': 'set_soc_max',
                                        'SOC_MODE': 'set_soc_mode'}
                            batt_events.append({
                                'epoch': _ep, 'ts': f'{_d} {_t[:5]}',
                                'kommando': _cmd_map.get(_key.upper(), 'extern'),
                                'wert': _val,
                                'grund': (_g or 'Drift erkannt').strip()[:120],
                                'ergebnis': 'EXTERN', 'quelle': 'extern',
                            })
                        continue

        # Phase 2: Doublet-Filter (ENGINE-Schreibvorgang + EXTERN-Drift-Detect
        # desselben physischen Vorgangs, von C zweifach geloggt). EXTERN-Eintrag
        # verwerfen, wenn ein ENGINE-OK-Eintrag für denselben Aktor/Kommando
        # innerhalb ±DOUBLET_WINDOW_S existiert. Damit fallen sowohl
        # Steuerbox-Override-Echos als auch Drift-Echos der C-Aktoren weg.
        def _filter_doublets(events, eng_cmd_pairs):
            """eng_cmd_pairs: dict {extern_cmd: matching_engine_cmd} (für Übersetzung)."""
            engine_oks = [
                e for e in events
                if e['quelle'] == 'automation' and e['ergebnis'] == 'OK'
            ]
            out = []
            for ev in events:
                if ev['quelle'] == 'extern':
                    matching_cmd = eng_cmd_pairs.get(ev['kommando'], ev['kommando'])
                    is_doublet = any(
                        eng['kommando'] == matching_cmd
                        and abs(eng['epoch'] - ev['epoch']) <= DOUBLET_WINDOW_S
                        for eng in engine_oks
                    )
                    if is_doublet:
                        continue
                out.append(ev)
            return out

        hp_events = _filter_doublets(hp_events, {'hp_ein': 'hp_ein', 'hp_aus': 'hp_aus'})
        klima_events = _filter_doublets(klima_events,
                                        {'klima_ein': 'klima_ein', 'klima_aus': 'klima_aus'})
        # Batt: EXTERN matcht generisch auf set_soc_min/max/mode mit gleichem kommando
        batt_events = _filter_doublets(batt_events, {})
        # Zusätzlich: EXTERN-Drift-Echos entdoppeln (gleicher kommando+wert
        # innerhalb BATT_DEDUP_WINDOW_S → nur den ersten behalten)
        batt_events.sort(key=lambda e: e['epoch'])
        _last_seen = {}
        _dedup = []
        for ev in batt_events:
            if ev['quelle'] == 'extern':
                _k = (ev['kommando'], ev['wert'])
                if _k in _last_seen and (ev['epoch'] - _last_seen[_k]) <= BATT_DEDUP_WINDOW_S:
                    continue
                _last_seen[_k] = ev['epoch']
            _dedup.append(ev)
        batt_events = _dedup

        # Phase 3: Sortierung (neueste zuerst) und Begrenzung
        for _lst in (hp_events, klima_events, wp_events, batt_events):
            _lst.sort(key=lambda e: e['epoch'], reverse=True)
        # epoch-Feld nicht ans Frontend
        def _strip(lst, n=120):
            return [{k: v for k, v in e.items() if k != 'epoch'} for e in lst[:n]]

        result['hp_aktionen'] = _strip(hp_events)
        result['klima_aktionen'] = _strip(klima_events)
        result['wp_aktionen'] = _strip(wp_events)
        result['batt_aktionen'] = _strip(batt_events)
        result['hp_bursts_heute'] = sum(
            1 for a in hp_events
            if a['kommando'] == 'hp_ein' and a['ergebnis'] == 'OK'
            and a['epoch'] >= now - 86400)

    except Exception as _he:
        logging.debug(f"Schaltlog-Parse: {_he}")
        result['hp_aktionen'] = []
        result['klima_aktionen'] = []
        result['hp_bursts_heute'] = 0
        result['wp_aktionen'] = []
        result['batt_aktionen'] = []

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

    # Klima-Status: Live-Power (klima_w aus fritzdect_readings, schon im result)
    # + letzter Schaltvorgang aus klima_aktionen
    try:
        _klima_w = result.get('klima_w', 0) or 0
        _klima_akt = result.get('klima_aktionen', [])
        _last_klima = _klima_akt[0] if _klima_akt else {}
        # Schwelle 5W: Stand-by/Geist-Power vermeiden
        if _klima_w >= 5:
            _zustand = 'EIN'
        elif _klima_w is not None:
            _zustand = 'AUS'
        else:
            _zustand = '?'
        # Schaltfrequenz-Cooldown aus RAM-DB engine_flags lesen (ABCD-konform: B liest RAM-DB)
        _cd_aktiv = False
        _cd_verbleibt_s = 0
        _cd_bis_iso = None
        try:
            _ram_db = '/dev/shm/automation_obs.db'
            with sqlite3.connect(_ram_db, timeout=2.0) as _edb:
                _erow = _edb.execute(
                    "SELECT value FROM engine_flags WHERE key='klima_cooldown_bis'"
                ).fetchone()
            if _erow:
                _cd_bis_epoch = float(_erow[0])
                if _cd_bis_epoch > time.time():
                    _cd_aktiv = True
                    _cd_verbleibt_s = int(_cd_bis_epoch - time.time())
                    from datetime import datetime as _dt
                    _cd_bis_iso = _dt.fromtimestamp(_cd_bis_epoch).strftime('%H:%M')
        except Exception:
            pass
        result['klima_status'] = {
            'zustand': _zustand,
            'live': True,
            'power_w': round(_klima_w, 1),
            'seit': _last_klima.get('ts'),
            'grund': _last_klima.get('grund', ''),
            'kommando': _last_klima.get('kommando'),
            'quelle_letzte': _last_klima.get('quelle'),
            'cooldown_aktiv': _cd_aktiv,
            'cooldown_verbleibt_s': _cd_verbleibt_s,
            'cooldown_bis': _cd_bis_iso,
        }
    except Exception as _kle:
        logging.debug(f"Klima-Status: {_kle}")
        result['klima_status'] = {
            'zustand': '?', 'live': False, 'seit': None,
            'grund': '', 'kommando': None, 'quelle_letzte': None,
            'cooldown_aktiv': False, 'cooldown_verbleibt_s': 0, 'cooldown_bis': None,
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
                    'heiz_soll': 'wp_heiz_soll_c',
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
        _batt_cfg_path = os.path.join(str(_REPO_ROOT), 'config', 'battery_control.json')
        with open(_batt_cfg_path, 'r') as _f:
            _batt_cfg = _json2.load(_f)
        result['soh'] = float(_batt_cfg.get('batterie', {}).get('soh_prozent', 92.0))
        result['soh_source'] = 'config_fallback'
    except Exception:
        result['soh'] = 92.0
        result['soh_source'] = 'default'
