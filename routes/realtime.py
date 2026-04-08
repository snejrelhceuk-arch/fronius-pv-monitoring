"""
Blueprint: Echtzeit- und Zoom-APIs.

Enthält: /api/zoom, /api/realtime_smart, /api/bulk_load,
         /api/zoom_compressed, /api/flow_realtime, /api/polling_data
"""
import sqlite3
import logging
import os
import time
from datetime import date
from flask import Blueprint, jsonify, request
from routes.helpers import get_db_connection, ram_db_lock, api_error_response

bp = Blueprint('realtime', __name__)


@bp.route('/api/zoom')
def api_zoom():
    """Adaptive Auflösung basierend auf Zeitbereich - ALLE Spalten"""
    try:
        start = request.args.get('start', type=int)  # Unix timestamp
        end = request.args.get('end', type=int)      # Unix timestamp

        if not start or not end:
            return jsonify({"error": "start und end erforderlich"}), 400

        duration_seconds = end - start
        duration_hours = duration_seconds / 3600

        # Nutze RAM-DB wenn verfügbar
        with ram_db_lock:
            conn = get_db_connection()
            if not conn:
                return jsonify({"error": "DB Error"}), 500

            try:
                c = conn.cursor()

                # Strategie basierend auf Zeitbereich
                # Für Echtzeit (72h): Jeden 2. Punkt (~26.000 Punkte)
                if duration_hours > 168:  # >7 Tage: 15min-Auflösung (data_15min hat nicht alle Spalten!)
                    # HINWEIS: Für >7d nutzen wir raw_data mit stärkerer Reduktion
                    c.execute("""
                        WITH numbered AS (
                            SELECT ts, ChaSt_Batt, f_Netz, I_Batt_API, I_DC1, I_DC2,
                                   I_L1_Inv, I_L1_Netz, I_L2_Inv, I_L2_Netz, I_L3_Inv, I_L3_Netz, I_Netz,
                                   P_AC_Inv, P_DC1, P_DC2, P_DC_Inv, P_F2, P_F3,
                                   PF_F2, PF_F3, PF_Inv, PF_Netz, PF_WP,
                                   P_L1_F2, P_L1_F3, P_L1_Netz, P_L1_WP,
                                   P_L2_F2, P_L2_F3, P_L2_Netz, P_L2_WP,
                                   P_L3_F2, P_L3_F3, P_L3_Netz, P_L3_WP,
                                   P_Netz, P_WP,
                                   Q_F2, Q_F3, Q_Inv, Q_Netz, Q_WP,
                                   S_F2, S_F3, S_Inv, S_Netz, S_WP, SOC_Batt,
                                   t_poll_ms,
                                   U_Batt_API, U_DC1, U_DC2,
                                   U_L1_L2_Inv, U_L1_L2_Netz, U_L1_N_Inv, U_L1_N_Netz,
                                   U_L2_L3_Inv, U_L2_L3_Netz, U_L2_N_Inv, U_L2_N_Netz,
                                   U_L3_L1_Inv, U_L3_L1_Netz, U_L3_N_Inv, U_L3_N_Netz, U_Netz,
                                   W_AC_Inv, W_DC1, W_DC2,
                                   W_Exp_F2, W_Exp_F3, W_Exp_Netz,
                                   W_Imp_F2, W_Imp_F3, W_Imp_Netz, W_Imp_WP,
                                   ROW_NUMBER() OVER (ORDER BY ts) as rn
                            FROM raw_data
                            WHERE ts >= ? AND ts <= ?
                        )
                        SELECT ts, ChaSt_Batt, f_Netz, I_Batt_API, I_DC1, I_DC2,
                               I_L1_Inv, I_L1_Netz, I_L2_Inv, I_L2_Netz, I_L3_Inv, I_L3_Netz, I_Netz,
                               P_AC_Inv, P_DC1, P_DC2, P_DC_Inv, P_F2, P_F3,
                               PF_F2, PF_F3, PF_Inv, PF_Netz, PF_WP,
                               P_L1_F2, P_L1_F3, P_L1_Netz, P_L1_WP,
                               P_L2_F2, P_L2_F3, P_L2_Netz, P_L2_WP,
                               P_L3_F2, P_L3_F3, P_L3_Netz, P_L3_WP,
                               P_Netz, P_WP,
                               Q_F2, Q_F3, Q_Inv, Q_Netz, Q_WP,
                               S_F2, S_F3, S_Inv, S_Netz, S_WP, SOC_Batt,
                               t_poll_ms,
                               U_Batt_API, U_DC1, U_DC2,
                               U_L1_L2_Inv, U_L1_L2_Netz, U_L1_N_Inv, U_L1_N_Netz,
                               U_L2_L3_Inv, U_L2_L3_Netz, U_L2_N_Inv, U_L2_N_Netz,
                               U_L3_L1_Inv, U_L3_L1_Netz, U_L3_N_Inv, U_L3_N_Netz, U_Netz,
                               W_AC_Inv, W_DC1, W_DC2,
                               W_Exp_F2, W_Exp_F3, W_Exp_Netz,
                               W_Imp_F2, W_Imp_F3, W_Imp_Netz, W_Imp_WP
                        FROM numbered
                        WHERE rn % 30 = 1
                        ORDER BY ts ASC
                    """, (start, end))
                    resolution = "~5min"

                else:  # <=7 Tage: Jeden 2. raw_data Punkt (gleichmäßig) - ALLE SPALTEN
                    c.execute("""
                        WITH numbered AS (
                            SELECT ts, ChaSt_Batt, f_Netz, I_Batt_API, I_DC1, I_DC2,
                                   I_L1_Inv, I_L1_Netz, I_L2_Inv, I_L2_Netz, I_L3_Inv, I_L3_Netz, I_Netz,
                                   P_AC_Inv, P_DC1, P_DC2, P_DC_Inv, P_F2, P_F3,
                                   PF_F2, PF_F3, PF_Inv, PF_Netz, PF_WP,
                                   P_L1_F2, P_L1_F3, P_L1_Netz, P_L1_WP,
                                   P_L2_F2, P_L2_F3, P_L2_Netz, P_L2_WP,
                                   P_L3_F2, P_L3_F3, P_L3_Netz, P_L3_WP,
                                   P_Netz, P_WP,
                                   Q_F2, Q_F3, Q_Inv, Q_Netz, Q_WP,
                                   S_F2, S_F3, S_Inv, S_Netz, S_WP, SOC_Batt,
                                   t_poll_ms,
                                   U_Batt_API, U_DC1, U_DC2,
                                   U_L1_L2_Inv, U_L1_L2_Netz, U_L1_N_Inv, U_L1_N_Netz,
                                   U_L2_L3_Inv, U_L2_L3_Netz, U_L2_N_Inv, U_L2_N_Netz,
                                   U_L3_L1_Inv, U_L3_L1_Netz, U_L3_N_Inv, U_L3_N_Netz, U_Netz,
                                   W_AC_Inv, W_DC1, W_DC2,
                                   W_Exp_F2, W_Exp_F3, W_Exp_Netz,
                                   W_Imp_F2, W_Imp_F3, W_Imp_Netz, W_Imp_WP,
                                   ROW_NUMBER() OVER (ORDER BY ts) as rn
                            FROM raw_data
                            WHERE ts >= ? AND ts <= ?
                        )
                        SELECT ts, ChaSt_Batt, f_Netz, I_Batt_API, I_DC1, I_DC2,
                               I_L1_Inv, I_L1_Netz, I_L2_Inv, I_L2_Netz, I_L3_Inv, I_L3_Netz, I_Netz,
                               P_AC_Inv, P_DC1, P_DC2, P_DC_Inv, P_F2, P_F3,
                               PF_F2, PF_F3, PF_Inv, PF_Netz, PF_WP,
                               P_L1_F2, P_L1_F3, P_L1_Netz, P_L1_WP,
                               P_L2_F2, P_L2_F3, P_L2_Netz, P_L2_WP,
                               P_L3_F2, P_L3_F3, P_L3_Netz, P_L3_WP,
                               P_Netz, P_WP,
                               Q_F2, Q_F3, Q_Inv, Q_Netz, Q_WP,
                               S_F2, S_F3, S_Inv, S_Netz, S_WP, SOC_Batt,
                               t_poll_ms,
                               U_Batt_API, U_DC1, U_DC2,
                               U_L1_L2_Inv, U_L1_L2_Netz, U_L1_N_Inv, U_L1_N_Netz,
                               U_L2_L3_Inv, U_L2_L3_Netz, U_L2_N_Inv, U_L2_N_Netz,
                               U_L3_L1_Inv, U_L3_L1_Netz, U_L3_N_Inv, U_L3_N_Netz, U_Netz,
                               W_AC_Inv, W_DC1, W_DC2,
                               W_Exp_F2, W_Exp_F3, W_Exp_Netz,
                               W_Imp_F2, W_Imp_F3, W_Imp_Netz, W_Imp_WP
                        FROM numbered
                        WHERE rn % 2 = 1
                        ORDER BY ts ASC
                    """, (start, end))
                    resolution = "~10s"

                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            finally:
                if conn:
                    conn.close()

        data = [dict(zip(cols, row)) for row in rows]
        return jsonify({
            "data": data,
            "resolution": resolution,
            "points": len(data),
            "duration_hours": round(duration_hours, 2)
        })
    except Exception as e:
        return api_error_response(e)


