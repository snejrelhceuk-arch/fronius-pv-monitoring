"""
Blueprint: Netzqualitäts-APIs.

Enthält: /api/netzqualitaet/tag
Liefert Leiterspannungen (L-L) und Netzfrequenz für die Netzqualitäts-Ansicht.
Datenquelle: data_1min (falls vorhanden), sonst Resampling aus raw_data.

ABCD-Rollenmodell: Säule B (read-only).
"""
import logging
from datetime import datetime
from flask import Blueprint, jsonify, request
from routes.helpers import get_db_connection, api_error_response

bp = Blueprint('netzqualitaet', __name__)


@bp.route('/api/netzqualitaet/tag')
def api_netzqualitaet_tag():
    """Tagesansicht Netzqualität: Leiterspannungen L-L + Frequenz im 5-min-Raster.

    Parameter: ?date=YYYY-MM-DD (optional, default heute)
    Quelle: Bevorzugt data_1min auf 5min resampelt, Fallback raw_data.
    """
    try:
        date_param = request.args.get('date')
        conn = get_db_connection()
        cursor = conn.cursor()

        # Zeitgrenzen bestimmen
        if date_param:
            where_1min = ("datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day') "
                          "AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')")
            params = (date_param, date_param)
        else:
            where_1min = "datetime(ts, 'unixepoch', 'localtime') >= date('now', 'localtime', 'start of day')"
            params = ()

        # Prüfe ob L-L-Spannungen in raw_data existieren (dort sind sie vorhanden)
        # data_1min hat nur L-N, deshalb gehen wir auf raw_data mit 5min-Resampling
        source = 'raw_data (5min)'
        query = f"""
            SELECT
                (CAST(ts AS INTEGER) / 300) * 300 AS ts_bucket,
                AVG(U_L1_L2_Netz) AS u_l1_l2,
                AVG(U_L2_L3_Netz) AS u_l2_l3,
                AVG(U_L3_L1_Netz) AS u_l3_l1,
                AVG(f_Netz)        AS f_netz,
                AVG(I_L1_Netz)     AS i_l1,
                AVG(I_L2_Netz)     AS i_l2,
                AVG(I_L3_Netz)     AS i_l3,
                COUNT(*)           AS n_samples
            FROM raw_data
            WHERE {where_1min}
            GROUP BY ts_bucket
            ORDER BY ts_bucket
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        # Falls keine Rohdaten (zu alt), Fallback auf data_1min mit L-N → approx L-L
        if not rows:
            source = 'data_1min (L-N approx)'
            query_fallback = f"""
                SELECT
                    (CAST(ts AS INTEGER) / 300) * 300 AS ts_bucket,
                    AVG(U_L1_N_Netz_avg) * 1.732 AS u_l1_l2,
                    AVG(U_L2_N_Netz_avg) * 1.732 AS u_l2_l3,
                    AVG(U_L3_N_Netz_avg) * 1.732 AS u_l3_l1,
                    AVG(f_Netz_avg)               AS f_netz,
                    NULL AS i_l1,
                    NULL AS i_l2,
                    NULL AS i_l3,
                    COUNT(*) AS n_samples
                FROM data_1min
                WHERE {where_1min}
                GROUP BY ts_bucket
                ORDER BY ts_bucket
            """
            cursor.execute(query_fallback, params)
            rows = cursor.fetchall()

        datapoints = []
        for row in rows:
            dp = {
                'ts': row[0],
                'u_l1_l2': round(row[1], 1) if row[1] else None,
                'u_l2_l3': round(row[2], 1) if row[2] else None,
                'u_l3_l1': round(row[3], 1) if row[3] else None,
                'f_netz':  round(row[4], 3) if row[4] else None,
            }
            # Ströme nur wenn vorhanden (Kontextsignal für lokale Kompensation)
            if row[5] is not None:
                dp['i_l1'] = round(row[5], 2)
                dp['i_l2'] = round(row[6], 2)
                dp['i_l3'] = round(row[7], 2)
            datapoints.append(dp)

        conn.close()

        return jsonify({
            'date': date_param or datetime.now().strftime('%Y-%m-%d'),
            'source': source,
            'datapoints': datapoints
        })

    except Exception as e:
        logging.error(f"Netzqualität API Fehler: {e}")
        return api_error_response(e, "API netzqualitaet/tag")
