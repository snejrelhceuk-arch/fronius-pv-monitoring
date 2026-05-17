"""
Blueprint: Netzqualitäts-APIs.

Enthält: /api/netzqualitaet/tag, /api/netzqualitaet/analyse
Liefert Leiterspannungen (L-L) und Netzfrequenz für die Netzqualitäts-Ansicht.
Datenquelle: data_1min (falls vorhanden), sonst Resampling aus raw_data.

ABCD-Rollenmodell: Säule B (read-only).
"""
import logging
import math
import os
import sqlite3
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from routes.helpers import get_db_connection, api_error_response
import config

bp = Blueprint('netzqualitaet', __name__)

NQ_DB_DIR = os.path.join(config.BASE_DIR, 'netzqualitaet', 'db')
SQRT3 = math.sqrt(3)
# Plausibility corridors
VOLTAGE_MIN = 200.0
VOLTAGE_MAX = 600.0
FREQ_MIN = 40.0
FREQ_MAX = 60.0


def _parse_anchor_date(date_param):
    if not date_param:
        return datetime.now(), datetime.now().strftime('%Y-%m-%d')
    anchor = datetime.strptime(date_param, '%Y-%m-%d')
    return anchor, anchor.strftime('%Y-%m-%d')


def _month_start(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _month_next(dt):
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1, day=1)
    return dt.replace(month=dt.month + 1, day=1)


def _year_start(dt):
    return dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


def _period_bounds(period, anchor):
    if period == 'tag':
        start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end
    if period == 'monat':
        start = _month_start(anchor)
        end = _month_next(start)
        return start, end
    if period == 'jahr':
        start = _year_start(anchor)
        end = start.replace(year=start.year + 1)
        return start, end
    return None, None


def _table_exists(cursor, table_name):
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def _rows_to_datapoints(rows):
    datapoints = []
    for row in rows:
        datapoints.append({
            'ts': row[0],
            'u_l1_l2': round(row[1], 1) if row[1] is not None else None,
            'u_l2_l3': round(row[2], 1) if row[2] is not None else None,
            'u_l3_l1': round(row[3], 1) if row[3] is not None else None,
            'f_netz': round(row[4], 3) if row[4] is not None else None,
            'u_l1_l2_min': round(row[5], 1) if row[5] is not None else None,
            'u_l1_l2_max': round(row[6], 1) if row[6] is not None else None,
            'u_l2_l3_min': round(row[7], 1) if row[7] is not None else None,
            'u_l2_l3_max': round(row[8], 1) if row[8] is not None else None,
            'u_l3_l1_min': round(row[9], 1) if row[9] is not None else None,
            'u_l3_l1_max': round(row[10], 1) if row[10] is not None else None,
            'f_netz_min': round(row[11], 3) if row[11] is not None else None,
            'f_netz_max': round(row[12], 3) if row[12] is not None else None,
        })
    return datapoints


def _query_tag_raw(cursor, date_param):
    cursor.execute(
        """
        SELECT
            (CAST(ts AS INTEGER) / 300) * 300 AS ts_bucket,
            AVG(U_L1_L2_Netz) AS u_l1_l2,
            AVG(U_L2_L3_Netz) AS u_l2_l3,
            AVG(U_L3_L1_Netz) AS u_l3_l1,
            AVG(f_Netz)       AS f_netz,
            MIN(U_L1_L2_Netz) AS u_l1_l2_min,
            MAX(U_L1_L2_Netz) AS u_l1_l2_max,
            MIN(U_L2_L3_Netz) AS u_l2_l3_min,
            MAX(U_L2_L3_Netz) AS u_l2_l3_max,
            MIN(U_L3_L1_Netz) AS u_l3_l1_min,
            MAX(U_L3_L1_Netz) AS u_l3_l1_max,
            MIN(f_Netz)       AS f_netz_min,
            MAX(f_Netz)       AS f_netz_max
        FROM raw_data
        WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day')
          AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')
        GROUP BY ts_bucket
        ORDER BY ts_bucket
        """,
        (date_param, date_param)
    )
    return cursor.fetchall()


