"""
Blueprint: Verbraucher-APIs (WP, Heizpatrone, Wattpilot, Haushalt).

Enthält: /api/verbraucher, /api/verbraucher/tag, /api/verbraucher/monat,
         /api/verbraucher/jahr, /api/verbraucher/gesamt,
         /api/verbraucher/wp_leistung
"""
import csv
import math
import os
import re
from datetime import datetime, timedelta, timezone
from flask import Blueprint, jsonify, request
import config
from routes.helpers import get_db_connection, api_error_response, validate_year_month, tag_table

bp = Blueprint('verbraucher', __name__)


def _read_wp_protocol_points(start_ts, end_ts):
    """Liest WP-Leistungsprotokoll als (ts, power_w, within_limit)."""
    protocol_file = getattr(
        config,
        'WP_POWER_PROTOCOL_FILE',
        os.path.join(config.BASE_DIR, 'logs', 'wp_netzbetreiber_leistung.csv'),
    )
    if not os.path.exists(protocol_file):
        return [], protocol_file

    points = []
    with open(protocol_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = int(float(row.get('ts_epoch') or 0))
                if ts <= 0:
                    continue
                if ts < start_ts or ts > end_ts:
                    continue
                power_w = float(row.get('wp_max_w') or 0.0)
                within_limit = int(float(row.get('within_limit') or 1))
                points.append((ts, abs(power_w), 1 if within_limit != 0 else 0))
            except Exception:
                continue

    return points, protocol_file


def _read_wp_points_from_db_fallback(start_ts, end_ts):
    """Fallback: WP-Leistung aus data_1min/data_15min lesen (ABCD-konform read-only DB)."""
    conn = get_db_connection()
    if not conn:
        return [], 'db:fallback(unavailable)'

    cursor = conn.cursor()

    table = 'data_1min'
    try:
        cursor.execute(
            """
            SELECT COUNT(*) FROM data_1min
            WHERE ts >= ? AND ts <= ?
            """,
            (start_ts, end_ts),
        )
        count_1min = cursor.fetchone()[0]
        if not count_1min:
            table = 'data_15min'
    except Exception:
        table = 'data_15min'

    points = []
    try:
        limit_w = float(getattr(config, 'WP_LEISTUNG_LIMIT_W', 4200))
        cursor.execute(
            f"""
            SELECT ts, ABS(COALESCE(P_WP_max, 0))
            FROM {table}
            WHERE ts >= ? AND ts <= ?
            ORDER BY ts
            """,
            (start_ts, end_ts),
        )
        for ts, power_w in cursor.fetchall():
            p = abs(float(power_w or 0.0))
            points.append((int(ts), p, 1 if p <= limit_w else 0))
    finally:
        conn.close()

    return points, f'db:fallback({table})'


def _downsample_wp_points(points, start_ts, end_ts, max_points):
    """Verdichtet Zeitreihe per Bucket-Maximum, behält Peaks für Nachweis."""
    if len(points) <= max_points:
        return points, 0

    span = max(1, end_ts - start_ts)
    bucket_s = max(60, int(math.ceil(span / max_points)))

    sampled = []
    bucket_ts = None
    bucket_max = 0.0
    bucket_within = 1

    for ts, power_w, within_limit in points:
        current_bucket = (ts // bucket_s) * bucket_s
        if bucket_ts is None:
            bucket_ts = current_bucket

        if current_bucket != bucket_ts:
            sampled.append((bucket_ts, bucket_max, bucket_within))
            bucket_ts = current_bucket
            bucket_max = 0.0
            bucket_within = 1

        if power_w > bucket_max:
            bucket_max = power_w
        if within_limit == 0:
            bucket_within = 0

    if bucket_ts is not None:
        sampled.append((bucket_ts, bucket_max, bucket_within))

    return sampled, bucket_s


def _compute_wp_stats(points):
    """Berechnet Kennzahlen für Infozeile aus gefilterter WP-Zeitreihe."""
    if not points:
        return {
            'max_w': 0.0,
            'max_ts': None,
            'violations': 0,
            'day_max': None,
            'month_max': None,
        }

    max_point = max(points, key=lambda p: p[1])
    violations = sum(1 for _, _, within in points if within == 0)

    day_map = {}
    month_map = {}
    for ts, power_w, _ in points:
        dt = datetime.fromtimestamp(ts)
        day_key = dt.strftime('%Y-%m-%d')
        month_key = dt.strftime('%Y-%m')

        if day_key not in day_map or power_w > day_map[day_key]['max_w']:
            day_map[day_key] = {'label': day_key, 'max_w': power_w, 'ts': ts}
        if month_key not in month_map or power_w > month_map[month_key]['max_w']:
            month_map[month_key] = {'label': month_key, 'max_w': power_w, 'ts': ts}

    day_max = max(day_map.values(), key=lambda x: x['max_w']) if day_map else None
    month_max = max(month_map.values(), key=lambda x: x['max_w']) if month_map else None

    return {
        'max_w': round(max_point[1], 1),
        'max_ts': int(max_point[0]),
        'violations': int(violations),
        'day_max': {
            'day': day_max['label'],
            'max_w': round(day_max['max_w'], 1),
            'ts': int(day_max['ts']),
        } if day_max else None,
        'month_max': {
            'month': month_max['label'],
            'max_w': round(month_max['max_w'], 1),
            'ts': int(month_max['ts']),
        } if month_max else None,
    }


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


# SOC-Stress-Schwellen für die Akku-Stress-Analyse (LFP): dauerhafte Voll-/Tiefladung belastet die Zellen.
SOC_STRESS_HIGH_PCT = 95   # Hoch-Stress: SOC oberhalb → Vollladungs-Belastung
SOC_STRESS_LOW_PCT = 10    # Tief-Stress: SOC unterhalb → Tiefentladungs-Belastung

# SOC-Quellen mit Sub-Tages-Auflösung (feinste zuerst). daily_data/data_monthly
# führen nur einen SOC-Wert je Periode und taugen NICHT für Stress-Dauern.
_SOC_SOURCE_TABLES = ['data_1min', 'data_15min', 'hourly_data']


def _resolve_soc_table(cursor, start_ts, end_ts):
    """Feinste SOC-Tabelle, die den Perioden-Anfang abdeckt; sonst die mit weitester Rückreichweite."""
    overlapping = []
    for table in _SOC_SOURCE_TABLES:
        try:
            row = cursor.execute(f"SELECT MIN(ts), MAX(ts) FROM {table}").fetchone()
        except Exception:
            continue
        if not row or row[0] is None:
            continue
        tmin, tmax = int(row[0]), int(row[1])
        if tmax < start_ts or tmin >= end_ts:
            continue
        if tmin <= start_ts:
            return table
        overlapping.append((tmin, table))
    if overlapping:
        overlapping.sort(key=lambda item: item[0])
        return overlapping[0][1]
    return 'hourly_data'


def _fetch_soc_points(cursor, start_ts, end_ts, table=None):
    """Liest (ts, soc) aus der passendsten SOC-Quelle für den Zeitraum."""
    table = table or _resolve_soc_table(cursor, start_ts, end_ts)
    try:
        cursor.execute(
            f"SELECT ts, SOC_Batt_avg FROM {table} WHERE ts >= ? AND ts < ? ORDER BY ts",
            (start_ts, end_ts),
        )
        rows = cursor.fetchall()
        return [(int(ts), float(soc)) for ts, soc in rows if soc is not None], table
    except Exception:
        return [], table


def _infer_soc_interval_s(points):
    """Ermittelt die typische Messintervall-Länge aus den Zeitstempeln."""
    if len(points) <= 1:
        return 300
    deltas = [
        points[i][0] - points[i - 1][0]
        for i in range(1, len(points))
        if points[i][0] > points[i - 1][0]
    ]
    if not deltas:
        return 300
    deltas.sort()
    return max(60, int(deltas[len(deltas) // 2]))


def _downsample_soc_points(points, bucket_s=300):
    """Aggregiert SOC-Punkte zu gleichmäßigen Buckets, z. B. 5-Minuten-Schritten."""
    if not points:
        return []

    sampled = []
    bucket_ts = None
    bucket_values = []
    for ts, soc in points:
        bucket = int(int(ts) // bucket_s) * bucket_s
        if bucket_ts is None:
            bucket_ts = bucket
            bucket_values = [float(soc)]
            continue
        if bucket != bucket_ts:
            sampled.append((bucket_ts, sum(bucket_values) / len(bucket_values)))
            bucket_ts = bucket
            bucket_values = [float(soc)]
        else:
            bucket_values.append(float(soc))

    if bucket_ts is not None:
        sampled.append((bucket_ts, sum(bucket_values) / len(bucket_values)))

    return sampled


def _summarize_soc_points(points, interval_s=None):
    """SOC-Kennzahlen: Max/Min sowie Stress-Dauer über/unter den SOC-Schwellen."""
    values = [soc for _, soc in points if soc is not None]
    if not values:
        return {
            'current': None,
            'day_max': None,
            'day_min': None,
            'high_stress_minutes': 0.0,
            'low_stress_minutes': 0.0,
        }

    if interval_s is None:
        interval_s = _infer_soc_interval_s(points)

    high_stress_minutes = 0.0
    low_stress_minutes = 0.0
    for _, soc in points:
        if soc is None:
            continue
        if soc > SOC_STRESS_HIGH_PCT:
            high_stress_minutes += (interval_s / 60.0)
        if soc < SOC_STRESS_LOW_PCT:
            low_stress_minutes += (interval_s / 60.0)

    available_minutes = len(values) * (interval_s / 60.0)
    stress_minutes = high_stress_minutes + low_stress_minutes
    return {
        'current': round(values[-1], 1),
        'day_max': round(max(values), 1),
        'day_min': round(min(values), 1),
        'high_stress_minutes': round(high_stress_minutes, 1),
        'low_stress_minutes': round(low_stress_minutes, 1),
        'available_hours': round(available_minutes / 60.0, 1),
        'stress_pct': round(stress_minutes / available_minutes * 100.0, 1) if available_minutes else 0.0,
        'high_stress_pct': round(high_stress_minutes / available_minutes * 100.0, 1) if available_minutes else 0.0,
        'low_stress_pct': round(low_stress_minutes / available_minutes * 100.0, 1) if available_minutes else 0.0,
    }


def _period_efficiency_pct(cursor, start_ts, end_ts, table):
    """Batterie-Wirkungsgrad (Entladung/Ladung in %) über den Zeitraum.

    Wählt die passenden Energiespalten je Tabelle (data_1min: W_inBatt/W_outBatt;
    hourly_data: W_Batt_Charge_total/W_Batt_Discharge_total). None, wenn keine
    Ladeenergie oder Spalten fehlen (z. B. STATS-Fallback-Tabelle).
    """
    try:
        cols = {r[1] for r in cursor.execute(f"PRAGMA table_info({table})")}
    except Exception:
        return None
    if {'W_inBatt', 'W_outBatt'} <= cols:
        ch, dis = 'W_inBatt', 'W_outBatt'
    elif {'W_Batt_Charge_total', 'W_Batt_Discharge_total'} <= cols:
        ch, dis = 'W_Batt_Charge_total', 'W_Batt_Discharge_total'
    else:
        return None
    try:
        row = cursor.execute(
            f"SELECT SUM({ch}), SUM({dis}) FROM {table} WHERE ts >= ? AND ts < ?",
            (start_ts, end_ts),
        ).fetchone()
    except Exception:
        return None
    charge = row[0] or 0.0
    discharge = row[1] or 0.0
    if charge <= 0:
        return None
    return round(discharge / charge * 100.0, 1)


def _aggregate_soc_buckets(points, key_fn, interval_s=None):
    """Aggregiert SOC-Punkte je Bucket (key_fn(ts)) zu Max/Min + Stress-Dauer."""
    if interval_s is None:
        interval_s = _infer_soc_interval_s(points)
    minutes = interval_s / 60.0
    buckets = {}
    for ts, soc in points:
        if soc is None:
            continue
        key = key_fn(ts)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {'max': soc, 'min': soc, 'high_min': 0.0, 'low_min': 0.0}
            buckets[key] = bucket
        if soc > bucket['max']:
            bucket['max'] = soc
        if soc < bucket['min']:
            bucket['min'] = soc
        if soc > SOC_STRESS_HIGH_PCT:
            bucket['high_min'] += minutes
        if soc < SOC_STRESS_LOW_PCT:
            bucket['low_min'] += minutes
    return buckets


# Zusätzliche Fritz!DECT-Verbraucher für die Aufschlüsselung (neben WP/HP/Wattpilot).
# Whitelist der erlaubten Daily-Tabellen (kein User-Input → keine Injection).
# Status-only-Geräte (fussbodenheizung: Thermostat ohne Leistungsmessung) sind
# bewusst NICHT enthalten, da deren energy_total_wh kein realer Zähler ist.
FRITZ_BREAKDOWN_DEVICES = [
    ('klima',    'klimaanlage_daily'),
    ('gefrier',  'gefriertruhe_daily'),
    ('lueftung', 'lueftung_daily'),
]
_FRITZ_DAILY_TABLES = {t for _, t in FRITZ_BREAKDOWN_DEVICES}


def _load_fritz_device_daily(cursor, table, first_ts, last_ts):
    """Lädt {day_ts: energy_wh} aus einer Fritz!DECT-Daily-Tabelle.

    `table` muss aus der internen Whitelist stammen.
    """
    data = {}
    if table not in _FRITZ_DAILY_TABLES:
        return data
    try:
        cursor.execute(
            f"SELECT ts, energy_wh FROM {table} WHERE ts >= ? AND ts < ? ORDER BY ts",
            (first_ts, last_ts),
        )
        for ts, energy_wh in cursor.fetchall():
            day_ts = (int(ts) // 86400) * 86400
            data[day_ts] = max(0.0, energy_wh or 0)   # Negativ-Guard
    except Exception:
        pass
    return data


def _sum_fritz_daily_kwh(cursor, table, first_ts, last_ts):
    """Summe einer Fritz!DECT-Daily-Tabelle im Zeitraum als kWh (Negativ-geguarded)."""
    if table not in _FRITZ_DAILY_TABLES:
        return 0.0
    try:
        cursor.execute(
            f"SELECT SUM(MAX(energy_wh, 0)) FROM {table} WHERE ts >= ? AND ts < ?",
            (first_ts, last_ts),
        )
        row = cursor.fetchone()
        return float((row[0] or 0)) / 1000.0
    except Exception:
        return 0.0


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


def _build_average_summary(totals, divisor, unit_label):
    """Leitet Durchschnittswerte fuer die Kopfzeile aus bestehenden Aggregaten ab."""
    if divisor <= 0:
        return None

    return {
        'unit_label': unit_label,
        'count': int(divisor),
        'values': {
            'wp': round((totals.get('wp') or 0) / divisor, 2),
            'heizpatrone': round((totals.get('heizpatrone') or 0) / divisor, 2),
            'wattpilot': round((totals.get('wattpilot') or 0) / divisor, 2),
            'klima': round((totals.get('klima') or 0) / divisor, 2),
            'gefrier': round((totals.get('gefrier') or 0) / divisor, 2),
            'lueftung': round((totals.get('lueftung') or 0) / divisor, 2),
        },
    }


@bp.route('/api/verbraucher/batterie')
def api_verbraucher_batterie():
    """Akku-Stress-Analyse: SOC-Verlauf (Tag) bzw. Stress-Dauer je Tag/Monat/Jahr."""
    try:
        period = request.args.get('period', 'tag')
        if period not in {'tag', 'monat', 'jahr', 'gesamt'}:
            period = 'tag'

        date_param = request.args.get('date')
        year = request.args.get('year', type=int)
        month = request.args.get('month', type=int)

        if period == 'tag':
            if not date_param:
                date_param = datetime.now().strftime('%Y-%m-%d')
            try:
                day_dt = datetime.strptime(date_param, '%Y-%m-%d')
            except ValueError:
                return jsonify({'error': 'Ungültiges Datumsformat'}), 400
            start_ts = int(day_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            end_ts = int((day_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        elif period == 'gesamt':
            start_ts = 0
            end_ts = int((datetime.now() + timedelta(days=1)).timestamp())
        else:
            if not year or not month:
                now = datetime.now()
                year, month = now.year, now.month
            valid, err = validate_year_month(year, month)
            if err:
                return err
            year, month = valid
            if period == 'monat':
                first_day = datetime(year, month, 1)
                last_day = datetime(year + (1 if month == 12 else 0), (month % 12) + 1, 1)
                start_ts = int(first_day.timestamp())
                end_ts = int(last_day.timestamp())
            else:
                start_ts = int(datetime(year, 1, 1).timestamp())
                end_ts = int(datetime(year + 1, 1, 1).timestamp())

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'DB nicht verfügbar'}), 500
        cursor = conn.cursor()
        points, table = _fetch_soc_points(cursor, start_ts, end_ts)
        efficiency_pct = _period_efficiency_pct(cursor, start_ts, end_ts, table)
        conn.close()

        thresholds = {'high': SOC_STRESS_HIGH_PCT, 'low': SOC_STRESS_LOW_PCT}

        # Tag: SOC-Verlauf als 5-Minuten-Linie + Tages-Stresskennzahlen
        if period == 'tag':
            summary = _summarize_soc_points(points)
            summary['efficiency_pct'] = efficiency_pct
            tag_points = _downsample_soc_points(points, bucket_s=300)
            return jsonify({
                'period': period,
                'date': date_param,
                'table': table,
                'thresholds': thresholds,
                'points': [{'ts': ts, 'soc': round(soc, 1)} for ts, soc in tag_points],
                'summary': summary,
            })

        # Monat/Jahr/Gesamt: Stress-Dauer je Bucket (Tag/Monat/Jahr) als Balken
        interval_s = _infer_soc_interval_s(points)
        if period == 'monat':
            def key_fn(ts):
                return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
            day_count = (datetime(year + (1 if month == 12 else 0), (month % 12) + 1, 1)
                         - datetime(year, month, 1)).days
            labels = [(f'{year:04d}-{month:02d}-{d:02d}', f'{d:02d}') for d in range(1, day_count + 1)]
        elif period == 'jahr':
            def key_fn(ts):
                return datetime.fromtimestamp(ts).strftime('%Y-%m')
            labels = [(f'{year:04d}-{m:02d}', datetime(year, m, 1).strftime('%b')) for m in range(1, 13)]
        else:
            def key_fn(ts):
                return datetime.fromtimestamp(ts).strftime('%Y')
            years = sorted({datetime.fromtimestamp(ts).year for ts, _ in points})
            labels = [(f'{y:04d}', f'{y:04d}') for y in years]

        buckets = _aggregate_soc_buckets(points, key_fn, interval_s)

        chart_points = []
        for key, label in labels:
            bucket = buckets.get(key)
            if bucket is None:
                chart_points.append({
                    'label': label,
                    'soc_max': None,
                    'soc_min': None,
                    'high_stress_minutes': 0.0,
                    'low_stress_minutes': 0.0,
                })
            else:
                chart_points.append({
                    'label': label,
                    'soc_max': round(bucket['max'], 1),
                    'soc_min': round(bucket['min'], 1),
                    'high_stress_minutes': round(bucket['high_min'], 1),
                    'low_stress_minutes': round(bucket['low_min'], 1),
                })

        soc_max_values = [cp['soc_max'] for cp in chart_points if cp['soc_max'] is not None]
        soc_min_values = [cp['soc_min'] for cp in chart_points if cp['soc_min'] is not None]
        high_stress_minutes = sum(cp['high_stress_minutes'] for cp in chart_points)
        low_stress_minutes = sum(cp['low_stress_minutes'] for cp in chart_points)
        available_minutes = len(points) * (interval_s / 60.0)
        stress_minutes = high_stress_minutes + low_stress_minutes
        summary = {
            'current': round(points[-1][1], 1) if points else None,
            'day_max': round(max(soc_max_values), 1) if soc_max_values else None,
            'day_min': round(min(soc_min_values), 1) if soc_min_values else None,
            'high_stress_minutes': round(high_stress_minutes, 1),
            'low_stress_minutes': round(low_stress_minutes, 1),
            'available_hours': round(available_minutes / 60.0, 1),
            'stress_pct': round(stress_minutes / available_minutes * 100.0, 1) if available_minutes else 0.0,
            'high_stress_pct': round(high_stress_minutes / available_minutes * 100.0, 1) if available_minutes else 0.0,
            'low_stress_pct': round(low_stress_minutes / available_minutes * 100.0, 1) if available_minutes else 0.0,
            'efficiency_pct': efficiency_pct,
        }

        response = {
            'period': period,
            'table': table,
            'thresholds': thresholds,
            'chart_points': chart_points,
            'summary': summary,
        }
        if period in ('monat', 'jahr'):
            response['year'] = year
        if period == 'monat':
            response['month'] = month
        return jsonify(response)

    except Exception as e:
        return api_error_response(e, 'Verbraucher-Batterie')


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
            table = tag_table(cursor, date_param)
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

        fritz_tag_power_maps = {
            'klima': {},
            'gefrier': {},
            'lueftung': {},
        }
        fritz_tag_predicates = {
            'klima': "(lower(COALESCE(device_id, '')) IN ('klima', 'klimaanlage') OR lower(COALESCE(name, '')) LIKE '%klima%')",
            'gefrier': "(lower(COALESCE(device_id, '')) IN ('gefrier', 'gefriertruhe') OR lower(COALESCE(name, '')) LIKE '%gefrier%')",
            'lueftung': "(lower(COALESCE(device_id, '')) IN ('lueftung', 'lüftung') OR lower(COALESCE(name, '')) LIKE '%lueft%' OR lower(COALESCE(name, '')) LIKE '%lüft%')",
        }
        for key, predicate in fritz_tag_predicates.items():
            try:
                cursor.execute(
                    f"""
                    SELECT
                        CAST((ts / 300) AS INTEGER) * 300 AS ts5,
                        AVG(power_w) AS p_fritz
                    FROM fritzdect_readings
                    {where}
                      AND {predicate}
                    GROUP BY CAST((ts / 300) AS INTEGER)
                    """,
                    where_params,
                )
                for r in cursor.fetchall():
                    fritz_tag_power_maps[key][int(r[0])] = max(0.0, r[1] or 0.0)
            except Exception:
                pass

        conn.close()

        datapoints = []
        totals = {
            'wp': 0,
            'heizpatrone': 0,
            'wattpilot': 0,
            'klima': 0,
            'gefrier': 0,
            'lueftung': 0,
            'haushalt': 0,
            'gesamt': 0,
        }

        for row in rows:
            ts5, p_wp, p_gesamt, w_wp, w_gesamt = row
            p_wp = max(0, p_wp or 0)
            p_gesamt = max(0, p_gesamt or 0)
            w_wp = max(0, w_wp or 0)
            w_gesamt = max(0, w_gesamt or 0)

            p_heizpatrone = heizpatrone_power_map.get(int(ts5), 0)
            p_wattpilot = wattpilot_power_map.get(int(ts5), 0)
            p_klima = fritz_tag_power_maps['klima'].get(int(ts5), 0)
            p_gefrier = fritz_tag_power_maps['gefrier'].get(int(ts5), 0)
            p_lueftung = fritz_tag_power_maps['lueftung'].get(int(ts5), 0)
            p_sum = p_wp + p_heizpatrone + p_wattpilot + p_klima + p_gefrier + p_lueftung
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
                w_klima = w_gesamt * (p_klima / p_norm)
                w_gefrier = w_gesamt * (p_gefrier / p_norm)
                w_lueftung = w_gesamt * (p_lueftung / p_norm)
                w_haushalt = w_gesamt * (p_haushalt / p_norm)
                w_wp_actual = w_gesamt * (p_wp / p_norm)
            else:
                w_heizpatrone = 0
                w_wattpilot = 0
                w_klima = 0
                w_gefrier = 0
                w_lueftung = 0
                w_haushalt = 0
                w_wp_actual = w_wp

            totals['wp'] += w_wp_actual
            totals['heizpatrone'] += w_heizpatrone
            totals['wattpilot'] += w_wattpilot
            totals['klima'] += w_klima
            totals['gefrier'] += w_gefrier
            totals['lueftung'] += w_lueftung
            totals['haushalt'] += w_haushalt
            totals['gesamt'] += w_gesamt

            datapoints.append({
                'timestamp': int(ts5),
                'p_wp': round(p_wp, 1),
                'p_heizpatrone': round(p_heizpatrone, 1),
                'p_wattpilot': round(p_wattpilot, 1),
                'p_klima': round(p_klima, 1),
                'p_gefrier': round(p_gefrier, 1),
                'p_lueftung': round(p_lueftung, 1),
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


@bp.route('/api/verbraucher/wp_leistung')
def api_verbraucher_wp_leistung():
    """WP-Leistungsnachweis (ABCD-konform): Read-only aus Dauerprotokolldatei."""
    try:
        now_ts = int(datetime.now().timestamp())
        range_days = request.args.get('range_days', default=30, type=int)
        range_days = max(1, min(range_days, 3650))

        start_ts = request.args.get('start_ts', type=int)
        end_ts = request.args.get('end_ts', type=int)
        if end_ts is None:
            end_ts = now_ts
        if start_ts is None:
            start_ts = end_ts - (range_days * 86400)

        if start_ts >= end_ts:
            return jsonify({'error': 'start_ts muss kleiner als end_ts sein'}), 400

        max_points = request.args.get('max_points', default=2400, type=int)
        max_points = max(200, min(max_points, 20000))

        points, source_file = _read_wp_protocol_points(start_ts, end_ts)
        if not points:
            points, source_file = _read_wp_points_from_db_fallback(start_ts, end_ts)
        stats = _compute_wp_stats(points)
        sampled, bucket_s = _downsample_wp_points(points, start_ts, end_ts, max_points)

        payload_points = [
            {
                'ts': int(ts),
                'power_w': round(power_w, 1),
                'within_limit': int(within),
            }
            for ts, power_w, within in sampled
        ]

        return jsonify({
            'start_ts': int(start_ts),
            'end_ts': int(end_ts),
            'limit_w': float(getattr(config, 'WP_LEISTUNG_LIMIT_W', 4200)),
            'count_raw': len(points),
            'count': len(payload_points),
            'bucket_seconds': int(bucket_s),
            'source_file': source_file,
            'stats': stats,
            'points': payload_points,
        })

    except Exception as e:
        return api_error_response(e, 'Verbraucher-WP-Leistung')


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

        fritz_by_day = {
            key: _load_fritz_device_daily(cursor, table, first_ts, last_ts)
            for key, table in FRITZ_BREAKDOWN_DEVICES
        }

        conn.close()

        datapoints = []
        totals = {'wp': 0, 'heizpatrone': 0, 'wattpilot': 0,
                  'klima': 0, 'gefrier': 0, 'lueftung': 0, 'haushalt': 0, 'gesamt': 0}

        for row in daily_rows:
            ts, w_wp, w_consumption, w_direct, w_batt_dis, w_netz = row
            w_wp = w_wp or 0
            w_consumption = w_consumption or 0
            if w_consumption <= 0:
                w_consumption = (w_direct or 0) + (w_batt_dis or 0) + (w_netz or 0)

            day_key = (int(ts) // 86400) * 86400
            w_wattpilot = wattpilot_by_day.get(day_key, {}).get('energy_wh', 0)
            w_heizpatrone = heizpatrone_by_day.get(day_key, 0)
            w_klima = fritz_by_day['klima'].get(day_key, 0)
            w_gefrier = fritz_by_day['gefrier'].get(day_key, 0)
            w_lueftung = fritz_by_day['lueftung'].get(day_key, 0)
            w_haushalt = max(0, w_consumption - w_wp - w_heizpatrone - w_wattpilot
                             - w_klima - w_gefrier - w_lueftung)

            wp_kwh = w_wp / 1000.0
            heizpatrone_kwh = w_heizpatrone / 1000.0
            wattpilot_kwh = w_wattpilot / 1000.0
            klima_kwh = w_klima / 1000.0
            gefrier_kwh = w_gefrier / 1000.0
            lueftung_kwh = w_lueftung / 1000.0
            haushalt_kwh = w_haushalt / 1000.0
            gesamt_kwh = w_consumption / 1000.0

            totals['wp'] += wp_kwh
            totals['heizpatrone'] += heizpatrone_kwh
            totals['wattpilot'] += wattpilot_kwh
            totals['klima'] += klima_kwh
            totals['gefrier'] += gefrier_kwh
            totals['lueftung'] += lueftung_kwh
            totals['haushalt'] += haushalt_kwh
            totals['gesamt'] += gesamt_kwh

            datapoints.append({
                'day': datetime.fromtimestamp(ts).day,
                'w_wp': round(wp_kwh, 2),
                'w_heizpatrone': round(heizpatrone_kwh, 2),
                'w_wattpilot': round(wattpilot_kwh, 2),
                'w_klima': round(klima_kwh, 2),
                'w_gefrier': round(gefrier_kwh, 2),
                'w_lueftung': round(lueftung_kwh, 2),
                'w_haushalt': round(haushalt_kwh, 2),
                'w_gesamt': round(gesamt_kwh, 2),
            })

        if heizpatrone_month_total > totals['heizpatrone']:
            totals['heizpatrone'] = heizpatrone_month_total
            totals['haushalt'] = max(
                0,
                totals['gesamt'] - totals['wp'] - totals['heizpatrone'] - totals['wattpilot']
                - totals['klima'] - totals['gefrier'] - totals['lueftung'],
            )

        average_summary = _build_average_summary(totals, len(datapoints), 'Tag')

        return jsonify({
            'year': year,
            'month': month,
            'datapoints': datapoints,
            'totals': {k: round(v, 2) for k, v in totals.items()},
            'average_summary': average_summary,
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

        # Fritz!DECT-Zusatzverbraucher pro Monat aus Daily-Tabellen summieren
        fritz_by_month = {}
        for mon in range(1, 13):
            m_first = int(datetime(year, mon, 1).timestamp())
            m_last = int(datetime(year + (1 if mon == 12 else 0), (mon % 12) + 1, 1).timestamp())
            fritz_by_month[mon] = {
                key: _sum_fritz_daily_kwh(cursor, table, m_first, m_last)
                for key, table in FRITZ_BREAKDOWN_DEVICES
            }

        conn.close()

        datapoints = []
        totals = {'wp': 0, 'heizpatrone': 0, 'wattpilot': 0,
                  'klima': 0, 'gefrier': 0, 'lueftung': 0, 'haushalt': 0, 'gesamt': 0}

        for mon, gesamt, wp, heiz, wattpilot in rows:
            gesamt = gesamt or 0
            wp = wp or 0
            heiz = heiz or 0
            wattpilot = wattpilot or 0
            fz = fritz_by_month.get(mon, {})
            klima = fz.get('klima', 0)
            gefrier = fz.get('gefrier', 0)
            lueftung = fz.get('lueftung', 0)
            haushalt = max(0, gesamt - wp - heiz - wattpilot - klima - gefrier - lueftung)

            totals['wp'] += wp
            totals['heizpatrone'] += heiz
            totals['wattpilot'] += wattpilot
            totals['klima'] += klima
            totals['gefrier'] += gefrier
            totals['lueftung'] += lueftung
            totals['haushalt'] += haushalt
            totals['gesamt'] += gesamt

            datapoints.append({
                'month': mon,
                'w_wp': round(wp, 2),
                'w_heizpatrone': round(heiz, 2),
                'w_wattpilot': round(wattpilot, 2),
                'w_klima': round(klima, 2),
                'w_gefrier': round(gefrier, 2),
                'w_lueftung': round(lueftung, 2),
                'w_haushalt': round(haushalt, 2),
                'w_gesamt': round(gesamt, 2),
            })

        average_summary = _build_average_summary(totals, len(datapoints), 'Monat')

        return jsonify({
            'year': year,
            'datapoints': datapoints,
            'totals': {k: round(v, 2) for k, v in totals.items()},
            'average_summary': average_summary,
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
                 COUNT(*),
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

        # Fritz!DECT-Zusatzverbraucher pro Jahr aus Daily-Tabellen summieren
        fritz_by_year = {}
        for (yr_row,) in [(r[0],) for r in rows]:
            y_first = int(datetime(yr_row, 1, 1).timestamp())
            y_last = int(datetime(yr_row + 1, 1, 1).timestamp())
            fritz_by_year[yr_row] = {
                key: _sum_fritz_daily_kwh(cursor, table, y_first, y_last)
                for key, table in FRITZ_BREAKDOWN_DEVICES
            }

        conn.close()

        datapoints = []
        totals = {'wp': 0, 'heizpatrone': 0, 'wattpilot': 0,
                  'klima': 0, 'gefrier': 0, 'lueftung': 0, 'haushalt': 0, 'gesamt': 0}
        month_count_total = 0

        for yr, month_count, gesamt, wp, heiz, wattpilot in rows:
            gesamt = gesamt or 0
            wp = wp or 0
            heiz = heiz or 0
            wattpilot = wattpilot or 0
            if gesamt < 1:
                continue
            fz = fritz_by_year.get(yr, {})
            klima = fz.get('klima', 0)
            gefrier = fz.get('gefrier', 0)
            lueftung = fz.get('lueftung', 0)
            haushalt = max(0, gesamt - wp - heiz - wattpilot - klima - gefrier - lueftung)
            month_count_total += month_count or 0

            totals['wp'] += wp
            totals['heizpatrone'] += heiz
            totals['wattpilot'] += wattpilot
            totals['klima'] += klima
            totals['gefrier'] += gefrier
            totals['lueftung'] += lueftung
            totals['haushalt'] += haushalt
            totals['gesamt'] += gesamt

            datapoints.append({
                'year': yr,
                'label': str(yr),
                'w_wp': round(wp, 2),
                'w_heizpatrone': round(heiz, 2),
                'w_wattpilot': round(wattpilot, 2),
                'w_klima': round(klima, 2),
                'w_gefrier': round(gefrier, 2),
                'w_lueftung': round(lueftung, 2),
                'w_haushalt': round(haushalt, 2),
                'w_gesamt': round(gesamt, 2),
            })

        average_summary = _build_average_summary(totals, month_count_total, 'Monat')

        return jsonify({
            'datapoints': datapoints,
            'totals': {k: round(v, 2) for k, v in totals.items()},
            'year_range': [yr_range[0] or 2022, yr_range[1] or datetime.now().year],
            'average_summary': average_summary,
        })

    except Exception as e:
        return api_error_response(e, "Verbraucher-Gesamt")