@bp.route('/api/realtime_smart')
def api_realtime_smart():
    """
    Smart Sampling für Echtzeit-Ansicht mit progressivem Zoom

    WAL-analog für Reads (zweistufiges Cache-System):
    - Echtzeit-Cache (15s refresh): Letzte 60min aus raw_data → kein DB-Lock!
    - Haupt-RAM-DB (5min refresh): Historische Daten → minimal Locks
    - Fallback auf data_1min für ältere Daten

    Progressive Auflösung: 300s (5min) → 150s (2.5min) → 60s (1min) → 30s → 3s
    """
    try:
        # Parameter
        hours = min(max(request.args.get('hours', type=float, default=24.0), 0.001), 168)
        resolution = max(request.args.get('resolution', type=int, default=300), 3)
        start_ts = request.args.get('start', type=int)
        end_ts = request.args.get('end', type=int)

        # Zeitfenster berechnen
        if start_ts and end_ts and start_ts < end_ts:
            start = start_ts
            end = end_ts
            hours = (end - start) / 3600
        else:
            if end_ts:
                end = end_ts
            else:
                end = int(time.time())

            start = end - int(hours * 3600)

        # tmpfs-DB: Direkt lesen — immer frisch, kein Cache nötig
        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()

            # Prüfe raw_data Verfügbarkeit
            c.execute("SELECT MIN(ts), MAX(ts) FROM raw_data")
            raw_result = c.fetchone()
            raw_min, raw_max = raw_result if raw_result else (None, None)

            # Entscheide: raw_data oder data_1min
            use_raw_data = (
                raw_min and raw_max and
                not (end < raw_min or start > raw_max)
            )

            if use_raw_data:
                if start < raw_min:
                    start = int(raw_min)
                if end > raw_max:
                    end = int(raw_max)

            if use_raw_data:
                # Smart Sampling aus raw_data (RAM-DB, alle 5min aktualisiert)
                c.execute("""
                    WITH numbered AS (
                        SELECT ts,
                               ChaSt_Batt, f_Netz,
                               I_Batt_API, I_DC1, I_DC2,
                               I_L1_Inv, I_L1_Netz, I_L2_Inv, I_L2_Netz, I_L3_Inv, I_L3_Netz, I_Netz,
                               P_AC_Inv, P_DC1, P_DC2, P_DC_Inv, P_F2, P_F3,
                               PF_F2, PF_F3, PF_Inv, PF_Netz, PF_WP,
                               P_L1_F2, P_L1_F3, P_L1_Netz, P_L1_WP,
                               P_L2_F2, P_L2_F3, P_L2_Netz, P_L2_WP,
                               P_L3_F2, P_L3_F3, P_L3_Netz, P_L3_WP,
                               P_Netz, P_WP,
                               Q_F2, Q_F3, Q_Inv, Q_Netz, Q_WP,
                               S_F2, S_F3, S_Inv, S_Netz, S_WP,
                               SOC_Batt, t_poll_ms,
                               U_Batt_API, U_DC1, U_DC2, U_Netz,
                               U_L1_L2_Inv, U_L1_L2_Netz, U_L1_N_Inv, U_L1_N_Netz,
                               U_L2_L3_Inv, U_L2_L3_Netz, U_L2_N_Inv, U_L2_N_Netz,
                               U_L3_L1_Inv, U_L3_L1_Netz, U_L3_N_Inv, U_L3_N_Netz,
                               W_AC_Inv, W_DC1, W_DC2,
                               W_Exp_F2, W_Exp_F3, W_Exp_Netz,
                               W_Imp_F2, W_Imp_F3, W_Imp_Netz, W_Imp_WP,
                               ROW_NUMBER() OVER (
                                   PARTITION BY CAST(ts / ? AS INTEGER)
                                   ORDER BY ts
                               ) as rn
                        FROM raw_data
                        WHERE ts >= ? AND ts <= ?
                    )
                    SELECT * FROM numbered WHERE rn = 1
                    ORDER BY ts ASC
                """, (resolution, start, end))

                source = "tmpfs_raw"

            else:
                # Fallback auf data_1min
                if resolution < 60:
                    resolution = 60

                c.execute("""
                    SELECT
                        CAST(ts / ? AS INTEGER) * ? as ts,
                        AVG(P_AC_Inv_avg) as P_AC_Inv,
                        AVG(P_DC_Inv_avg) as P_DC_Inv,
                        AVG(P_DC1_avg) as P_DC1,
                        AVG(P_DC2_avg) as P_DC2,
                        AVG(P_F2_avg) as P_F2,
                        AVG(P_F3_avg) as P_F3,
                        AVG(P_Netz_avg) as P_Netz,
                        AVG(P_WP_avg) as P_WP,
                        AVG(P_Direct) as P_Direct,
                        AVG(P_Exp) as P_Exp,
                        AVG(P_Imp) as P_Imp,
                        AVG(P_inBatt) as P_inBatt,
                        AVG(P_inBatt_PV) as P_inBatt_PV,
                        AVG(P_inBatt_Grid) as P_inBatt_Grid,
                        AVG(P_outBatt) as P_outBatt,
                        AVG(SOC_Batt_avg) as SOC_Batt,
                        AVG(f_Netz_avg) as f_Netz,
                        AVG(I_Batt_API_avg) as I_Batt_API,
                        AVG(U_Batt_API_avg) as U_Batt_API,
                        AVG(I_L1_Inv_avg) as I_L1_Inv,
                        AVG(I_L2_Inv_avg) as I_L2_Inv,
                        AVG(I_L3_Inv_avg) as I_L3_Inv,
                        AVG(U_L1_N_Inv_avg) as U_L1_N_Inv,
                        AVG(U_L2_N_Inv_avg) as U_L2_N_Inv,
                        AVG(U_L3_N_Inv_avg) as U_L3_N_Inv,
                        AVG(U_L1_N_Netz_avg) as U_L1_N_Netz,
                        AVG(U_L2_N_Netz_avg) as U_L2_N_Netz,
                        AVG(U_L3_N_Netz_avg) as U_L3_N_Netz
                    FROM data_1min
                    WHERE ts >= ? AND ts <= ?
                    GROUP BY CAST(ts / ? AS INTEGER)
                    ORDER BY ts ASC
                """, (resolution, resolution, start, end, resolution))

                source = "tmpfs_1min"

            # Hole Daten
            rows = c.fetchall()
            cols = [d[0] for d in c.description if d[0] != 'rn']

            if source == "tmpfs_raw":
                rows = [row[:-1] for row in rows]  # Entferne rn

            data = [dict(zip(cols, row)) for row in rows]

            return jsonify({
                "data": data,
                "source": source,
                "resolution": f"{resolution}s",
                "points": len(data),
                "expected_points": int((hours * 3600) / resolution),
                "hours": hours,
                "start": start,
                "end": end,
                "raw_data_range": {
                    "min": raw_min,
                    "max": raw_max
                } if raw_min and raw_max else None
            })

        finally:
            conn.close()

    except Exception as e:
        return api_error_response(e, "API realtime_smart")