def _query_tag_from_1min(cursor, date_param):
    if not _table_exists(cursor, 'data_1min'):
        return []

    cursor.execute(
        """
        SELECT
            (CAST(ts AS INTEGER) / 300) * 300 AS ts_bucket,
            AVG(U_L1_N_Netz_avg) * ? AS u_l1_l2,
            AVG(U_L2_N_Netz_avg) * ? AS u_l2_l3,
            AVG(U_L3_N_Netz_avg) * ? AS u_l3_l1,
            AVG(f_Netz_avg)          AS f_netz,
            MIN(U_L1_N_Netz_min) * ? AS u_l1_l2_min,
            MAX(U_L1_N_Netz_max) * ? AS u_l1_l2_max,
            MIN(U_L2_N_Netz_min) * ? AS u_l2_l3_min,
            MAX(U_L2_N_Netz_max) * ? AS u_l2_l3_max,
            MIN(U_L3_N_Netz_min) * ? AS u_l3_l1_min,
            MAX(U_L3_N_Netz_max) * ? AS u_l3_l1_max,
            MIN(f_Netz_min)          AS f_netz_min,
            MAX(f_Netz_max)          AS f_netz_max
        FROM data_1min
        WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day')
          AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')
        GROUP BY ts_bucket
        ORDER BY ts_bucket
        """,
        (
            SQRT3, SQRT3, SQRT3,
            SQRT3, SQRT3, SQRT3, SQRT3, SQRT3, SQRT3,
            date_param, date_param
        )
    )
    return cursor.fetchall()


def _query_month_15min(cursor, date_param):
    if not _table_exists(cursor, 'data_15min'):
        return []

    cursor.execute(
        """
        SELECT
            ts AS ts_bucket,
            U_L1_N_Netz_avg * ? AS u_l1_l2,
            U_L2_N_Netz_avg * ? AS u_l2_l3,
            U_L3_N_Netz_avg * ? AS u_l3_l1,
            f_Netz_avg          AS f_netz,
            U_L1_N_Netz_min * ? AS u_l1_l2_min,
            U_L1_N_Netz_max * ? AS u_l1_l2_max,
            U_L2_N_Netz_min * ? AS u_l2_l3_min,
            U_L2_N_Netz_max * ? AS u_l2_l3_max,
            U_L3_N_Netz_min * ? AS u_l3_l1_min,
            U_L3_N_Netz_max * ? AS u_l3_l1_max,
            f_Netz_min          AS f_netz_min,
            f_Netz_max          AS f_netz_max
        FROM data_15min
        WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of month')
          AND datetime(ts, 'unixepoch', 'localtime') < date(?, 'start of month', '+1 month')
        ORDER BY ts_bucket
        """,
        (
            SQRT3, SQRT3, SQRT3,
            SQRT3, SQRT3, SQRT3, SQRT3, SQRT3, SQRT3,
            date_param, date_param
        )
    )
    return cursor.fetchall()


def _query_month_from_1min(cursor, date_param):
    if not _table_exists(cursor, 'data_1min'):
        return []

    cursor.execute(
        """
        SELECT
            (CAST(ts AS INTEGER) / 900) * 900 AS ts_bucket,
            AVG(U_L1_N_Netz_avg) * ? AS u_l1_l2,
            AVG(U_L2_N_Netz_avg) * ? AS u_l2_l3,
            AVG(U_L3_N_Netz_avg) * ? AS u_l3_l1,
            AVG(f_Netz_avg)          AS f_netz,
            MIN(U_L1_N_Netz_min) * ? AS u_l1_l2_min,
            MAX(U_L1_N_Netz_max) * ? AS u_l1_l2_max,
            MIN(U_L2_N_Netz_min) * ? AS u_l2_l3_min,
            MAX(U_L2_N_Netz_max) * ? AS u_l2_l3_max,
            MIN(U_L3_N_Netz_min) * ? AS u_l3_l1_min,
            MAX(U_L3_N_Netz_max) * ? AS u_l3_l1_max,
            MIN(f_Netz_min)          AS f_netz_min,
            MAX(f_Netz_max)          AS f_netz_max
        FROM data_1min
        WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of month')
          AND datetime(ts, 'unixepoch', 'localtime') < date(?, 'start of month', '+1 month')
        GROUP BY ts_bucket
        ORDER BY ts_bucket
        """,
        (
            SQRT3, SQRT3, SQRT3,
            SQRT3, SQRT3, SQRT3, SQRT3, SQRT3, SQRT3,
            date_param, date_param
        )
    )
    return cursor.fetchall()


