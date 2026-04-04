"""
Blueprint: Netzqualitäts-APIs.

Enthält: /api/netzqualitaet/tag, /api/netzqualitaet/analyse
Liefert Leiterspannungen (L-L) und Netzfrequenz für die Netzqualitäts-Ansicht.
Datenquelle: data_1min (falls vorhanden), sonst Resampling aus raw_data.

ABCD-Rollenmodell: Säule B (read-only).
"""
import logging
import os
import sqlite3
from datetime import datetime
from flask import Blueprint, jsonify, request
from routes.helpers import get_db_connection, api_error_response
import config

bp = Blueprint('netzqualitaet', __name__)

NQ_DB_DIR = os.path.join(config.BASE_DIR, 'netzqualitaet', 'db')


@bp.route('/api/netzqualitaet/tag')
def api_netzqualitaet_tag():
    """Tagesansicht Netzqualität: Leiterspannungen L-L + Frequenz im 5-min-Raster.

    Parameter: ?date=YYYY-MM-DD (optional, default heute)
    Quelle: Ausschließlich raw_data (L-L-Spannungen, Phasenströme, Frequenz).
    """
    try:
        date_param = request.args.get('date')
        conn = get_db_connection()
        cursor = conn.cursor()

        # Zeitgrenzen bestimmen
        if date_param:
            where_clause = ("datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day') "
                            "AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')")
            params = (date_param, date_param)
        else:
            where_clause = "datetime(ts, 'unixepoch', 'localtime') >= date('now', 'localtime', 'start of day')"
            params = ()

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
            WHERE {where_clause}
            GROUP BY ts_bucket
            ORDER BY ts_bucket
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()

        datapoints = []
        for row in rows:
            dp = {
                'ts': row[0],
                'u_l1_l2': round(row[1], 1) if row[1] else None,
                'u_l2_l3': round(row[2], 1) if row[2] else None,
                'u_l3_l1': round(row[3], 1) if row[3] else None,
                'f_netz':  round(row[4], 3) if row[4] else None,
                'i_l1': round(row[5], 2) if row[5] is not None else None,
                'i_l2': round(row[6], 2) if row[6] is not None else None,
                'i_l3': round(row[7], 2) if row[7] is not None else None,
            }
            datapoints.append(dp)

        conn.close()

        return jsonify({
            'date': date_param or datetime.now().strftime('%Y-%m-%d'),
            'source': 'raw_data (5min)',
            'datapoints': datapoints
        })

    except Exception as e:
        logging.error(f"Netzqualität API Fehler: {e}")
        return api_error_response(e, "API netzqualitaet/tag")


@bp.route('/api/netzqualitaet/analyse')
def api_netzqualitaet_analyse():
    """15-min-Analyse-Overlay: Blockgrenzen + DFD-Events + Tageszusammenfassung.

    Parameter: ?date=YYYY-MM-DD (optional, default heute)
    Quelle: netzqualitaet/db/nq_YYYY-MM.db (aus nq_analysis.py)
    """
    try:
        date_param = request.args.get('date')
        if date_param:
            date_obj = datetime.strptime(date_param, '%Y-%m-%d')
        else:
            date_obj = datetime.now()
            date_param = date_obj.strftime('%Y-%m-%d')

        db_path = os.path.join(NQ_DB_DIR, f"nq_{date_obj.strftime('%Y-%m')}.db")
        if not os.path.exists(db_path):
            return jsonify({'date': date_param, 'available': False,
                            'boundaries': [], 'summary': None})

        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Boundary-Events des Tages
        cursor.execute(
            "SELECT boundary_ts, boundary_type, "
            "  ROUND(dfd_amplitude * 1000, 0) AS dfd_mHz, "
            "  ROUND(f_nadir, 3) AS f_nadir, "
            "  ROUND(f_nadir_offset_s, 0) AS nadir_offset_s, "
            "  ROUND(local_impact_score, 2) AS local_impact "
            "FROM nq_boundary_events "
            "WHERE date(datetime(boundary_ts, 'unixepoch', 'localtime')) = ? "
            "ORDER BY boundary_ts",
            (date_param,)
        )
        boundaries = [dict(row) for row in cursor.fetchall()]

        # Tageszusammenfassung
        cursor.execute(
            "SELECT * FROM nq_daily_summary WHERE date_str = ?",
            (date_param,)
        )
        summary_row = cursor.fetchone()
        summary = dict(summary_row) if summary_row else None

        conn.close()

        return jsonify({
            'date': date_param,
            'available': True,
            'boundaries': boundaries,
            'summary': summary
        })

    except Exception as e:
        logging.error(f"Netzqualität Analyse API Fehler: {e}")
        return api_error_response(e, "API netzqualitaet/analyse")