@bp.route('/api/bulk_load')
def api_bulk_load():
    """Lädt ALLE Topics für ein Zeitfenster - volle Auflösung, kein Downsampling, keine Delta-Kompression"""
    MAX_DURATION_S = 7 * 24 * 3600  # max 7 Tage
    MAX_ROWS = 200_000              # ~28h bei 5s-Takt (75 Spalten)

    try:
        start = request.args.get('start', type=int)
        end = request.args.get('end', type=int)

        if not start or not end:
            return jsonify({"error": "start und end erforderlich"}), 400

        if end <= start:
            return jsonify({"error": "end muss größer als start sein"}), 400

        duration_seconds = end - start
        if duration_seconds > MAX_DURATION_S:
            return jsonify({"error": f"Zeitfenster zu groß (max {MAX_DURATION_S // 3600}h)"}), 400
        duration_hours = duration_seconds / 3600

        with ram_db_lock:
            conn = get_db_connection()
            if not conn:
                return jsonify({"error": "DB Error"}), 500

            try:
                c = conn.cursor()

                # ALLE Spalten, ALLE Zeilen - keine Reduktion
                c.execute("""
                    SELECT ts, ChaSt_Batt, f_Netz, I_Batt_API, I_DC1, I_DC2,
                           I_L1_Inv, I_L1_Netz, I_L2_Inv, I_L2_Netz, I_L3_Inv, I_L3_Netz, I_Netz,
                           P_AC_Inv, P_DC1, P_DC2, P_DC_Inv, P_F2, P_F3,
                           PF_F2, PF_F3, PF_Inv, PF_Netz, PF_WP,
                           P_L1_F2, P_L1_F3, P_L1_Netz, P_L1_WP,
                           P_L2_F2, P_L2_F3, P_L2_Netz, P_L2_WP,
                           P_L3_F2, P_L3_F3, P_L3_Netz, P_L3_WP,
                           P_Netz, P_WP,
                           Q_F2, Q_F3, Q_Inv, Q_Netz, Q_WP,
                           S_F2, S_F3, S_Inv, S_Netz, S_WP, SOC_Batt,
                           t_poll_ms,
                           U_Batt_API, U_DC1, U_DC2,
                           U_L1_L2_Inv, U_L1_L2_Netz, U_L1_N_Inv, U_L1_N_Netz,
                           U_L2_L3_Inv, U_L2_L3_Netz, U_L2_N_Inv, U_L2_N_Netz,
                           U_L3_L1_Inv, U_L3_L1_Netz, U_L3_N_Inv, U_L3_N_Netz, U_Netz,
                           W_AC_Inv, W_DC1, W_DC2,
                           W_Exp_F2, W_Exp_F3, W_Exp_Netz,
                           W_Imp_F2, W_Imp_F3, W_Imp_Netz, W_Imp_WP
                    FROM raw_data
                    WHERE ts >= ? AND ts <= ?
                    ORDER BY ts ASC
                    LIMIT ?
                """, (start, end, MAX_ROWS))

                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            finally:
                if conn:
                    conn.close()

        if not rows:
            return jsonify({
                "data": [],
                "points": 0,
                "duration_hours": round(duration_hours, 2),
                "topics": 75
            })

        # Konvertiere zu dict
        data = [dict(zip(cols, row)) for row in rows]

        return jsonify({
            "data": data,
            "points": len(data),
            "truncated": len(data) >= MAX_ROWS,
            "duration_hours": round(duration_hours, 2),
            "topics": 75,
            "resolution": "full (~5s)"
        })
    except Exception as e:
        return api_error_response(e)