def _query_year_monthly(cursor, date_param):
    if not _table_exists(cursor, 'data_monthly'):
        return []

    cursor.execute(
        """
        SELECT
            ts AS ts_bucket,
            U_L1_N_Netz_avg * ? AS u_l1_l2,
            U_L2_N_Netz_avg * ? AS u_l2_l3,
            U_L3_N_Netz_avg * ? AS u_l3_l1,
            f_Netz_avg          AS f_netz,
            U_L1_N_Netz_min * ? AS u_l1_l2_min,
            U_L1_N_Netz_max * ? AS u_l1_l2_max,
            U_L2_N_Netz_min * ? AS u_l2_l3_min,
            U_L2_N_Netz_max * ? AS u_l2_l3_max,
            U_L3_N_Netz_min * ? AS u_l3_l1_min,
            U_L3_N_Netz_max * ? AS u_l3_l1_max,
            f_Netz_min          AS f_netz_min,
            f_Netz_max          AS f_netz_max
        FROM data_monthly
        WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of year')
          AND datetime(ts, 'unixepoch', 'localtime') < date(?, 'start of year', '+1 year')
        ORDER BY ts_bucket
        """,
        (
            SQRT3, SQRT3, SQRT3,
            SQRT3, SQRT3, SQRT3, SQRT3, SQRT3, SQRT3,
            date_param, date_param
        )
    )
    return cursor.fetchall()


def _query_year_15min_daily(cursor, date_param):
    if not _table_exists(cursor, 'data_15min'):
        return []

    cursor.execute(
        """
        SELECT
            (CAST(ts AS INTEGER) / 86400) * 86400 AS ts_bucket,
            AVG(U_L1_N_Netz_avg) * ? AS u_l1_l2,
            AVG(U_L2_N_Netz_avg) * ? AS u_l2_l3,
            AVG(U_L3_N_Netz_avg) * ? AS u_l3_l1,
            AVG(f_Netz_avg)          AS f_netz,
            MIN(U_L1_N_Netz_min) * ? AS u_l1_l2_min,
            MAX(U_L1_N_Netz_max) * ? AS u_l1_l2_max,
            MIN(U_L2_N_Netz_min) * ? AS u_l2_l3_min,
            MAX(U_L2_N_Netz_max) * ? AS u_l2_l3_max,
            MIN(U_L3_N_Netz_min) * ? AS u_l3_l1_min,
            MAX(U_L3_N_Netz_max) * ? AS u_l3_l1_max,
            MIN(f_Netz_min)          AS f_netz_min,
            MAX(f_Netz_max)          AS f_netz_max
        FROM data_15min
        WHERE datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of year')
          AND datetime(ts, 'unixepoch', 'localtime') < date(?, 'start of year', '+1 year')
        GROUP BY ts_bucket
        ORDER BY ts_bucket
        """,
        (
            SQRT3, SQRT3, SQRT3,
            SQRT3, SQRT3, SQRT3, SQRT3, SQRT3, SQRT3,
            date_param, date_param
        )
    )
    return cursor.fetchall()


def _query_gesamt_monthly(cursor):
    if not _table_exists(cursor, 'data_monthly'):
        return []

    cursor.execute(
        """
        SELECT
            ts AS ts_bucket,
            U_L1_N_Netz_avg * ? AS u_l1_l2,
            U_L2_N_Netz_avg * ? AS u_l2_l3,
            U_L3_N_Netz_avg * ? AS u_l3_l1,
            f_Netz_avg          AS f_netz,
            U_L1_N_Netz_min * ? AS u_l1_l2_min,
            U_L1_N_Netz_max * ? AS u_l1_l2_max,
            U_L2_N_Netz_min * ? AS u_l2_l3_min,
            U_L2_N_Netz_max * ? AS u_l2_l3_max,
            U_L3_N_Netz_min * ? AS u_l3_l1_min,
            U_L3_N_Netz_max * ? AS u_l3_l1_max,
            f_Netz_min          AS f_netz_min,
            f_Netz_max          AS f_netz_max
        FROM data_monthly
        ORDER BY ts_bucket
        """,
        (
            SQRT3, SQRT3, SQRT3,
            SQRT3, SQRT3, SQRT3, SQRT3, SQRT3, SQRT3
        )
    )
    return cursor.fetchall()


