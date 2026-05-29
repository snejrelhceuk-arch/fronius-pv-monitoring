"""Wattpilot-Status- und History-Endpunkte des system-Blueprints."""
import logging
import time
from datetime import datetime

from flask import jsonify, request

from routes.helpers import (
    get_db_connection,
    wattpilot_cache,
    api_error_response,
    validate_year_month,
)
from routes.system import bp
from routes.system._shared import _read_wattpilot_db_summary


@bp.route('/api/wattpilot/status')
def wattpilot_status():
    """Wattpilot-Status aus lokaler DB (mit 30s Cache, kein Live-WebSocket)."""
    now = time.time()

    # 30s Cache
    if wattpilot_cache['data'] and (now - wattpilot_cache['ts']) < 30:
        return jsonify(wattpilot_cache['data'])

    try:
        summary = _read_wattpilot_db_summary(now)
        wattpilot_cache['data'] = summary
        wattpilot_cache['ts'] = now
        return jsonify(summary)
    except Exception as e:
        logging.warning(f"Wattpilot-Status aus DB nicht verfügbar: {e}")
        if wattpilot_cache['data']:
            return jsonify(wattpilot_cache['data'])
        # Offline/Stale ist normaler Betriebszustand → 200 (nicht 500)
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
        valid, err = validate_year_month(year, month)
        if err:
            return err
        year, month = valid

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
        return api_error_response(e, "Wattpilot History")