@bp.route('/api/zoom_compressed')
def api_zoom_compressed():
    """Delta-komprimierte Daten - nur signifikante Änderungen"""
    try:
        start = request.args.get('start', type=int)
        end = request.args.get('end', type=int)
        level = request.args.get('level', type=int, default=1)  # 1 = normal, 2 = verdoppelt

        if not start or not end:
            return jsonify({"error": "start und end erforderlich"}), 400

        duration_seconds = end - start
        duration_hours = duration_seconds / 3600

        # Basis-Schwellwerte pro Topic
        BASE_THRESHOLDS = {
            'P_Netz': {'abs': 100, 'pct': 2.0},      # ±100W ODER ±2%
            'P_AC_Inv': {'abs': 100, 'pct': 2.0},
            'P_DC_Inv': {'abs': 100, 'pct': 2.0},
            'P_WP': {'abs': 50, 'pct': 3.0},
            'P_F2': {'abs': 50, 'pct': 3.0},
            'P_F3': {'abs': 50, 'pct': 3.0},
            'f_Netz': {'abs': 0.02, 'pct': None},    # ±0.02 Hz
            'SOC_Batt': {'abs': 1.0, 'pct': None},   # ±1.0%
            'I_Batt_API': {'abs': 0.5, 'pct': 5.0},
            'U_Batt_API': {'abs': 1.0, 'pct': None},
            # Default für nicht definierte Topics
            '_default': {'abs': 0, 'pct': 3.0},
        }

        # Schwellwerte mit Level multiplizieren
        THRESHOLDS = {}
        for key, val in BASE_THRESHOLDS.items():
            THRESHOLDS[key] = {
                'abs': val['abs'] * level if val['abs'] else None,
                'pct': val['pct'] * level if val['pct'] else None
            }

        with ram_db_lock:
            conn = get_db_connection()
            if not conn:
                return jsonify({"error": "DB Error"}), 500

            try:
                c = conn.cursor()

                # Alle Rohdaten laden (keine ROW_NUMBER Reduktion)
                c.execute("""
                    SELECT ts, ChaSt_Batt, f_Netz, I_Batt_API, I_DC1, I_DC2,
                           I_L1_Inv, I_L1_Netz, I_L2_Inv, I_L2_Netz, I_L3_Inv, I_L3_Netz, I_Netz,
                           P_AC_Inv, P_DC1, P_DC2, P_DC_Inv, P_F2, P_F3,
                           PF_F2, PF_F3, PF_Inv, PF_Netz, PF_WP,
                           P_L1_F2, P_L1_F3, P_L1_Netz, P_L1_WP,
                           P_L2_F2, P_L2_F3, P_L2_Netz, P_L2_WP,
                           P_L3_F2, P_L3_F3, P_L3_Netz, P_L3_WP,
                           P_Netz, P_WP,
                           Q_F2, Q_F3, Q_Inv, Q_Netz, Q_WP,
                           S_F2, S_F3, S_Inv, S_Netz, S_WP, SOC_Batt,
                           t_poll_ms,
                           U_Batt_API, U_DC1, U_DC2,
                           U_L1_L2_Inv, U_L1_L2_Netz, U_L1_N_Inv, U_L1_N_Netz,
                           U_L2_L3_Inv, U_L2_L3_Netz, U_L2_N_Inv, U_L2_N_Netz,
                           U_L3_L1_Inv, U_L3_L1_Netz, U_L3_N_Inv, U_L3_N_Netz, U_Netz,
                           W_AC_Inv, W_DC1, W_DC2,
                           W_Exp_F2, W_Exp_F3, W_Exp_Netz,
                           W_Imp_F2, W_Imp_F3, W_Imp_Netz, W_Imp_WP
                    FROM raw_data
                    WHERE ts >= ? AND ts <= ?
                    ORDER BY ts ASC
                """, (start, end))

                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            finally:
                if conn:
                    conn.close()

        if not rows:
            return jsonify({
                "data": [],
                "resolution": "compressed",
                "points": 0,
                "original_points": 0,
                "compression_ratio": 0,
                "duration_hours": round(duration_hours, 2)
            })

        # Konvertiere zu dict
        all_data = [dict(zip(cols, row)) for row in rows]
        original_count = len(all_data)

        # Delta-Kompression anwenden
        compressed_data = []
        last_values = {}

        for i, point in enumerate(all_data):
            # Erster und letzter Punkt immer behalten
            if i == 0 or i == original_count - 1:
                compressed_data.append(point)
                for col in cols:
                    if col != 'ts':
                        last_values[col] = point.get(col)
                continue

            # Prüfe ob signifikante Änderung in IRGENDEINEM Topic
            should_keep = False
            for col in cols:
                if col == 'ts':
                    continue

                current_val = point.get(col)
                last_val = last_values.get(col)

                if current_val is None or last_val is None:
                    continue

                threshold = THRESHOLDS.get(col, THRESHOLDS['_default'])
                delta = abs(current_val - last_val)

                # Absolute Schwelle
                if threshold.get('abs') and delta > threshold['abs']:
                    should_keep = True
                    break

                # Prozentuale Schwelle
                if threshold.get('pct') and last_val != 0:
                    pct_change = delta / abs(last_val) * 100
                    if pct_change > threshold['pct']:
                        should_keep = True
                        break

            if should_keep:
                compressed_data.append(point)
                for col in cols:
                    if col != 'ts':
                        last_values[col] = point.get(col)

        compression_ratio = len(compressed_data) / original_count if original_count > 0 else 0

        return jsonify({
            "data": compressed_data,
            "resolution": "compressed",
            "points": len(compressed_data),
            "original_points": original_count,
            "compression_ratio": round(compression_ratio, 3),
            "duration_hours": round(duration_hours, 2)
        })
    except Exception as e:
        return api_error_response(e)