def _query_gesamt_15min_monthly(cursor):
    if not _table_exists(cursor, 'data_15min'):
        return []

    cursor.execute(
        """
        SELECT
            CAST(strftime('%s', date(datetime(ts, 'unixepoch', 'localtime'), 'start of month')) AS INTEGER) AS ts_bucket,
            AVG(U_L1_N_Netz_avg) * ? AS u_l1_l2,
            AVG(U_L2_N_Netz_avg) * ? AS u_l2_l3,
            AVG(U_L3_N_Netz_avg) * ? AS u_l3_l1,
            AVG(f_Netz_avg)          AS f_netz,
            MIN(U_L1_N_Netz_min) * ? AS u_l1_l2_min,
            MAX(U_L1_N_Netz_max) * ? AS u_l1_l2_max,
            MIN(U_L2_N_Netz_min) * ? AS u_l2_l3_min,
            MAX(U_L2_N_Netz_max) * ? AS u_l2_l3_max,
            MIN(U_L3_N_Netz_min) * ? AS u_l3_l1_min,
            MAX(U_L3_N_Netz_max) * ? AS u_l3_l1_max,
            MIN(f_Netz_min)          AS f_netz_min,
            MAX(f_Netz_max)          AS f_netz_max
        FROM data_15min
        GROUP BY strftime('%Y-%m', datetime(ts, 'unixepoch', 'localtime'))
        ORDER BY ts_bucket
        """,
        (
            SQRT3, SQRT3, SQRT3,
            SQRT3, SQRT3, SQRT3, SQRT3, SQRT3, SQRT3
        )
    )
    return cursor.fetchall()


def _period_where_clause(period, date_param):
    if period == 'tag':
        return (
            "datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of day') "
            "AND datetime(ts, 'unixepoch', 'localtime') < date(?, '+1 day', 'start of day')",
            (date_param, date_param)
        )
    if period == 'monat':
        return (
            "datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of month') "
            "AND datetime(ts, 'unixepoch', 'localtime') < date(?, 'start of month', '+1 month')",
            (date_param, date_param)
        )
    if period == 'jahr':
        return (
            "datetime(ts, 'unixepoch', 'localtime') >= date(?, 'start of year') "
            "AND datetime(ts, 'unixepoch', 'localtime') < date(?, 'start of year', '+1 year')",
            (date_param, date_param)
        )
    return ('1=1', ())


def _fetch_maxima_raw(cursor, period, date_param):
    where_clause, params = _period_where_clause(period, date_param)

    # For raw_data the voltage columns are already L-L values
    v_low, v_high = VOLTAGE_MIN, VOLTAGE_MAX
    f_low, f_high = FREQ_MIN, FREQ_MAX

    def one(col, order='DESC'):
        cl = col.lower()
        if 'f_netz' in cl or cl.startswith('f_'):
            low, high = f_low, f_high
        else:
            low, high = v_low, v_high

        cursor.execute(
            f"""
            SELECT ts, {col}
            FROM raw_data
            WHERE {where_clause} AND {col} IS NOT NULL AND {col} BETWEEN ? AND ?
            ORDER BY {col} {order}, ts ASC
            LIMIT 1
            """,
            params + (low, high),
        )
        return cursor.fetchone()

    l1 = one('U_L1_L2_Netz')
    l2 = one('U_L2_L3_Netz')
    l3 = one('U_L3_L1_Netz')
    fmax = one('f_Netz')
    l1n = one('U_L1_L2_Netz', 'ASC')
    l2n = one('U_L2_L3_Netz', 'ASC')
    l3n = one('U_L3_L1_Netz', 'ASC')
    fmin = one('f_Netz', 'ASC')

    rows = [r for r in [l1, l2, l3] if r]
    if not rows:
        return None

    vmax_row = max(rows, key=lambda x: x[1])
    rows_min = [r for r in [l1n, l2n, l3n] if r]
    vmin_row = min(rows_min, key=lambda x: x[1]) if rows_min else None
    return {
        'source': 'raw_data',
        'accuracy': '5s',
        'u_l1_l2': {'ts': l1[0], 'value': round(l1[1], 2)} if l1 else None,
        'u_l2_l3': {'ts': l2[0], 'value': round(l2[1], 2)} if l2 else None,
        'u_l3_l1': {'ts': l3[0], 'value': round(l3[1], 2)} if l3 else None,
        'u_voltage_max': {'ts': vmax_row[0], 'value': round(vmax_row[1], 2)},
        'u_voltage_min': {'ts': vmin_row[0], 'value': round(vmin_row[1], 2)} if vmin_row else None,
        'f_netz_max': {'ts': fmax[0], 'value': round(fmax[1], 4)} if fmax else None,
        'f_netz_min': {'ts': fmin[0], 'value': round(fmin[1], 4)} if fmin else None,
    }


