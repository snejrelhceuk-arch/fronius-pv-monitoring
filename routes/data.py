"""
Blueprint: Roh- und aggregierte Daten-APIs.

Enthält: /api/15min, /api/hourly, /api/daily, /api/monthly, /api/yearly,
         /api/data_15min, /api/data_hourly, /api/data_daily, /api/data_monthly
"""
from flask import Blueprint, jsonify, request
from routes.helpers import get_db_connection

bp = Blueprint('data', __name__)


@bp.route('/api/15min')
def api_15min():
    """15-Minuten-Daten"""
    try:
        days = min(request.args.get('days', 7, type=int), 365)
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()
            modifier = f'-{days} days'
            c.execute("SELECT * FROM data_15min WHERE ts >= strftime('%s', 'now', ?) ORDER BY ts ASC", (modifier,))

            rows = c.fetchall()
            cols = [d[0] for d in c.description]
        finally:
            conn.close()

        data = [dict(zip(cols, row)) for row in rows]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/api/hourly')
def api_hourly():
    """Stunden-Daten"""
    try:
        hours = min(request.args.get('hours', 168, type=int), 8760)
        weeks = request.args.get('weeks', 0, type=int)

        if weeks > 0:
            hours = min(weeks * 168, 8760)

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()
            modifier = f'-{hours} hours'
            c.execute("SELECT * FROM hourly_data WHERE ts >= strftime('%s', 'now', ?) ORDER BY ts ASC", (modifier,))

            rows = c.fetchall()
            cols = [d[0] for d in c.description]
        finally:
            conn.close()

        data = [dict(zip(cols, row)) for row in rows]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/api/daily')
def api_daily():
    """Tages-Daten (aggregiert aus data_15min für aktuellen Monat)"""
    try:
        start = request.args.get('start', type=int)
        end = request.args.get('end', type=int)

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()

            # Aggregiere data_15min zu Tagen
            query = """
                SELECT
                    strftime('%s', datetime(ts, 'unixepoch', 'start of day')) as ts,
                    AVG(P_Netz_avg) as p_Grid_avg,
                    AVG(P_AC_Inv_avg) as p_PV_avg,
                    0 as p_Akku_avg,
                    AVG(P_AC_Inv_avg) as p_Load_avg,
                    AVG(f_Netz_avg) as freq_avg,
                    SUM(CASE WHEN P_Netz_avg > 0 THEN P_Netz_avg*0.25/1000.0 ELSE 0 END) as energy_grid_kwh,
                    SUM(P_AC_Inv_avg*0.25/1000.0) as energy_pv_kwh,
                    0 as energy_battery_kwh,
                    SUM(P_AC_Inv_avg*0.25/1000.0) as energy_load_kwh
                FROM data_15min
            """

            if start and end:
                query += " WHERE ts >= ? AND ts <= ?"
                c.execute(query + " GROUP BY strftime('%Y-%m-%d', datetime(ts, 'unixepoch')) ORDER BY ts ASC", (start, end))
            else:
                c.execute(query + " GROUP BY strftime('%Y-%m-%d', datetime(ts, 'unixepoch')) ORDER BY ts ASC")

            rows = c.fetchall()
            cols = [d[0] for d in c.description]
        finally:
            conn.close()

        data = [dict(zip(cols, row)) for row in rows]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/api/monthly')
def api_monthly():
    """Monats-Daten (aus monthly_statistics)"""
    try:
        start = request.args.get('start', type=int)
        end = request.args.get('end', type=int)

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()
            # Konvertiere year/month zu ts (1. des Monats)
            query = """
                SELECT
                    strftime('%s', year || '-' || printf('%02d', month) || '-01') as ts,
                    solar_erzeugung_kwh as p_PV_avg,
                    netz_bezug_kwh as p_Grid_avg,
                    gesamt_verbrauch_kwh as p_Load_avg,
                    batt_ladung_kwh as p_Akku_avg,
                    50.0 as freq_avg,
                    solar_erzeugung_kwh as energy_pv_kwh,
                    netz_bezug_kwh as energy_grid_kwh,
                    gesamt_verbrauch_kwh as energy_load_kwh,
                    batt_ladung_kwh as energy_battery_kwh
                FROM monthly_statistics
            """

            if start and end:
                query += " WHERE strftime('%s', year || '-' || printf('%02d', month) || '-01') >= ? AND strftime('%s', year || '-' || printf('%02d', month) || '-01') <= ?"
                c.execute(query + " ORDER BY year, month ASC", (start, end))
            else:
                c.execute(query + " ORDER BY year, month ASC")

            rows = c.fetchall()
            cols = [d[0] for d in c.description]
        finally:
            conn.close()

        data = [dict(zip(cols, row)) for row in rows]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/api/yearly')