@bp.route('/api/flow_realtime')
def api_flow_realtime():
    """
    Echtzeit-Daten für Energieflow-Visualisierung.
    Direkter Zugriff auf tmpfs-DB — immer frisch (<3s).
    """
    try:
        now = int(time.time())

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB nicht verfügbar"}), 500

        try:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute("SELECT * FROM raw_data ORDER BY ts DESC LIMIT 1")
            row = c.fetchone()

            # Wattpilot aus separater Tabelle (vor conn.close!)
            # Strategie: letzten aktiven Ladewert (car_state=2, power>0) innerhalb
            # 3 Minuten bevorzugen. Verhindert Sprünge in Haushalt-Bubble wenn der
            # WebSocket-Collector kurz retried und power=0 schreibt, obwohl das Auto
            # tatsächlich lädt (Erkennung über car_state=2).
            wattpilot_power = 0
            try:
                c.execute("""
                    SELECT power_w, car_state FROM wattpilot_readings
                    WHERE ts > ?
                    ORDER BY ts DESC LIMIT 6
                """, (now - 180,))
                wattpilot_rows = c.fetchall()
                if wattpilot_rows:
                    # Bevorzuge jüngsten aktiven Ladewert (car=2, power>0)
                    for pw, car in wattpilot_rows:
                        if car == 2 and (pw or 0) > 0:
                            wattpilot_power = round(pw, 0)
                            break
                    # Fallback: aktuellster Wert (auch wenn 0)
                    if wattpilot_power == 0:
                        pw0 = wattpilot_rows[0][0]
                        if pw0 is not None:
                            wattpilot_power = round(pw0, 0)
            except Exception as e:
                logging.debug(f"Wattpilot read: {e}")

            # Fritz!DECT Geräte (Heizpatrone + Klimaanlage) — aktuellste Readings
            heizpatrone_power = 0
            klima_power = 0
            try:
                c.execute("""
                    SELECT device_id, power_w FROM fritzdect_readings
                    WHERE ts > ?
                    ORDER BY ts DESC LIMIT 10
                """, (now - 60,))
                for device_id, pw in c.fetchall():
                    if device_id == 'heizpatrone':
                        heizpatrone_power = max(0, round(pw or 0, 1))
                    elif device_id == 'klimaanlage':
                        klima_power = max(0, round(pw or 0, 1))
            except Exception as e:
                logging.debug(f"Fritz!DECT reading: {e}")
        finally:
            conn.close()

        if not row:
            return jsonify({"error": "Keine aktuellen Daten"}), 404

        latest = dict(row)
        ts = latest.get('ts', 0)

        if now - ts > 120:
            return jsonify({"error": "Daten zu alt"}), 404

        # Daten extrahieren
        p_dc1 = latest.get('P_DC1', 0) or 0
        p_dc2 = latest.get('P_DC2', 0) or 0
        p_f2 = latest.get('P_F2', 0) or 0
        p_f3 = latest.get('P_F3', 0) or 0
        p_netz = latest.get('P_Netz', 0) or 0
        i_batt = latest.get('I_Batt_API', 0) or 0
        u_batt = latest.get('U_Batt_API', 0) or 0
        soc_batt = latest.get('SOC_Batt', 0) or 0
        chastate_batt = latest.get('ChaSt_Batt', 0)
        p_wp = latest.get('P_WP', 0) or 0

        # Berechnungen
        # PV-Erzeuger
        f1 = round(p_dc1 + p_dc2, 0)
        f2 = round(p_f2, 0)
        f3 = round(p_f3, 0)
        pv_gesamt = round(f1 + f2 + f3, 0)

        # Batterie
        p_akku = round(i_batt * u_batt, 0)
        soc = round(soc_batt, 1)

        # Netz (negativ = Einspeisung, positiv = Bezug)
        netz = round(p_netz, 0)

        # Verbrauch (Bilanz: PV - Batterie_Ladung + Netz)
        verbrauch_gesamt = round(pv_gesamt - p_akku + netz, 0)

        # KRITISCH: P_WP = Wärmepumpe (SmartMeter Unit 4), NICHT Wattpilot!
        waermepumpe = max(0, round(-p_wp, 0))

        # Wattpilot (bereits oben aus DB gelesen)
        wattpilot = max(0, wattpilot_power)

        haushalt = max(0, round(verbrauch_gesamt - wattpilot - waermepumpe - heizpatrone_power - klima_power, 0))

        # Flussrichtungen ermitteln
        flows = {
            'pv_to_consumption': max(0, min(pv_gesamt, verbrauch_gesamt)),
            'pv_to_grid': max(0, -netz) if netz < 0 else 0,
            'pv_to_battery': max(0, p_akku),
            'battery_to_consumption': max(0, -p_akku),
            'grid_to_consumption': max(0, netz),
            'grid_to_battery': 0
        }

        # Tageswerte berechnen (heute)
        today_start = int(time.mktime(time.localtime(now)[:3] + (0,0,0, 0,0, -1)))
        pv_today_kwh = 0.0
        grid_import_today_kwh = 0.0
        consumption_today_kwh = 0.0
        # SOH aus battery_control.json (langsam veränderlicher Hardware-Wert)
        battery_soh = 92.0  # Fallback
        try:
            import json as _json
            _batt_cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'battery_control.json')
            with open(_batt_cfg_path, 'r') as _f:
                _batt_cfg = _json.load(_f)
            battery_soh = float(_batt_cfg.get('batterie', {}).get('soh_prozent', 92.0))
        except Exception:
            pass  # Fallback 92.0 bleibt

        try:
            conn2 = get_db_connection()
            if conn2:
                try:
                    c2 = conn2.cursor()
                    c2.execute("""
                        SELECT
                            SUM(W_Ertrag) / 1000.0 as pv_sum,
                            SUM(W_Bezug) / 1000.0 as grid_import_sum,
                            SUM(W_Verbrauch) / 1000.0 as consumption_sum
                        FROM data_1min
                        WHERE ts >= ?
                    """, (today_start,))
                    day_row = c2.fetchone()
                    if day_row:
                        pv_today_kwh = round(day_row[0] or 0, 2)
                        grid_import_today_kwh = round(day_row[1] or 0, 2)
                        consumption_today_kwh = round(day_row[2] or 0, 2)
                finally:
                    conn2.close()
        except Exception as e:
            logging.debug(f"Tageswerte Fehler: {e}")

        # Autarkie berechnen
        autarkie_today = 0.0
        if consumption_today_kwh > 0:
            autarkie_today = ((consumption_today_kwh - grid_import_today_kwh) / consumption_today_kwh) * 100
            autarkie_today = max(0.0, min(100.0, round(autarkie_today, 1)))

        result = {
            'timestamp': ts,
            'age_seconds': now - ts,
            'producers': {
                'f1': f1,
                'f2': f2,
                'f3': f3,
                'pv_total': pv_gesamt,
                'pv_today_kwh': pv_today_kwh,
                'autarkie_today': autarkie_today
            },
            'battery': {
                'power': p_akku,
                'soc': soc,
                'soh': battery_soh,
                'state': chastate_batt,
                'charging': p_akku > 0,
                'discharging': p_akku < 0
            },
            'grid': {
                'power': netz,
                'importing': netz > 0,
                'exporting': netz < 0,
                'import_today_kwh': grid_import_today_kwh
            },
            'consumption': {
                'total': verbrauch_gesamt,
                'household': haushalt,
                'wattpilot': wattpilot,
                'heatpump': waermepumpe,
                'heizpatrone': heizpatrone_power,
                'klima': klima_power,
                'total_today_kwh': consumption_today_kwh
            },
            'flows': flows
        }

        return jsonify(result)

    except Exception as e:
        return api_error_response(e, "Flow-API")