def _fetch_maxima_1min(cursor, period, date_param):
    if not _table_exists(cursor, 'data_1min'):
        return None

    where_clause, params = _period_where_clause(period, date_param)

    # data_1min stores phase (L-N) voltages; convert L-L bounds to L-N for filtering
    v_low, v_high = VOLTAGE_MIN / SQRT3, VOLTAGE_MAX / SQRT3
    f_low, f_high = FREQ_MIN, FREQ_MAX

    def one(col, order='DESC'):
        cl = col.lower()
        if 'f_netz' in cl or cl.startswith('f_'):
            low, high = f_low, f_high
        else:
            low, high = v_low, v_high

        cursor.execute(
            f"""
            SELECT ts, {col}
            FROM data_1min
            WHERE {where_clause} AND {col} IS NOT NULL AND {col} BETWEEN ? AND ?
            ORDER BY {col} {order}, ts ASC
            LIMIT 1
            """,
            params + (low, high),
        )
        return cursor.fetchone()

    l1 = one('U_L1_N_Netz_max')
    l2 = one('U_L2_N_Netz_max')
    l3 = one('U_L3_N_Netz_max')
    fmax = one('f_Netz_max')
    l1n = one('U_L1_N_Netz_min', 'ASC')
    l2n = one('U_L2_N_Netz_min', 'ASC')
    l3n = one('U_L3_N_Netz_min', 'ASC')
    fmin = one('f_Netz_min', 'ASC')

    rows = [r for r in [l1, l2, l3] if r]
    if not rows:
        return None

    vmax_row = max(rows, key=lambda x: x[1])
    rows_min = [r for r in [l1n, l2n, l3n] if r]
    vmin_row = min(rows_min, key=lambda x: x[1]) if rows_min else None
    return {
        'source': 'data_1min',
        'accuracy': '1min',
        'u_l1_l2': {'ts': l1[0], 'value': round(l1[1] * SQRT3, 2)} if l1 else None,
        'u_l2_l3': {'ts': l2[0], 'value': round(l2[1] * SQRT3, 2)} if l2 else None,
        'u_l3_l1': {'ts': l3[0], 'value': round(l3[1] * SQRT3, 2)} if l3 else None,
        'u_voltage_max': {'ts': vmax_row[0], 'value': round(vmax_row[1] * SQRT3, 2)},
        'u_voltage_min': {'ts': vmin_row[0], 'value': round(vmin_row[1] * SQRT3, 2)} if vmin_row else None,
        'f_netz_max': {'ts': fmax[0], 'value': round(fmax[1], 4)} if fmax else None,
        'f_netz_min': {'ts': fmin[0], 'value': round(fmin[1], 4)} if fmin else None,
    }


def _fetch_maxima_15min(cursor, period, date_param):
    if not _table_exists(cursor, 'data_15min'):
        return None

    where_clause, params = _period_where_clause(period, date_param)

    # data_15min stores phase (L-N) voltages; convert L-L bounds to L-N for filtering
    v_low, v_high = VOLTAGE_MIN / SQRT3, VOLTAGE_MAX / SQRT3
    f_low, f_high = FREQ_MIN, FREQ_MAX

    def one(col, order='DESC'):
        cl = col.lower()
        if 'f_netz' in cl or cl.startswith('f_'):
            low, high = f_low, f_high
        else:
            low, high = v_low, v_high

        cursor.execute(
            f"""
            SELECT ts, {col}
            FROM data_15min
            WHERE {where_clause} AND {col} IS NOT NULL AND {col} BETWEEN ? AND ?
            ORDER BY {col} {order}, ts ASC
            LIMIT 1
            """,
            params + (low, high),
        )
        return cursor.fetchone()

    l1 = one('U_L1_N_Netz_max')
    l2 = one('U_L2_N_Netz_max')
    l3 = one('U_L3_N_Netz_max')
    fmax = one('f_Netz_max')
    l1n = one('U_L1_N_Netz_min', 'ASC')
    l2n = one('U_L2_N_Netz_min', 'ASC')
    l3n = one('U_L3_N_Netz_min', 'ASC')
    fmin = one('f_Netz_min', 'ASC')

    rows = [r for r in [l1, l2, l3] if r]
    if not rows:
        return None

    vmax_row = max(rows, key=lambda x: x[1])
    rows_min = [r for r in [l1n, l2n, l3n] if r]
    vmin_row = min(rows_min, key=lambda x: x[1]) if rows_min else None
    return {
        'source': 'data_15min',
        'accuracy': '15min',
        'u_l1_l2': {'ts': l1[0], 'value': round(l1[1] * SQRT3, 2)} if l1 else None,
        'u_l2_l3': {'ts': l2[0], 'value': round(l2[1] * SQRT3, 2)} if l2 else None,
        'u_l3_l1': {'ts': l3[0], 'value': round(l3[1] * SQRT3, 2)} if l3 else None,
        'u_voltage_max': {'ts': vmax_row[0], 'value': round(vmax_row[1] * SQRT3, 2)},
        'u_voltage_min': {'ts': vmin_row[0], 'value': round(vmin_row[1] * SQRT3, 2)} if vmin_row else None,
        'f_netz_max': {'ts': fmax[0], 'value': round(fmax[1], 4)} if fmax else None,
        'f_netz_min': {'ts': fmin[0], 'value': round(fmin[1], 4)} if fmin else None,
    }


