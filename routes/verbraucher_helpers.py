"""
routes/verbraucher_helpers.py — Read-Helfer fuer das verbraucher-Blueprint.

Extrahiert aus routes/verbraucher.py (Architektur-Refactor 2026-09-28):
WP-Leistungsprotokoll/-Downsampling, SOC-Zeitreihen + Akku-Stress-Analyse,
Batterie-Wirkungsgrad/Vollzyklen und Fritz!DECT-/Heizpatrone-Tagesenergie.
Reine read-only DB-/CSV-Helfer (Saeule B). Re-Export ueber routes/verbraucher.py,
damit bestehende Importpfade (Tests, Routen) stabil bleiben.
"""
import csv
import math
import os
from datetime import datetime, timezone

import config
from routes.helpers import get_db_connection


def _read_wp_protocol_points(start_ts, end_ts):
    """Liest WP-Leistungsprotokoll als (ts, power_w, within_limit, grid_draw_w)."""
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
                grid_raw = row.get('grid_draw_w')
                grid_draw = None
                if grid_raw not in (None, ''):
                    try:
                        grid_draw = max(0.0, float(grid_raw))
                    except (TypeError, ValueError):
                        grid_draw = None
                points.append((ts, abs(power_w), 1 if within_limit != 0 else 0, grid_draw))
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
            SELECT ts, ABS(COALESCE(P_WP_max, 0)), P_Netz_avg
            FROM {table}
            WHERE ts >= ? AND ts <= ?
            ORDER BY ts
            """,
            (start_ts, end_ts),
        )
        for ts, power_w, p_netz in cursor.fetchall():
            p = abs(float(power_w or 0.0))
            grid_draw = None if p_netz is None else max(0.0, float(p_netz))
            points.append((int(ts), p, 1 if p <= limit_w else 0, grid_draw))
    finally:
        conn.close()

    return points, f'db:fallback({table})'


def _downsample_wp_points(points, start_ts, end_ts, max_points):
    """Verdichtet Zeitreihe per Bucket-Maximum, behält Peaks (+ Netzbezug am Peak)."""
    if len(points) <= max_points:
        return points, 0

    span = max(1, end_ts - start_ts)
    bucket_s = max(60, int(math.ceil(span / max_points)))

    sampled = []
    bucket_ts = None
    bucket_max = 0.0
    bucket_within = 1
    bucket_grid = None

    for ts, power_w, within_limit, grid_draw in points:
        current_bucket = (ts // bucket_s) * bucket_s
        if bucket_ts is None:
            bucket_ts = current_bucket

        if current_bucket != bucket_ts:
            sampled.append((bucket_ts, bucket_max, bucket_within, bucket_grid))
            bucket_ts = current_bucket
            bucket_max = 0.0
            bucket_within = 1
            bucket_grid = None

        if power_w > bucket_max:
            bucket_max = power_w
            bucket_grid = grid_draw
        if within_limit == 0:
            bucket_within = 0

    if bucket_ts is not None:
        sampled.append((bucket_ts, bucket_max, bucket_within, bucket_grid))

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
            'violation_grid_max_w': None,
            'violation_grid_avg_w': None,
        }

    max_point = max(points, key=lambda p: p[1])
    violations = sum(1 for _, _, within, _ in points if within == 0)

    violation_grids = [g for _, _, within, g in points if within == 0 and g is not None]
    violation_grid_max = round(max(violation_grids), 1) if violation_grids else None
    violation_grid_avg = (
        round(sum(violation_grids) / len(violation_grids), 1) if violation_grids else None
    )

    day_map = {}
    month_map = {}
    for ts, power_w, _, _ in points:
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
        'violation_grid_max_w': violation_grid_max,
        'violation_grid_avg_w': violation_grid_avg,
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


def _period_full_cycles(cursor, period, start_ts, end_ts, year=None, month=None):
    """Intervallbezogene Vollzyklen = Σ (Ladung / Nominal-Kapazität der Ausbaustufe).

    Monat/Jahr/Gesamt aus monthly_statistics (batt_ladung_kwh, eichgenaue
    Counter-Basis — konsistent zur PV-Übersicht). Tag aus daily_data
    (W_Batt_Charge_total, nur dort tagesgenau). Kapazitäts-Ausbaustufen
    (10.24 → 20.48 → 25.6 kWh) via config.battery_capacity_kwh_for.
    """
    total = 0.0
    have = False
    try:
        if period == 'tag':
            rows = cursor.execute(
                "SELECT ts, W_Batt_Charge_total FROM daily_data WHERE ts >= ? AND ts < ?",
                (start_ts, end_ts),
            ).fetchall()
            for ts, charge_wh in rows:
                if not charge_wh:
                    continue
                d = datetime.fromtimestamp(ts)
                cap = config.battery_capacity_kwh_for(d.year, d.month)
                if cap > 0:
                    total += (charge_wh / 1000.0) / cap
                    have = True
        else:
            if period == 'monat':
                q = "SELECT year, month, batt_ladung_kwh FROM monthly_statistics WHERE year = ? AND month = ?"
                params = (year, month)
            elif period == 'jahr':
                q = "SELECT year, month, batt_ladung_kwh FROM monthly_statistics WHERE year = ?"
                params = (year,)
            else:  # gesamt
                q = "SELECT year, month, batt_ladung_kwh FROM monthly_statistics"
                params = ()
            for y, m, charge_kwh in cursor.execute(q, params):
                cap = config.battery_capacity_kwh_for(y, m)
                if cap > 0 and charge_kwh:
                    total += charge_kwh / cap
                    have = True
    except Exception:
        return None
    return round(total, 2) if have else None


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
