"""
Blueprint: Verbraucher-APIs (WP, Heizpatrone, Wattpilot, Haushalt).

Enthält: /api/verbraucher, /api/verbraucher/tag, /api/verbraucher/monat,
         /api/verbraucher/jahr, /api/verbraucher/gesamt
"""
import re
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from routes.helpers import get_db_connection, api_error_response, validate_year_month

bp = Blueprint('verbraucher', __name__)


def _load_wattpilot_daily(cursor, first_ts, last_ts):
    data = {}
    try:
        cursor.execute(
            """
            SELECT ts, energy_wh, max_power_w, charging_hours, sessions
            FROM wattpilot_daily
            WHERE ts >= ? AND ts < ?
            ORDER BY ts
            """,
            (first_ts, last_ts),
        )
        for row in cursor.fetchall():
            day_ts = (int(row[0]) // 86400) * 86400
            data[day_ts] = {
                'energy_wh': row[1] or 0,
                'max_power_w': row[2] or 0,
                'charging_hours': row[3] or 0,
                'sessions': row[4] or 0,
            }
    except Exception:
        pass
    return data


def _load_heizpatrone_daily(cursor, first_ts, last_ts):
    data = {}
    try:
        cursor.execute(
            """
            SELECT ts, energy_wh
            FROM heizpatrone_daily
            WHERE ts >= ? AND ts < ?
            ORDER BY ts
            """,
            (first_ts, last_ts),
        )
        for ts, energy_wh in cursor.fetchall():
            day_ts = (int(ts) // 86400) * 86400
            data[day_ts] = energy_wh or 0
    except Exception:
        pass

    # Fallback: Fehlende Tagessummen aus Fritz!DECT-Zaehler (energy_total_wh)
    # per Tagesdelta ermitteln. Manuelle Referenzwerte in heizpatrone_daily
    # haben Vorrang und werden nicht ueberschrieben.
    try:
        cursor.execute(
            """
            SELECT
                date(datetime(ts, 'unixepoch', 'localtime')) AS day_local,
                MIN(energy_total_wh) AS e_start,
                MAX(energy_total_wh) AS e_end
            FROM fritzdect_readings
            WHERE ts >= ? AND ts < ?
              AND (
                lower(COALESCE(device_id, '')) = 'heizpatrone'
                OR lower(COALESCE(name, '')) LIKE '%heiz%patrone%'
                OR lower(COALESCE(name, '')) LIKE '%sdheiz%'
              )
              AND energy_total_wh IS NOT NULL
            GROUP BY day_local
            """,
            (first_ts, last_ts),
        )
        for day_local, e_start, e_end in cursor.fetchall():
            if not day_local or e_start is None or e_end is None:
                continue
            delta_wh = max(0.0, float(e_end) - float(e_start))
            day_dt = datetime.strptime(day_local, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            day_ts = int(day_dt.timestamp())
            if day_ts not in data:
                data[day_ts] = delta_wh
    except Exception:
        pass

    return data


def _get_heizpatrone_month_total_kwh(cursor, year, month, first_ts, last_ts):
    try:
        cursor.execute(
            """
            SELECT energy_kwh
            FROM heizpatrone_monthly
            WHERE year = ? AND month = ?
            """,
            (year, month),
        )
        row = cursor.fetchone()
        if row and row[0] is not None:
            return float(row[0])
    except Exception:
        pass

    try:
        daily_by_day = _load_heizpatrone_daily(cursor, first_ts, last_ts)
        if daily_by_day:
            return float(sum(daily_by_day.values()) / 1000.0)
    except Exception:
        pass

    return 0.0


@bp.route('/api/verbraucher')
def verbraucher_chart():
    """
    Verbraucher-Aufschlüsselung für Monatsansicht.
    Zeigt den Gesamtverbrauch aufgeteilt nach:
    - Wärmepumpe (SmartMeter Unit 4)
    - Heizpatrone (Fritz!DECT)
    - Wattpilot/E-Auto (aus wattpilot_daily)
    - Haushalt/Rest (Differenz)
    """
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
        last_day = datetime(year + (1 if month == 12 else 0), (month % 12) + 1, 1)
        first_ts = int(first_day.timestamp())
        last_ts = int(last_day.timestamp())

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT ts,
                   W_WP_total,
                   W_Consumption_total,
                   W_PV_Direct_total,
                   W_Batt_Discharge_total,
                   W_Imp_Netz_total
            FROM daily_data
            WHERE ts >= ? AND ts < ?
            ORDER BY ts
            """,
            (first_ts, last_ts),
        )
        daily_rows = cursor.fetchall()

        wattpilot_by_day = _load_wattpilot_daily(cursor, first_ts, last_ts)
        heizpatrone_by_day = _load_heizpatrone_daily(cursor, first_ts, last_ts)
        heizpatrone_month_total = _get_heizpatrone_month_total_kwh(cursor, year, month, first_ts, last_ts)

        datapoints = []
        totals = {'wp': 0, 'heizpatrone': 0, 'wattpilot': 0, 'haushalt': 0, 'gesamt': 0}

        for row in daily_rows:
            ts, w_wp, w_consumption, w_direct, w_batt_dis, w_netz = row
            w_wp = w_wp or 0
            w_consumption = w_consumption or 0
            if w_consumption <= 0:
                w_consumption = (w_direct or 0) + (w_batt_dis or 0) + (w_netz or 0)

            day_key = (int(ts) // 86400) * 86400
            wattpilot_day = wattpilot_by_day.get(day_key, {})
            w_wattpilot = wattpilot_day.get('energy_wh', 0)
            w_heizpatrone = heizpatrone_by_day.get(day_key, 0)
            w_haushalt = max(0, w_consumption - w_wp - w_heizpatrone - w_wattpilot)

            wp_kwh = w_wp / 1000.0
            heizpatrone_kwh = w_heizpatrone / 1000.0
            wattpilot_kwh = w_wattpilot / 1000.0
            haushalt_kwh = w_haushalt / 1000.0
            gesamt_kwh = w_consumption / 1000.0

            totals['wp'] += wp_kwh
            totals['heizpatrone'] += heizpatrone_kwh
            totals['wattpilot'] += wattpilot_kwh
            totals['haushalt'] += haushalt_kwh
            totals['gesamt'] += gesamt_kwh

            datapoints.append({
                'timestamp': ts,
                'date': datetime.fromtimestamp(ts).strftime('%Y-%m-%d'),
                'day': datetime.fromtimestamp(ts).day,
                'w_waermepumpe': round(wp_kwh, 2),
                'w_heizpatrone': round(heizpatrone_kwh, 2),
                'w_wattpilot': round(wattpilot_kwh, 2),
                'w_haushalt': round(haushalt_kwh, 2),
                'w_gesamt': round(gesamt_kwh, 2),
                'wattpilot_sessions': wattpilot_day.get('sessions', 0),
                'wattpilot_max_power_w': wattpilot_day.get('max_power_w', 0),
                'wattpilot_charging_hours': round(wattpilot_day.get('charging_hours', 0), 1),
            })

        if heizpatrone_month_total > totals['heizpatrone']:
            totals['heizpatrone'] = heizpatrone_month_total
            totals['haushalt'] = max(
                0,
                totals['gesamt'] - totals['wp'] - totals['heizpatrone'] - totals['wattpilot'],
            )

        conn.close()

        return jsonify({
            'year': year,
            'month': month,
            'datapoints': datapoints,
            'totals': {k: round(v, 2) for k, v in totals.items()},
        })

    except Exception as e:
        return api_error_response(e, "Verbraucher-Chart")


@bp.route('/api/verbraucher/tag')
def api_verbraucher_tag():
    """
    Verbraucher-Leistungsübersicht für Tagesansicht (5-min-Intervall).
    WP = Wärmepumpe (P_WP_avg)
    Heizpatrone = derzeit ohne historische 5-min-Zeitreihe
    Wattpilot = E-Auto (aus wattpilot_readings)
    Haushalt = Gesamtverbrauch - WP - Heizpatrone - Wattpilot
    """
    try:
        date_param = request.args.get('date')
        if date_param and not re.match(r'^\d{4}-\d{2}-\d{2}$', date_param):
            return jsonify({"error": "Ungültiges Datumsformat"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500
        cursor = conn.cursor()

        if date_param:
            cursor.execute(
                """
                SELECT COUNT(*) FROM data_1min
                WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day')
                  AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')
                """,
                (date_param, date_param),
            )
            count_1min = cursor.fetchone()[0]
            table = 'data_1min' if count_1min > 0 else 'data_15min'
            where = "WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day') AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')"
            where_params = (date_param, date_param)
        else:
            cursor.execute(
                """
                SELECT COUNT(*) FROM data_1min
                WHERE datetime(ts, 'unixepoch', 'localtime') >= date('now', 'localtime', 'start of day')
                """
            )
            count_1min = cursor.fetchone()[0]
            table = 'data_1min' if count_1min > 0 else 'data_15min'
            date_param = datetime.now().strftime('%Y-%m-%d')
            where = "WHERE datetime(ts, 'unixepoch', 'localtime') >= date('now', 'localtime', 'start of day')"
            where_params = ()

        query = f"""
            SELECT
                CAST((ts / 300) AS INTEGER) * 300 AS ts5,
                AVG(COALESCE(-P_WP_avg, 0)) AS p_wp,
                AVG(COALESCE(P_Direct, 0) + COALESCE(P_outBatt, 0) +
                    CASE WHEN COALESCE(P_Netz_avg, 0) > 0 THEN P_Netz_avg ELSE 0 END) AS p_gesamt,
                SUM(COALESCE(W_Imp_WP_delta, 0)) AS w_wp,
                SUM(COALESCE(W_Direct, 0) + COALESCE(W_outBatt, 0) + COALESCE(W_Imp_Netz_delta, 0)) AS w_gesamt
            FROM {table}
            {where}
            GROUP BY CAST((ts / 300) AS INTEGER)
            ORDER BY ts5
        """
        cursor.execute(query, where_params)
        rows = cursor.fetchall()

        wattpilot_power_map = {}
        try:
            cursor.execute(
                f"""
                SELECT
                    CAST((ts / 300) AS INTEGER) * 300 AS ts5,
                    AVG(power_w) AS p_wp
                FROM wattpilot_readings
                {where}
                GROUP BY CAST((ts / 300) AS INTEGER)
                """,
                where_params,
            )
            for r in cursor.fetchall():
                wattpilot_power_map[int(r[0])] = max(0, r[1] or 0)
        except Exception:
            pass

        heizpatrone_power_map = {}
        try:
            cursor.execute(
                f"""
                SELECT
                    CAST((ts / 300) AS INTEGER) * 300 AS ts5,
                    AVG(power_w) AS p_hp
                FROM fritzdect_readings
                {where}
                  AND (
                    lower(COALESCE(device_id, '')) = 'heizpatrone'
                    OR lower(COALESCE(name, '')) LIKE '%heiz%patrone%'
                    OR lower(COALESCE(name, '')) LIKE '%sdheiz%'
                  )
                GROUP BY CAST((ts / 300) AS INTEGER)
                """,
                where_params,
            )
            for r in cursor.fetchall():
                heizpatrone_power_map[int(r[0])] = max(0, r[1] or 0)
        except Exception:
            pass

        conn.close()

        datapoints = []
        totals = {'wp': 0, 'heizpatrone': 0, 'wattpilot': 0, 'haushalt': 0, 'gesamt': 0}

        for row in rows:
            ts5, p_wp, p_gesamt, w_wp, w_gesamt = row
            p_wp = max(0, p_wp or 0)
            p_gesamt = max(0, p_gesamt or 0)
            w_wp = max(0, w_wp or 0)
            w_gesamt = max(0, w_gesamt or 0)

            p_heizpatrone = heizpatrone_power_map.get(int(ts5), 0)
            p_wattpilot = wattpilot_power_map.get(int(ts5), 0)
            p_sum = p_wp + p_heizpatrone + p_wattpilot
            if p_sum <= p_gesamt:
                p_haushalt = max(0, p_gesamt - p_sum)
                p_norm = p_gesamt
            else:
                # Bei Messdifferenzen auf Sensor-Summe normieren,
                # damit die Teilenergien nicht ueber dem Gesamtwert liegen.
                p_haushalt = 0
                p_norm = p_sum

            if p_norm > 0:
                w_heizpatrone = w_gesamt * (p_heizpatrone / p_norm)
                w_wattpilot = w_gesamt * (p_wattpilot / p_norm)
                w_haushalt = w_gesamt * (p_haushalt / p_norm)
                w_wp_actual = w_gesamt * (p_wp / p_norm)
            else:
                w_heizpatrone = 0
                w_wattpilot = 0
                w_haushalt = 0
                w_wp_actual = w_wp

            totals['wp'] += w_wp_actual
            totals['heizpatrone'] += w_heizpatrone
            totals['wattpilot'] += w_wattpilot
            totals['haushalt'] += w_haushalt
            totals['gesamt'] += w_gesamt

            datapoints.append({
                'timestamp': int(ts5),
                'p_wp': round(p_wp, 1),
                'p_heizpatrone': round(p_heizpatrone, 1),
                'p_wattpilot': round(p_wattpilot, 1),
                'p_haushalt': round(p_haushalt, 1),
                'p_gesamt': round(p_gesamt, 1),
            })

        return jsonify({
            'date': date_param,
            'datapoints': datapoints,
            'totals': {k: round(v / 1000, 2) for k, v in totals.items()},
        })

    except Exception as e:
        return api_error_response(e, "Verbraucher-Tag")


@bp.route('/api/verbraucher/monat')
def api_verbraucher_monat():
    """
    Verbraucher-Energieübersicht für Monatsansicht (gestapelte Balken pro Tag).
    Nutzt daily_data + wattpilot_daily + heizpatrone_daily.
    """
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        if not year or not month:
            now = datetime.now()
            year, month = now.year, now.month
        valid, err = validate_year_month(year, month)
        if err:
            return err
        year, month = valid

        first_day = datetime(year, month, 1)
        last_day = datetime(year + (1 if month == 12 else 0), (month % 12) + 1, 1)
        first_ts = int(first_day.timestamp())
        last_ts = int(last_day.timestamp())

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT ts, W_WP_total, W_Consumption_total,
                   W_PV_Direct_total, W_Batt_Discharge_total, W_Imp_Netz_total
            FROM daily_data
            WHERE ts >= ? AND ts < ?
            ORDER BY ts
            """,
            (first_ts, last_ts),
        )
        daily_rows = cursor.fetchall()

        wattpilot_by_day = _load_wattpilot_daily(cursor, first_ts, last_ts)
        heizpatrone_by_day = _load_heizpatrone_daily(cursor, first_ts, last_ts)
        heizpatrone_month_total = _get_heizpatrone_month_total_kwh(cursor, year, month, first_ts, last_ts)

        conn.close()

        datapoints = []
        totals = {'wp': 0, 'heizpatrone': 0, 'wattpilot': 0, 'haushalt': 0, 'gesamt': 0}

        for row in daily_rows:
            ts, w_wp, w_consumption, w_direct, w_batt_dis, w_netz = row
            w_wp = w_wp or 0
            w_consumption = w_consumption or 0
            if w_consumption <= 0:
                w_consumption = (w_direct or 0) + (w_batt_dis or 0) + (w_netz or 0)

            day_key = (int(ts) // 86400) * 86400
            w_wattpilot = wattpilot_by_day.get(day_key, {}).get('energy_wh', 0)
            w_heizpatrone = heizpatrone_by_day.get(day_key, 0)
            w_haushalt = max(0, w_consumption - w_wp - w_heizpatrone - w_wattpilot)

            wp_kwh = w_wp / 1000.0
            heizpatrone_kwh = w_heizpatrone / 1000.0
            wattpilot_kwh = w_wattpilot / 1000.0
            haushalt_kwh = w_haushalt / 1000.0
            gesamt_kwh = w_consumption / 1000.0

            totals['wp'] += wp_kwh
            totals['heizpatrone'] += heizpatrone_kwh
            totals['wattpilot'] += wattpilot_kwh
            totals['haushalt'] += haushalt_kwh
            totals['gesamt'] += gesamt_kwh

            datapoints.append({
                'day': datetime.fromtimestamp(ts).day,
                'w_wp': round(wp_kwh, 2),
                'w_heizpatrone': round(heizpatrone_kwh, 2),
                'w_wattpilot': round(wattpilot_kwh, 2),
                'w_haushalt': round(haushalt_kwh, 2),
                'w_gesamt': round(gesamt_kwh, 2),
            })

        if heizpatrone_month_total > totals['heizpatrone']:
            totals['heizpatrone'] = heizpatrone_month_total
            totals['haushalt'] = max(
                0,
                totals['gesamt'] - totals['wp'] - totals['heizpatrone'] - totals['wattpilot'],
            )

        return jsonify({
            'year': year,
            'month': month,
            'datapoints': datapoints,
            'totals': {k: round(v, 2) for k, v in totals.items()},
        })

    except Exception as e:
        return api_error_response(e, "Verbraucher-Monat")


@bp.route('/api/verbraucher/jahr')
def api_verbraucher_jahr():
    """Verbraucher-Energieübersicht für Jahresansicht (gestapelte Balken pro Monat)."""
    try:
        year = request.args.get('year', type=int)
        if not year:
            year = datetime.now().year
        valid, err = validate_year_month(year)
        if err:
            return err
        year, _ = valid

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT month, gesamt_verbrauch_kwh, waermepumpe_kwh, heizpatrone_kwh, wattpilot_kwh
            FROM monthly_statistics
            WHERE year = ?
            ORDER BY month
            """,
            (year,),
        )
        rows = cursor.fetchall()
        conn.close()

        datapoints = []
        totals = {'wp': 0, 'heizpatrone': 0, 'wattpilot': 0, 'haushalt': 0, 'gesamt': 0}

        for mon, gesamt, wp, heiz, wattpilot in rows:
            gesamt = gesamt or 0
            wp = wp or 0
            heiz = heiz or 0
            wattpilot = wattpilot or 0
            haushalt = max(0, gesamt - wp - heiz - wattpilot)

            totals['wp'] += wp
            totals['heizpatrone'] += heiz
            totals['wattpilot'] += wattpilot
            totals['haushalt'] += haushalt
            totals['gesamt'] += gesamt

            datapoints.append({
                'month': mon,
                'w_wp': round(wp, 2),
                'w_heizpatrone': round(heiz, 2),
                'w_wattpilot': round(wattpilot, 2),
                'w_haushalt': round(haushalt, 2),
                'w_gesamt': round(gesamt, 2),
            })

        return jsonify({
            'year': year,
            'datapoints': datapoints,
            'totals': {k: round(v, 2) for k, v in totals.items()},
        })

    except Exception as e:
        return api_error_response(e, "Verbraucher-Jahr")


@bp.route('/api/verbraucher/gesamt')
def api_verbraucher_gesamt():
    """Verbraucher-Energieübersicht Gesamtansicht (gestapelte Balken pro Jahr)."""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT year,
                   SUM(gesamt_verbrauch_kwh), SUM(waermepumpe_kwh),
                   SUM(heizpatrone_kwh), SUM(wattpilot_kwh)
            FROM monthly_statistics
            GROUP BY year
            ORDER BY year
            """
        )
        rows = cursor.fetchall()

        cursor.execute("SELECT MIN(year), MAX(year) FROM monthly_statistics")
        yr_range = cursor.fetchone()
        conn.close()

        datapoints = []
        totals = {'wp': 0, 'heizpatrone': 0, 'wattpilot': 0, 'haushalt': 0, 'gesamt': 0}

        for yr, gesamt, wp, heiz, wattpilot in rows:
            gesamt = gesamt or 0
            wp = wp or 0
            heiz = heiz or 0
            wattpilot = wattpilot or 0
            if gesamt < 1:
                continue
            haushalt = max(0, gesamt - wp - heiz - wattpilot)

            totals['wp'] += wp
            totals['heizpatrone'] += heiz
            totals['wattpilot'] += wattpilot
            totals['haushalt'] += haushalt
            totals['gesamt'] += gesamt

            datapoints.append({
                'year': yr,
                'label': str(yr),
                'w_wp': round(wp, 2),
                'w_heizpatrone': round(heiz, 2),
                'w_wattpilot': round(wattpilot, 2),
                'w_haushalt': round(haushalt, 2),
                'w_gesamt': round(gesamt, 2),
            })

        return jsonify({
            'datapoints': datapoints,
            'totals': {k: round(v, 2) for k, v in totals.items()},
            'year_range': [yr_range[0] or 2022, yr_range[1] or datetime.now().year],
        })

    except Exception as e:
        return api_error_response(e, "Verbraucher-Gesamt")