def _fetch_maxima_monthly(cursor, period, date_param):
    if not _table_exists(cursor, 'data_monthly'):
        return None

    where_clause, params = _period_where_clause(period, date_param)

    # data_monthly stores phase (L-N) voltages; convert L-L bounds to L-N for filtering
    v_low, v_high = VOLTAGE_MIN / SQRT3, VOLTAGE_MAX / SQRT3
    f_low, f_high = FREQ_MIN, FREQ_MAX

    def one(col, order='DESC'):
        cl = col.lower()
        if 'f_netz' in cl or cl.startswith('f_'):
            low, high = f_low, f_high
        else:
            low, high = v_low, v_high

        cursor.execute(
            f"""
            SELECT ts, {col}
            FROM data_monthly
            WHERE {where_clause} AND {col} IS NOT NULL AND {col} BETWEEN ? AND ?
            ORDER BY {col} {order}, ts ASC
            LIMIT 1
            """,
            params + (low, high),
        )
        return cursor.fetchone()

    l1 = one('U_L1_N_Netz_max')
    l2 = one('U_L2_N_Netz_max')
    l3 = one('U_L3_N_Netz_max')
    fmax = one('f_Netz_max')
    l1n = one('U_L1_N_Netz_min', 'ASC')
    l2n = one('U_L2_N_Netz_min', 'ASC')
    l3n = one('U_L3_N_Netz_min', 'ASC')
    fmin = one('f_Netz_min', 'ASC')

    rows = [r for r in [l1, l2, l3] if r]
    if not rows:
        return None

    vmax_row = max(rows, key=lambda x: x[1])
    rows_min = [r for r in [l1n, l2n, l3n] if r]
    vmin_row = min(rows_min, key=lambda x: x[1]) if rows_min else None
    return {
        'source': 'data_monthly',
        'accuracy': 'month',
        'u_l1_l2': {'ts': l1[0], 'value': round(l1[1] * SQRT3, 2)} if l1 else None,
        'u_l2_l3': {'ts': l2[0], 'value': round(l2[1] * SQRT3, 2)} if l2 else None,
        'u_l3_l1': {'ts': l3[0], 'value': round(l3[1] * SQRT3, 2)} if l3 else None,
        'u_voltage_max': {'ts': vmax_row[0], 'value': round(vmax_row[1] * SQRT3, 2)},
        'u_voltage_min': {'ts': vmin_row[0], 'value': round(vmin_row[1] * SQRT3, 2)} if vmin_row else None,
        'f_netz_max': {'ts': fmax[0], 'value': round(fmax[1], 4)} if fmax else None,
        'f_netz_min': {'ts': fmin[0], 'value': round(fmin[1], 4)} if fmin else None,
    }


def _select_maxima_collector(cursor, period, date_param):
    if period == 'tag':
        return _fetch_maxima_raw(cursor, period, date_param) or _fetch_maxima_1min(cursor, period, date_param)
    if period == 'monat':
        return _fetch_maxima_1min(cursor, period, date_param) or _fetch_maxima_15min(cursor, period, date_param)
    if period == 'jahr':
        return _fetch_maxima_15min(cursor, period, date_param) or _fetch_maxima_monthly(cursor, period, date_param)
    # gesamt
    return _fetch_maxima_15min(cursor, period, date_param) or _fetch_maxima_monthly(cursor, period, date_param)


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


