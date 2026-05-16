"""
collector.wp_power_protocol — Netzbetreiber-Nachweis WP-Leistung.

Dauerhaft persistente Minutwerte (max. Wattpilot- bzw. WP-Phasenleistung)
in CSV. Rechtlich relevant: zeigt Einhaltung des Leistungslimits gegenueber
dem Netzbetreiber. Backfill aus data_1min fuellt Luecken nach Restarts.
"""

import logging
import os
import sqlite3
import threading
import time

import config

WP_POWER_LIMIT_W = float(getattr(config, 'WP_LEISTUNG_LIMIT_W', 4200))
WP_POWER_PROTOCOL_FILE = getattr(
    config,
    'WP_POWER_PROTOCOL_FILE',
    os.path.join(config.BASE_DIR, 'logs', 'wp_netzbetreiber_leistung.csv'),
)
WP_POWER_PROTOCOL_INTERVAL_S = int(getattr(config, 'WP_POWER_PROTOCOL_INTERVAL_S', 60))

DB_FILE = config.DB_PATH

wp_protocol_lock = threading.Lock()
wp_protocol_state = {
    'bucket_ts': None,
    'max_power_w': 0.0,
    'samples': 0,
    'violation': False,
}


def _ensure_wp_protocol_header():
    protocol_dir = os.path.dirname(WP_POWER_PROTOCOL_FILE)
    if protocol_dir:
        os.makedirs(protocol_dir, exist_ok=True)
    if not os.path.exists(WP_POWER_PROTOCOL_FILE):
        with open(WP_POWER_PROTOCOL_FILE, 'a') as f:
            f.write('ts_epoch,ts_local,wp_max_w,limit_w,within_limit,samples\n')


def _write_wp_protocol_bucket(bucket_ts, max_power_w, samples, violation):
    _ensure_wp_protocol_header()
    ts_local = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(bucket_ts))
    within_limit = 0 if violation else 1
    line = f"{int(bucket_ts)},{ts_local},{max_power_w:.1f},{WP_POWER_LIMIT_W:.1f},{within_limit},{int(samples)}\n"
    with open(WP_POWER_PROTOCOL_FILE, 'a') as f:
        f.write(line)


def _read_wp_protocol_last_ts():
    if not os.path.exists(WP_POWER_PROTOCOL_FILE):
        return None
    try:
        with open(WP_POWER_PROTOCOL_FILE, 'r') as f:
            lines = f.readlines()
        for raw in reversed(lines):
            line = raw.strip()
            if not line or line.startswith('ts_epoch'):
                continue
            first = line.split(',', 1)[0].strip()
            if first.isdigit():
                return int(first)
    except Exception as e:
        logging.warning(f"WP-Protokoll lesen fehlgeschlagen: {e}")
    return None


def backfill_wp_protocol_from_db():
    """Fuelle fehlende WP-Protokollzeilen aus data_1min auf."""
    conn = None
    try:
        _ensure_wp_protocol_header()
        last_ts = _read_wp_protocol_last_ts()
        start_ts = (last_ts + WP_POWER_PROTOCOL_INTERVAL_S) if last_ts is not None else 0

        db_candidates = [DB_FILE, getattr(config, 'DB_PERSIST_PATH', DB_FILE)]
        selected_db = None
        for candidate in db_candidates:
            if not candidate or not os.path.exists(candidate):
                continue
            try:
                probe = sqlite3.connect(candidate, timeout=2.0)
                cur = probe.cursor()
                cur.execute("SELECT COUNT(*) FROM data_1min")
                count = cur.fetchone()[0]
                probe.close()
                if count > 0:
                    selected_db = candidate
                    break
            except Exception:
                continue

        if not selected_db:
            logging.info("WP-Protokoll Backfill: keine geeignete DB mit data_1min gefunden")
            return

        conn = sqlite3.connect(selected_db, timeout=5.0)
        c = conn.cursor()
        c.execute(
            """
            SELECT CAST(ts / ? AS INTEGER) * ? AS bucket_ts,
                   MAX(ABS(P_WP_max)) AS wp_max_w
            FROM data_1min
            WHERE ts >= ?
              AND P_WP_max IS NOT NULL
            GROUP BY bucket_ts
            ORDER BY bucket_ts
            """,
            (WP_POWER_PROTOCOL_INTERVAL_S, WP_POWER_PROTOCOL_INTERVAL_S, start_ts),
        )
        rows = c.fetchall()
        if not rows:
            return

        with open(WP_POWER_PROTOCOL_FILE, 'a') as f:
            for bucket_ts, wp_max_w in rows:
                max_w = abs(float(wp_max_w or 0.0))
                within_limit = 0 if max_w > WP_POWER_LIMIT_W else 1
                ts_local = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(bucket_ts))
                f.write(
                    f"{int(bucket_ts)},{ts_local},{max_w:.1f},{WP_POWER_LIMIT_W:.1f},{within_limit},1\n"
                )

        logging.info(
            "WP-Protokoll Backfill: %d Zeilen aus data_1min ergaenzt (%s)",
            len(rows),
            selected_db,
        )
    except Exception as e:
        logging.warning(f"WP-Protokoll Backfill fehlgeschlagen: {e}")
    finally:
        if conn:
            conn.close()


def track_wp_power_protocol(sample_ts, p_wp):
    """Sammelt WP-Leistung und schreibt minutliche Maximalwerte dauerhaft weg."""
    try:
        abs_power_w = abs(float(p_wp or 0.0))
        bucket_size = max(1, WP_POWER_PROTOCOL_INTERVAL_S)
        bucket_ts = int(sample_ts // bucket_size) * bucket_size

        with wp_protocol_lock:
            prev_bucket = wp_protocol_state['bucket_ts']

            if prev_bucket is None:
                wp_protocol_state['bucket_ts'] = bucket_ts
            elif bucket_ts != prev_bucket:
                _write_wp_protocol_bucket(
                    prev_bucket,
                    wp_protocol_state['max_power_w'],
                    wp_protocol_state['samples'],
                    wp_protocol_state['violation'],
                )
                wp_protocol_state['bucket_ts'] = bucket_ts
                wp_protocol_state['max_power_w'] = 0.0
                wp_protocol_state['samples'] = 0
                wp_protocol_state['violation'] = False

            wp_protocol_state['samples'] += 1
            if abs_power_w > wp_protocol_state['max_power_w']:
                wp_protocol_state['max_power_w'] = abs_power_w

            if abs_power_w > WP_POWER_LIMIT_W and not wp_protocol_state['violation']:
                wp_protocol_state['violation'] = True
                logging.warning(
                    "WP Leistungsgrenze ueberschritten: %.1f W > %.1f W",
                    abs_power_w,
                    WP_POWER_LIMIT_W,
                )
    except Exception as e:
        logging.error(f"WP-Protokollierung Fehler: {e}")


def flush_wp_power_protocol():
    """Schreibt den aktuellen WP-Protokoll-Bucket, z.B. beim Shutdown."""
    try:
        with wp_protocol_lock:
            bucket_ts = wp_protocol_state['bucket_ts']
            samples = wp_protocol_state['samples']
            if bucket_ts is None or samples <= 0:
                return

            _write_wp_protocol_bucket(
                bucket_ts,
                wp_protocol_state['max_power_w'],
                samples,
                wp_protocol_state['violation'],
            )
            wp_protocol_state['bucket_ts'] = None
            wp_protocol_state['max_power_w'] = 0.0
            wp_protocol_state['samples'] = 0
            wp_protocol_state['violation'] = False
    except Exception as e:
        logging.error(f"WP-Protokoll-Flush Fehler: {e}")
