"""
Blueprint: Erzeuger-APIs (DC-Strings F1, SmartMeter F2/F3).

Enthält: /api/erzeuger/tag, /api/erzeuger/monat, /api/erzeuger/jahr, /api/erzeuger/gesamt
"""
import re
import logging
from datetime import datetime
from flask import Blueprint, jsonify, request
from routes.helpers import get_db_connection, DB_FILE

bp = Blueprint('erzeuger', __name__)


@bp.route('/api/erzeuger/tag')
def api_erzeuger_tag():
    """
    Erzeuger-Leistungsübersicht für Tagesansicht (5-min-Intervall).
    F1 = P_DC1 + P_DC2 (Haupt-Inverter DC)
    F2 = P_F2 (SmartMeter)
    F3 = P_F3 (SmartMeter)
    """
    conn = None
    try:
        date_param = request.args.get('date')  # Format: YYYY-MM-DD
        if date_param and not re.match(r'^\d{4}-\d{2}-\d{2}$', date_param):
            return jsonify({"error": "Ungültiges Datumsformat"}), 400

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500
        cursor = conn.cursor()

        # Bestimme Tabelle: data_1min oder data_15min
        if date_param:
            cursor.execute("""
                SELECT COUNT(*) FROM data_1min
                WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day')
                  AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')
            """, (date_param, date_param))
            count_1min = cursor.fetchone()[0]
            table = 'data_1min' if count_1min > 0 else 'data_15min'
            where = "WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day') AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')"
            where_params = (date_param, date_param)
        else:
            cursor.execute("""
                SELECT COUNT(*) FROM data_1min
                WHERE datetime(ts, 'unixepoch', 'localtime') >= date('now', 'localtime', 'start of day')
            """)
            count_1min = cursor.fetchone()[0]
            table = 'data_1min' if count_1min > 0 else 'data_15min'
            date_param = datetime.now().strftime('%Y-%m-%d')
            where = "WHERE datetime(ts, 'unixepoch', 'localtime') >= date('now', 'localtime', 'start of day')"
            where_params = ()

        # Aggregiere auf 5-Minuten-Intervalle
        query = f"""
            SELECT
                CAST((ts / 300) AS INTEGER) * 300 AS ts5,
                AVG(COALESCE(P_DC1_avg, 0) + COALESCE(P_DC2_avg, 0)) AS p_f1,
                AVG(COALESCE(P_F2_avg, 0)) AS p_f2,
                AVG(COALESCE(P_F3_avg, 0)) AS p_f3,
                SUM(COALESCE(W_DC1_delta, 0) + COALESCE(W_DC2_delta, 0)) AS w_f1,
                SUM(-COALESCE(W_Exp_F2_delta, 0)) AS w_f2,
                SUM(-COALESCE(W_Exp_F3_delta, 0)) AS w_f3
            FROM {table}
            {where}
            GROUP BY CAST((ts / 300) AS INTEGER)
            ORDER BY ts5
        """
        cursor.execute(query, where_params)
        rows = cursor.fetchall()

        datapoints = []
        totals = {'f1': 0, 'f2': 0, 'f3': 0, 'gesamt': 0}

        for row in rows:
            ts5, p_f1, p_f2, p_f3, w_f1, w_f2, w_f3 = row
            # Nur positive Leistung (Erzeugung), Standby-Verbrauch ausblenden
            p_f1 = max(0, p_f1 or 0)
            p_f2 = max(0, p_f2 or 0)
            p_f3 = max(0, p_f3 or 0)
            w_f1 = max(0, w_f1 or 0)
            w_f2 = max(0, w_f2 or 0)
            w_f3 = max(0, w_f3 or 0)

            totals['f1'] += w_f1
            totals['f2'] += w_f2
            totals['f3'] += w_f3
            totals['gesamt'] += w_f1 + w_f2 + w_f3

            datapoints.append({
                'timestamp': int(ts5),
                'p_f1': round(p_f1, 1),
                'p_f2': round(p_f2, 1),
                'p_f3': round(p_f3, 1),
                'p_gesamt': round(p_f1 + p_f2 + p_f3, 1),
            })

        # Totals in kWh — try counter-based (exact) first
        counter_totals = None
        try:
            if date_param:
                ct_query = """
                    SELECT
                        (MAX(W_DC1) - MIN(W_DC1)) / 1000.0,
                        (MAX(W_DC2) - MIN(W_DC2)) / 1000.0,
                        (MAX(W_Exp_F2) - MIN(W_Exp_F2)) / 1000.0,
                        (MAX(W_Exp_F3) - MIN(W_Exp_F3)) / 1000.0,
                        COUNT(*)
                    FROM raw_data
                    WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day')
                      AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')
                """
                cursor.execute(ct_query, (date_param, date_param))
            else:
                ct_query = """
                    SELECT
                        (MAX(W_DC1) - MIN(W_DC1)) / 1000.0,
                        (MAX(W_DC2) - MIN(W_DC2)) / 1000.0,
                        (MAX(W_Exp_F2) - MIN(W_Exp_F2)) / 1000.0,
                        (MAX(W_Exp_F3) - MIN(W_Exp_F3)) / 1000.0,
                        COUNT(*)
                    FROM raw_data
                    WHERE datetime(ts, 'unixepoch', 'localtime') >= date('now', 'localtime', 'start of day')
                """
                cursor.execute(ct_query)
            ct_row = cursor.fetchone()
            if ct_row and ct_row[4] and ct_row[4] > 100:
                dc1, dc2, f2, f3, cnt = ct_row
                dc1 = dc1 or 0; dc2 = dc2 or 0; f2 = f2 or 0; f3 = f3 or 0
                counter_totals = {
                    'f1': round(dc1 + dc2, 2),
                    'f2': round(f2, 2),
                    'f3': round(f3, 2),
                    'gesamt': round(dc1 + dc2 + f2 + f3, 2),
                }
        except Exception as e:
            logging.warning(f"Erzeuger Counter-Totals Fehler: {e}")

        result = {
            'date': date_param,
            'datapoints': datapoints,
            'totals': counter_totals or {k: round(v / 1000, 2) for k, v in totals.items()}
        }

        return jsonify(result)

    except Exception as e:
        logging.error(f"Erzeuger-Tag Fehler: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()


@bp.route('/api/erzeuger/monat')
def api_erzeuger_monat():
    """
    Erzeuger-Energieübersicht für Monatsansicht (gestapelte Balken pro Tag).
    Aggregiert aus data_1min / data_15min.
    """
    try:
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)
        if not year or not month:
            now = datetime.now()
            year, month = now.year, now.month

        first_day = datetime(year, month, 1)
        last_day = datetime(year + (1 if month == 12 else 0), (month % 12) + 1, 1)
        first_ts = int(first_day.timestamp())
        last_ts = int(last_day.timestamp())

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500
        cursor = conn.cursor()

        # Prüfe data_1min Verfügbarkeit
        cursor.execute("SELECT COUNT(*) FROM data_1min WHERE ts >= ? AND ts < ?", (first_ts, last_ts))
        count = cursor.fetchone()[0]
        table = 'data_1min' if count > 0 else 'data_15min'

        cursor.execute(f"""
            SELECT
                date(ts, 'unixepoch', 'localtime') AS day,
                SUM(COALESCE(W_DC1_delta, 0) + COALESCE(W_DC2_delta, 0)) AS w_f1,
                SUM(-COALESCE(W_Exp_F2_delta, 0)) AS w_f2,
                SUM(-COALESCE(W_Exp_F3_delta, 0)) AS w_f3
            FROM {table}
            WHERE ts >= ? AND ts < ?
            GROUP BY date(ts, 'unixepoch', 'localtime')
            ORDER BY day
        """, (first_ts, last_ts))

        rows = cursor.fetchall()
        conn.close()

        datapoints = []
        totals = {'f1': 0, 'f2': 0, 'f3': 0, 'gesamt': 0}

        for day_str, w_f1, w_f2, w_f3 in rows:
            w_f1 = max(0, (w_f1 or 0)) / 1000  # in kWh
            w_f2 = max(0, (w_f2 or 0)) / 1000
            w_f3 = max(0, (w_f3 or 0)) / 1000

            totals['f1'] += w_f1
            totals['f2'] += w_f2
            totals['f3'] += w_f3
            totals['gesamt'] += w_f1 + w_f2 + w_f3

            day_num = int(day_str.split('-')[2])
            datapoints.append({
                'date': day_str,
                'day': day_num,
                'w_f1': round(w_f1, 2),
                'w_f2': round(w_f2, 2),
                'w_f3': round(w_f3, 2),
                'w_gesamt': round(w_f1 + w_f2 + w_f3, 2),
            })

        return jsonify({
            'year': year, 'month': month,
            'datapoints': datapoints,
            'totals': {k: round(v, 2) for k, v in totals.items()}
        })

    except Exception as e:
        logging.error(f"Erzeuger-Monat Fehler: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route('/api/erzeuger/jahr')
def api_erzeuger_jahr():
    """
    Erzeuger-Energieübersicht für Jahresansicht (gestapelte Balken pro Monat).
    Gesamtsummen aus monthly_statistics (korrekte Referenzwerte inkl. SolarWeb-Backfill),
    F1/F2/F3-Aufteilung proportional aus data_1min / data_15min skaliert.
    """
    try:
        year = request.args.get('year', type=int)
        if not year:
            year = datetime.now().year

        first_ts = int(datetime(year, 1, 1).timestamp())
        last_ts = int(datetime(year + 1, 1, 1).timestamp())

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500
        cursor = conn.cursor()

        # ── Korrekte Monatssummen aus monthly_statistics (in Wh) ──
        cursor.execute("""
            SELECT month, COALESCE(solar_erzeugung_kwh, 0)
            FROM monthly_statistics
            WHERE year = ?
            ORDER BY month
        """, (year,))
        stat_totals = {row[0]: row[1] * 1000.0 for row in cursor.fetchall()}

        # ── F1/F2/F3-Aufteilung aus Rohdaten (für Proportionsberechnung) ──
        cursor.execute("SELECT COUNT(*) FROM data_1min WHERE ts >= ? AND ts < ?", (first_ts, last_ts))
        count = cursor.fetchone()[0]
        table = 'data_1min' if count > 0 else 'data_15min'

        cursor.execute(f"""
            SELECT
                CAST(strftime('%m', datetime(ts, 'unixepoch', 'localtime')) AS INTEGER) AS mon,
                SUM(COALESCE(W_DC1_delta, 0) + COALESCE(W_DC2_delta, 0)) AS w_f1,
                SUM(-COALESCE(W_Exp_F2_delta, 0)) AS w_f2,
                SUM(-COALESCE(W_Exp_F3_delta, 0)) AS w_f3
            FROM {table}
            WHERE ts >= ? AND ts < ?
            GROUP BY mon
            ORDER BY mon
        """, (first_ts, last_ts))

        rows = cursor.fetchall()
        conn.close()

        MONTHS = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
        datapoints = []
        totals = {'f1': 0, 'f2': 0, 'f3': 0, 'gesamt': 0}

        for mon, w_f1, w_f2, w_f3 in rows:
            w_f1 = max(0.0, (w_f1 or 0.0))
            w_f2 = max(0.0, (w_f2 or 0.0))
            w_f3 = max(0.0, (w_f3 or 0.0))
            raw_sum = w_f1 + w_f2 + w_f3

            # monthly_statistics ist die autoritative Quelle (enthält SolarWeb-Korrekturen).
            # F1/F2/F3 werden proportional auf die korrekte Gesamtmenge skaliert.
            if mon in stat_totals and stat_totals[mon] > 0:
                total_wh = stat_totals[mon]
                if raw_sum > 0:
                    scale = total_wh / raw_sum
                    w_f1 *= scale
                    w_f2 *= scale
                    w_f3 *= scale
                else:
                    w_f1 = total_wh
                    w_f2 = 0.0
                    w_f3 = 0.0
            # Kein monthly_statistics-Eintrag → Rohdaten direkt verwenden

            w_f1 /= 1000.0
            w_f2 /= 1000.0
            w_f3 /= 1000.0

            totals['f1'] += w_f1
            totals['f2'] += w_f2
            totals['f3'] += w_f3
            totals['gesamt'] += w_f1 + w_f2 + w_f3

            datapoints.append({
                'month': mon,
                'label': MONTHS[mon - 1],
                'w_f1': round(w_f1, 2),
                'w_f2': round(w_f2, 2),
                'w_f3': round(w_f3, 2),
                'w_gesamt': round(w_f1 + w_f2 + w_f3, 2),
            })

        return jsonify({
            'year': year,
            'datapoints': datapoints,
            'totals': {k: round(v, 2) for k, v in totals.items()}
        })

    except Exception as e:
        logging.error(f"Erzeuger-Jahr Fehler: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route('/api/erzeuger/gesamt')
def api_erzeuger_gesamt():
    """
    Erzeuger-Energieübersicht Gesamtansicht (gestapelte Balken pro Jahr).
    Aggregiert aus data_1min / data_15min.
    """
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500
        cursor = conn.cursor()

        # Versuche beide Tabellen zu kombinieren
        cursor.execute("SELECT COUNT(*) FROM data_1min")
        count_1min = cursor.fetchone()[0]
        table = 'data_1min' if count_1min > 0 else 'data_15min'

        cursor.execute(f"""
            SELECT
                CAST(strftime('%Y', datetime(ts, 'unixepoch', 'localtime')) AS INTEGER) AS yr,
                SUM(COALESCE(W_DC1_delta, 0) + COALESCE(W_DC2_delta, 0)) AS w_f1,
                SUM(-COALESCE(W_Exp_F2_delta, 0)) AS w_f2,
                SUM(-COALESCE(W_Exp_F3_delta, 0)) AS w_f3
            FROM {table}
            GROUP BY yr
            ORDER BY yr
        """)

        rows = cursor.fetchall()

        # Jahr-Bereich aus monthly_statistics ermitteln (enthält auch ältere Jahre)
        cursor.execute("SELECT MIN(year), MAX(year) FROM monthly_statistics")
        yr_range_row = cursor.fetchone()
        conn.close()

        current_year = datetime.now().year
        min_year = yr_range_row[0] if yr_range_row and yr_range_row[0] else current_year
        max_year = max(yr_range_row[1] if yr_range_row and yr_range_row[1] else current_year, current_year)

        datapoints = []
        totals = {'f1': 0, 'f2': 0, 'f3': 0, 'gesamt': 0}

        for yr, w_f1, w_f2, w_f3 in rows:
            w_f1 = max(0, (w_f1 or 0)) / 1000
            w_f2 = max(0, (w_f2 or 0)) / 1000
            w_f3 = max(0, (w_f3 or 0)) / 1000

            totals['f1'] += w_f1
            totals['f2'] += w_f2
            totals['f3'] += w_f3
            totals['gesamt'] += w_f1 + w_f2 + w_f3

            datapoints.append({
                'year': yr,
                'label': str(yr),
                'w_f1': round(w_f1, 2),
                'w_f2': round(w_f2, 2),
                'w_f3': round(w_f3, 2),
                'w_gesamt': round(w_f1 + w_f2 + w_f3, 2),
            })

        return jsonify({
            'datapoints': datapoints,
            'totals': {k: round(v, 2) for k, v in totals.items()},
            'year_range': [min_year, max_year]
        })

    except Exception as e:
        logging.error(f"Erzeuger-Gesamt Fehler: {e}")
        return jsonify({"error": str(e)}), 500