@bp.route('/api/netzqualitaet/zeitraum')
def api_netzqualitaet_zeitraum():
    """Zeitraumansicht Netzqualität mit automatischem Aggregations-Sprung.

    Parameter:
      - period: tag | monat | jahr | gesamt
      - date:   YYYY-MM-DD (Ankerdatum, optional)

    Aggregationslogik:
      - tag:    raw_data (5min), fallback data_1min (5min)
      - monat:  data_15min, fallback data_1min (15min)
      - jahr:   data_monthly, fallback data_15min (1d)
      - gesamt: data_monthly, fallback data_15min (1 Monat)
    """
    try:
        period = (request.args.get('period') or 'tag').strip().lower()
        if period not in {'tag', 'monat', 'jahr', 'gesamt'}:
            return jsonify({'error': 'Ungueltiger period-Parameter'}), 400

        anchor, date_param = _parse_anchor_date(request.args.get('date'))
        conn = get_db_connection()
        cursor = conn.cursor()

        source = 'unbekannt'
        rows = []

        if period == 'tag':
            rows = _query_tag_raw(cursor, date_param)
            source = 'raw_data (5min)'
            if not rows:
                rows = _query_tag_from_1min(cursor, date_param)
                source = 'data_1min (5min, fallback)'

        elif period == 'monat':
            rows = _query_month_15min(cursor, date_param)
            source = 'data_15min'
            if not rows:
                rows = _query_month_from_1min(cursor, date_param)
                source = 'data_1min (15min, fallback)'

        elif period == 'jahr':
            rows = _query_year_monthly(cursor, date_param)
            source = 'data_monthly'
            if not rows:
                rows = _query_year_15min_daily(cursor, date_param)
                source = 'data_15min (1d, fallback)'

        elif period == 'gesamt':
            rows = _query_gesamt_monthly(cursor)
            source = 'data_monthly'
            if not rows:
                rows = _query_gesamt_15min_monthly(cursor)
                source = 'data_15min (1 Monat, fallback)'

        conn.close()

        datapoints = _rows_to_datapoints(rows)
        start_local, end_local = _period_bounds(period, anchor)

        if period == 'gesamt':
            if datapoints:
                window_start_ts = datapoints[0]['ts']
                window_end_ts = datapoints[-1]['ts'] + 86400
            else:
                window_start_ts = None
                window_end_ts = None
        else:
            window_start_ts = int(start_local.timestamp())
            window_end_ts = int(end_local.timestamp())

        today = datetime.now()
        if period == 'tag':
            has_next = anchor.date() < today.date()
        elif period == 'monat':
            has_next = (anchor.year, anchor.month) < (today.year, today.month)
        elif period == 'jahr':
            has_next = anchor.year < today.year
        else:
            has_next = False

        return jsonify({
            'date': date_param,
            'period': period,
            'source': source,
            'datapoints': datapoints,
            'window_start_ts': window_start_ts,
            'window_end_ts': window_end_ts,
            'has_prev': period != 'gesamt',
            'has_next': has_next,
        })

    except Exception as e:
        logging.error(f"Netzqualität Zeitraum API Fehler: {e}")
        return api_error_response(e, "API netzqualitaet/zeitraum")


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


@bp.route('/api/netzqualitaet/maxima')
def api_netzqualitaet_maxima():
    """Maxima-Sammler fuer Tag/Monat/Jahr/Gesamt inkl. Zeitpunkt.

    Parameter:
      - period: tag | monat | jahr | gesamt
      - date:   YYYY-MM-DD (Ankerdatum, optional)
    """
    try:
        period = (request.args.get('period') or 'tag').strip().lower()
        if period not in {'tag', 'monat', 'jahr', 'gesamt'}:
            return jsonify({'error': 'Ungueltiger period-Parameter'}), 400

        _, date_param = _parse_anchor_date(request.args.get('date'))
        conn = get_db_connection()
        cursor = conn.cursor()
        maxima = _select_maxima_collector(cursor, period, date_param)
        conn.close()

        return jsonify({
            'period': period,
            'date': date_param,
            'available': maxima is not None,
            'maxima': maxima,
        })

    except Exception as e:
        logging.error(f"Netzqualität Maxima API Fehler: {e}")
        return api_error_response(e, "API netzqualitaet/maxima")