def api_yearly():
    """Jahres-Daten (aus yearly_statistics)"""
    try:
        start = request.args.get('start', type=int)
        end = request.args.get('end', type=int)

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()
            # Konvertiere year zu ts (1. Januar)
            query = """
                SELECT
                    strftime('%s', year || '-01-01') as ts,
                    solar_erzeugung_kwh as p_PV_avg,
                    netz_bezug_kwh as p_Grid_avg,
                    gesamt_verbrauch_kwh as p_Load_avg,
                    batt_ladung_kwh as p_Akku_avg,
                    50.0 as freq_avg,
                    solar_erzeugung_kwh as energy_pv_kwh,
                    netz_bezug_kwh as energy_grid_kwh,
                    gesamt_verbrauch_kwh as energy_load_kwh,
                    batt_ladung_kwh as energy_battery_kwh
                FROM yearly_statistics
            """

            if start and end:
                query += " WHERE strftime('%s', year || '-01-01') >= ? AND strftime('%s', year || '-01-01') <= ?"
                c.execute(query + " ORDER BY year ASC", (start, end))
            else:
                c.execute(query + " ORDER BY year ASC")

            rows = c.fetchall()
            cols = [d[0] for d in c.description]
        finally:
            conn.close()

        data = [dict(zip(cols, row)) for row in rows]
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/api/data_15min')
def api_data_15min():
    """15-Minuten aggregierte Daten für einen bestimmten Zeitraum"""
    try:
        # Parameter: date (YYYY-MM-DD), optional start_hour/end_hour
        date_str = request.args.get('date', '2026-01-01')
        start_hour = request.args.get('start_hour', type=int)
        end_hour = request.args.get('end_hour', type=int)

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()

            # Zeitbereich festlegen
            if start_hour is not None and end_hour is not None:
                start_datetime = f"{date_str} {start_hour:02d}:00:00"
                end_datetime = f"{date_str} {end_hour:02d}:00:00"
            else:
                # Ganzer Tag
                start_datetime = f"{date_str} 00:00:00"
                end_datetime = f"{date_str} 23:59:59"

            # ALLE Spalten aus data_15min in DB-Reihenfolge
            query = """
                SELECT
                    datetime(ts, 'unixepoch', 'localtime') as Zeit,
                    ts,
                    P_AC_Inv_avg, P_AC_Inv_min, P_AC_Inv_max,
                    I_L1_Inv_avg, I_L1_Inv_min, I_L1_Inv_max,
                    I_L2_Inv_avg, I_L2_Inv_min, I_L2_Inv_max,
                    I_L3_Inv_avg, I_L3_Inv_min, I_L3_Inv_max,
                    U_L1_N_Inv_avg, U_L1_N_Inv_min, U_L1_N_Inv_max,
                    U_L2_N_Inv_avg, U_L2_N_Inv_min, U_L2_N_Inv_max,
                    U_L3_N_Inv_avg, U_L3_N_Inv_min, U_L3_N_Inv_max,
                    P_DC_Inv_avg, P_DC_Inv_min, P_DC_Inv_max,
                    P_DC1_avg, P_DC1_min, P_DC1_max,
                    P_DC2_avg, P_DC2_min, P_DC2_max,
                    SOC_Batt_avg, SOC_Batt_min, SOC_Batt_max,
                    U_Batt_API_avg, U_Batt_API_min, U_Batt_API_max,
                    I_Batt_API_avg, I_Batt_API_min, I_Batt_API_max,
                    P_Netz_avg, P_Netz_min, P_Netz_max,
                    f_Netz_avg, f_Netz_min, f_Netz_max,
                    U_L1_N_Netz_avg, U_L1_N_Netz_min, U_L1_N_Netz_max,
                    U_L2_N_Netz_avg, U_L2_N_Netz_min, U_L2_N_Netz_max,
                    U_L3_N_Netz_avg, U_L3_N_Netz_min, U_L3_N_Netz_max,
                    P_F2_avg, P_F2_min, P_F2_max,
                    P_F3_avg, P_F3_min, P_F3_max,
                    P_WP_avg, P_WP_min, P_WP_max,
                    W_PV_total_delta,
                    W_DC1_delta,
                    W_DC2_delta,
                    W_Exp_Netz_delta,
                    W_Imp_Netz_delta,
                    W_Exp_F2_delta,
                    W_Imp_F2_delta,
                    W_Exp_F3_delta,
                    W_Imp_F3_delta,
                    W_Exp_WP_delta,
                    W_Imp_WP_delta
                FROM data_15min
                WHERE datetime(ts, 'unixepoch', 'localtime') >= ?
                  AND datetime(ts, 'unixepoch', 'localtime') <= ?
                ORDER BY ts ASC
            """

            c.execute(query, (start_datetime, end_datetime))
            rows = c.fetchall()
            cols = [d[0] for d in c.description]
        finally:
            conn.close()

        data = [dict(zip(cols, row)) for row in rows]

        # Statistik
        if data:
            stats = {
                'anzahl_messwerte': len(data),
                'anzahl_spalten': len(data[0]) if data else 0,
                'zeitraum': f"{start_datetime} bis {end_datetime}",
                'pv_avg': round(sum(row.get('P_AC_Inv_avg', 0) or 0 for row in data) / len(data), 1) if data else 0,
                'pv_max': round(max((row.get('P_AC_Inv_max', 0) or 0 for row in data), default=0), 1),
                'netz_avg': round(sum(row.get('P_Netz_avg', 0) or 0 for row in data) / len(data), 1) if data else 0,
                'soc_avg': round(sum(row.get('SOC_Batt_avg', 0) or 0 for row in data) / len(data), 1) if data else 0
            }
        else:
            stats = {
                'anzahl_messwerte': 0,
                'anzahl_spalten': 0,
                'zeitraum': f"{start_datetime} bis {end_datetime}",
                'message': 'Keine Daten im angegebenen Zeitraum'
            }

        return jsonify({
            'stats': stats,
            'data': data
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/api/data_hourly')
def api_data_hourly():
    """Stündliche aggregierte Daten für einen bestimmten Zeitraum"""
    try:
        # Parameter: date (YYYY-MM-DD), optional start_hour/end_hour
        date_str = request.args.get('date', '2026-01-01')
        start_hour = request.args.get('start_hour', type=int)
        end_hour = request.args.get('end_hour', type=int)

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()

            # Zeitbereich festlegen
            if start_hour is not None and end_hour is not None:
                start_datetime = f"{date_str} {start_hour:02d}:00:00"
                end_datetime = f"{date_str} {end_hour:02d}:00:00"
            else:
                # Ganzer Tag
                start_datetime = f"{date_str} 00:00:00"
                end_datetime = f"{date_str} 23:59:59"

            # ALLE Spalten aus hourly_data in DB-Reihenfolge
            query = """
                SELECT
                    datetime(ts, 'unixepoch', 'localtime') as Zeit,
                    ts,
                    P_AC_Inv_avg, P_AC_Inv_min, P_AC_Inv_max,
                    P_DC_Inv_avg, P_DC_Inv_min, P_DC_Inv_max,
                    P_DC1_avg, P_DC1_min, P_DC1_max,
                    P_DC2_avg, P_DC2_min, P_DC2_max,
                    SOC_Batt_avg, SOC_Batt_min, SOC_Batt_max,
                    U_Batt_API_avg, U_Batt_API_min, U_Batt_API_max,
                    I_Batt_API_avg, I_Batt_API_min, I_Batt_API_max,
                    P_Netz_avg, P_Netz_min, P_Netz_max,
                    f_Netz_avg, f_Netz_min, f_Netz_max,
                    P_F2_avg, P_F2_min, P_F2_max,
                    P_F3_avg, P_F3_min, P_F3_max,
                    P_WP_avg, P_WP_min, P_WP_max,
                    W_PV_total_delta,
                    W_Exp_Netz_delta,
                    W_Imp_Netz_delta
                FROM hourly_data
                WHERE datetime(ts, 'unixepoch', 'localtime') >= ?
                  AND datetime(ts, 'unixepoch', 'localtime') <= ?
                ORDER BY ts ASC
            """

            c.execute(query, (start_datetime, end_datetime))
            rows = c.fetchall()
            cols = [d[0] for d in c.description]
        finally:
            conn.close()

        data = [dict(zip(cols, row)) for row in rows]

        # Statistik
        if data:
            stats = {
                'anzahl_messwerte': len(data),
                'anzahl_spalten': len(data[0]) if data else 0,
                'zeitraum': f"{start_datetime} bis {end_datetime}",
                'pv_avg': round(sum(row.get('P_AC_Inv_avg', 0) or 0 for row in data) / len(data), 1) if data else 0,
                'pv_max': round(max((row.get('P_AC_Inv_max', 0) or 0 for row in data), default=0), 1),
                'netz_avg': round(sum(row.get('P_Netz_avg', 0) or 0 for row in data) / len(data), 1) if data else 0,
                'soc_avg': round(sum(row.get('SOC_Batt_avg', 0) or 0 for row in data) / len(data), 1) if data else 0
            }
        else:
            stats = {
                'anzahl_messwerte': 0,
                'anzahl_spalten': 0,
                'zeitraum': f"{start_datetime} bis {end_datetime}",
                'message': 'Keine Daten im angegebenen Zeitraum'
            }

        return jsonify({
            'stats': stats,
            'data': data
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/api/data_daily')
def api_data_daily():
    """Tägliche aggregierte Daten"""
    try:
        start_date = request.args.get('start_date', '2025-12-01')
        end_date = request.args.get('end_date', '2026-01-31')

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()
            query = """
                SELECT
                    datetime(ts, 'unixepoch', 'localtime') as Zeit,
                    ts,
                    P_AC_Inv_avg, P_AC_Inv_min, P_AC_Inv_max,
                    f_Netz_avg, f_Netz_min, f_Netz_max,
                    P_Netz_avg, P_Netz_min, P_Netz_max,
                    P_F2_avg, P_F2_min, P_F2_max,
                    P_F3_avg, P_F3_min, P_F3_max,
                    SOC_Batt_avg, SOC_Batt_min, SOC_Batt_max,
                    W_PV_total, W_Exp_Netz_total, W_Imp_Netz_total, W_Consumption_total
                FROM daily_data
                WHERE date(datetime(ts, 'unixepoch', 'localtime')) >= ?
                  AND date(datetime(ts, 'unixepoch', 'localtime')) <= ?
                ORDER BY ts ASC
            """
            c.execute(query, (start_date, end_date))
            rows = c.fetchall()
            cols = [d[0] for d in c.description]
        finally:
            conn.close()

        data = [dict(zip(cols, row)) for row in rows]
        stats = {'anzahl_messwerte': len(data), 'anzahl_spalten': len(data[0]) if data else 0}
        return jsonify({'stats': stats, 'data': data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/api/data_monthly')
def api_data_monthly():
    """Monatliche aggregierte Daten"""
    try:
        start_date = request.args.get('start_date', '2025-01-01')
        end_date = request.args.get('end_date', '2026-12-31')

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()
            query = """
                SELECT
                    datetime(ts, 'unixepoch', 'localtime') as Zeit,
                    ts,
                    W_PV_total_delta, W_DC1_delta, W_DC2_delta,
                    W_Exp_Netz_delta, W_Imp_Netz_delta,
                    W_Exp_F2_delta, W_Imp_F2_delta,
                    W_Exp_F3_delta, W_Imp_F3_delta,
                    W_Exp_WP_delta, W_Imp_WP_delta,
                    W_Bat_Charge_delta, W_Bat_Discharge_delta,
                    f_Netz_min, f_Netz_max, f_Netz_avg,
                    P_AC_Inv_min, P_AC_Inv_max, P_AC_Inv_avg,
                    P_DC_Inv_min, P_DC_Inv_max, P_DC_Inv_avg,
                    P_DC1_min, P_DC1_max, P_DC1_avg,
                    P_DC2_min, P_DC2_max, P_DC2_avg,
                    SOC_Batt_min, SOC_Batt_max, SOC_Batt_avg,
                    P_Netz_min, P_Netz_max, P_Netz_avg,
                    U_L1_N_Netz_min, U_L1_N_Netz_max, U_L1_N_Netz_avg,
                    U_L2_N_Netz_min, U_L2_N_Netz_max, U_L2_N_Netz_avg,
                    U_L3_N_Netz_min, U_L3_N_Netz_max, U_L3_N_Netz_avg,
                    P_F2_min, P_F2_max, P_F2_avg,
                    P_F3_min, P_F3_max, P_F3_avg,
                    P_WP_min, P_WP_max, P_WP_avg
                FROM data_monthly
                WHERE date(datetime(ts, 'unixepoch', 'localtime')) >= ?
                  AND date(datetime(ts, 'unixepoch', 'localtime')) <= ?
                ORDER BY ts ASC
            """
            c.execute(query, (start_date, end_date))
            rows = c.fetchall()
            cols = [d[0] for d in c.description]
        finally:
            conn.close()

        data = [dict(zip(cols, row)) for row in rows]
        stats = {'anzahl_messwerte': len(data), 'anzahl_spalten': len(data[0]) if data else 0}
        return jsonify({'stats': stats, 'data': data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