@bp.route('/api/polling_data')
def api_polling_data():
    """Raw Polling-Daten für einen bestimmten Zeitraum"""
    try:
        # Parameter: date (YYYY-MM-DD), start_hour (0-23), end_hour (1-24)
        date_str = request.args.get('date', date.today().isoformat())
        start_hour = request.args.get('start_hour', 10, type=int)
        end_hour = request.args.get('end_hour', 11, type=int)

        conn = get_db_connection()
        if not conn:
            return jsonify({"error": "DB Error"}), 500

        try:
            c = conn.cursor()

            # Erstelle Zeitstempel-Bereich
            start_datetime = f"{date_str} {start_hour:02d}:00:00"
            end_datetime = f"{date_str} {end_hour:02d}:00:00"

            # Abfrage mit ALLEN Spalten in DB-Reihenfolge
            query = """
                SELECT
                    datetime(ts, 'unixepoch', 'localtime') as Zeit,
                    ts,
                    I_L1_Inv, I_L2_Inv, I_L3_Inv,
                    U_L1_L2_Inv, U_L2_L3_Inv, U_L3_L1_Inv,
                    U_L1_N_Inv, U_L2_N_Inv, U_L3_N_Inv,
                    P_AC_Inv, S_Inv, Q_Inv, PF_Inv, W_AC_Inv,
                    P_DC_Inv,
                    I_DC1, U_DC1, P_DC1, W_DC1,
                    I_DC2, U_DC2, P_DC2, W_DC2,
                    SOC_Batt, ChaSt_Batt, U_Batt_API, I_Batt_API,
                    I_Netz, I_L1_Netz, I_L2_Netz, I_L3_Netz,
                    U_Netz, U_L1_N_Netz, U_L2_N_Netz, U_L3_N_Netz,
                    U_L1_L2_Netz, U_L2_L3_Netz, U_L3_L1_Netz,
                    f_Netz,
                    P_Netz, P_L1_Netz, P_L2_Netz, P_L3_Netz,
                    S_Netz, Q_Netz, PF_Netz,
                    W_Exp_Netz, W_Imp_Netz,
                    P_F2, P_L1_F2, P_L2_F2, P_L3_F2,
                    S_F2, Q_F2, PF_F2,
                    W_Exp_F2, W_Imp_F2,
                    P_WP, P_L1_WP, P_L2_WP, P_L3_WP,
                    S_WP, Q_WP, PF_WP, W_Imp_WP,
                    P_F3, P_L1_F3, P_L2_F3, P_L3_F3,
                    S_F3, Q_F3, PF_F3,
                    W_Exp_F3, W_Imp_F3,
                    t_poll_ms
                FROM raw_data
                WHERE datetime(ts, 'unixepoch', 'localtime') >= ?
                  AND datetime(ts, 'unixepoch', 'localtime') < ?
                ORDER BY ts ASC
            """

            c.execute(query, (start_datetime, end_datetime))
            rows = c.fetchall()
            cols = [d[0] for d in c.description]
        finally:
            conn.close()

        data = [dict(zip(cols, row)) for row in rows]

        # Zusätzlich Statistik berechnen
        if data:
            stats = {
                'anzahl_messwerte': len(data),
                'anzahl_spalten': len(data[0]) if data else 0,
                'zeitraum': f"{start_datetime} bis {end_datetime}",
                'pv_avg': round(sum(row.get('P_AC_Inv', 0) or 0 for row in data) / len(data), 1),
                'pv_max': round(max(row.get('P_AC_Inv', 0) or 0 for row in data), 1),
                'netz_avg': round(sum(row.get('P_Netz', 0) or 0 for row in data) / len(data), 1),
                'soc_avg': round(sum(row.get('SOC_Batt', 0) or 0 for row in data) / len(data), 1),
                'freq_avg': round(sum(row.get('f_Netz', 0) or 0 for row in data) / len(data), 3)
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
        return api_error_response(e)
