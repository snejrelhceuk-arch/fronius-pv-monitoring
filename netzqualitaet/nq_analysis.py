#!/usr/bin/env python3
"""
nq_analysis.py — 15-Minuten-Handelstakt-Analyse der Netzqualitätsdaten.

Analysiert die deterministische Frequenzabweichung (DFD) an den
Viertelstunden-Grenzen des Stromhandels (EPEX SPOT 15-min-Blöcke).

Hintergrund:
  - EPEX SPOT handelt in 15-min-Blöcken (seit 2011)
  - An Blockgrenzen (xx:00, :15, :30, :45) wechseln Fahrpläne
  - Das erzeugt messbare Frequenzabweichungen (DFD)
  - Vollstunden-Grenzen sind stärker (Stunden- + Viertelstundenkontrakte)
  - 50Hertz (ÜNB Sachsen) kompensiert mit Regelleistung

Analyse-Bausteine:
  A) 15-min-Block-Statistiken (Mittel, Streuung, Min, Max)
  B) Grenzübergangs-Analyse (Frequenzgradient an Blockgrenzen)
  C) Lokale Rückwirkung (Korrelation Strom↔Spannung)
  D) Tages- und Wochenmuster

Datenquelle: netzqualitaet/db/nq_YYYY-MM.db (aus nq_export.py)

Cron-Empfehlung:
  20 1 * * *  cd /home/admin/Dokumente/PVAnlage/pv-system && .venv/bin/python netzqualitaet/nq_analysis.py >> /tmp/nq_analysis.log 2>&1

ABCD-Rollenmodell: Säule A (Analyse, read-only auf NQ-DB, write Ergebnistabellen).
"""
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger('nq_analysis')

NQ_DB_DIR = os.path.join(config.BASE_DIR, 'netzqualitaet', 'db')

# --- Analyse-Parameter ---
BLOCK_SECONDS = 900            # 15-Minuten-Block
BOUNDARY_WINDOW_S = 60        # Sekunden vor/nach Grenze für Gradientenanalyse
MID_BLOCK_START_S = 300       # Mid-Block Referenzzeitfenster: 5:00–10:00 im Block
MID_BLOCK_END_S = 600
MIN_SAMPLES_BLOCK = 150       # Mindestens 150 Samples (≈ 50% von 300 bei 3s-Polling)
MIN_SAMPLES_BOUNDARY = 10     # Mindestens 10 Samples im Grenzfenster
NOMINAL_FREQ = 50.0           # Hz

# Schema für Ergebnistabellen
ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS nq_15min_blocks (
    block_ts        INTEGER PRIMARY KEY,
    block_type      TEXT NOT NULL,
    f_avg           REAL,
    f_min           REAL,
    f_max           REAL,
    f_std           REAL,
    f_range         REAL,
    u_l1_l2_avg     REAL,
    u_l2_l3_avg     REAL,
    u_l3_l1_avg     REAL,
    u_spread        REAL,
    i_l1_avg        REAL,
    i_l2_avg        REAL,
    i_l3_avg        REAL,
    i_total_avg     REAL,
    n_samples       INTEGER
);

CREATE TABLE IF NOT EXISTS nq_boundary_events (
    boundary_ts         INTEGER PRIMARY KEY,
    boundary_type       TEXT NOT NULL,
    f_pre_avg           REAL,
    f_post_avg          REAL,
    f_mid_pre_avg       REAL,
    f_mid_post_avg      REAL,
    f_delta_pre         REAL,
    f_delta_post        REAL,
    f_nadir             REAL,
    f_nadir_offset_s    REAL,
    f_gradient_pre      REAL,
    f_gradient_post     REAL,
    dfd_amplitude       REAL,
    u_delta_pre         REAL,
    u_delta_post        REAL,
    i_delta_pre         REAL,
    i_delta_post        REAL,
    local_impact_score  REAL,
    n_samples_pre       INTEGER,
    n_samples_post      INTEGER
);

CREATE TABLE IF NOT EXISTS nq_daily_summary (
    date_str            TEXT PRIMARY KEY,
    n_blocks            INTEGER,
    n_boundaries        INTEGER,
    dfd_mean            REAL,
    dfd_std             REAL,
    dfd_max             REAL,
    dfd_hour_mean       REAL,
    dfd_quarter_mean    REAL,
    f_daily_avg         REAL,
    f_daily_std         REAL,
    f_daily_min         REAL,
    f_daily_max         REAL,
    u_avg               REAL,
    u_spread_avg        REAL,
    local_events        INTEGER,
    grid_events         INTEGER,
    analysis_ts         INTEGER
);

CREATE TABLE IF NOT EXISTS nq_analysis_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_ts     INTEGER NOT NULL,
    date_analyzed   TEXT NOT NULL,
    n_blocks        INTEGER,
    n_boundaries    INTEGER,
    duration_s      REAL
);
"""


def get_nq_db_path(date_obj):
    """Pfad zur Monats-DB für ein gegebenes Datum."""
    if isinstance(date_obj, str):
        date_obj = datetime.strptime(date_obj, '%Y-%m-%d')
    filename = f"nq_{date_obj.strftime('%Y-%m')}.db"
    return os.path.join(NQ_DB_DIR, filename)


def open_nq_db(date_obj):
    """NQ-Monats-DB öffnen. Gibt None zurück wenn nicht vorhanden."""
    db_path = get_nq_db_path(date_obj)
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.executescript(ANALYSIS_SCHEMA)
    return conn


def classify_boundary(ts):
    """Klassifiziert eine Blockgrenze nach Handelsrelevanz.

    Returns:
        'full_hour':    xx:00 — Stärkster DFD (Stunden- + Viertelstundenkontrakt)
        'half_hour':    xx:30 — Mittlerer DFD
        'quarter_hour': xx:15, xx:45 — Schwächster DFD
    """
    dt = datetime.fromtimestamp(ts)
    minute = dt.minute
    if minute == 0:
        return 'full_hour'
    elif minute == 30:
        return 'half_hour'
    else:
        return 'quarter_hour'


def linear_gradient(times, values):
    """Berechnet den linearen Gradienten (Steigung) via Least-Squares.

    Args:
        times: Array von Zeitpunkten (Sekunden)
        values: Array von Messwerten

    Returns:
        Steigung (Einheit/Sekunde), oder None wenn zu wenige Punkte
    """
    if len(times) < 3:
        return None
    t = np.array(times, dtype=np.float64)
    v = np.array(values, dtype=np.float64)
    t -= t[0]  # Normalisiere auf 0
    mask = np.isfinite(v)
    if mask.sum() < 3:
        return None
    coeffs = np.polyfit(t[mask], v[mask], 1)
    return float(coeffs[0])


def load_day_samples(conn, date_str):
    """Lädt alle NQ-Samples für einen Tag.

    Returns:
        numpy structured array mit ts, f_netz, u_l1_l2, ..., i_l3
    """
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    ts_start = int(dt.timestamp())
    ts_end = int((dt + timedelta(days=1)).timestamp())

    cursor = conn.execute(
        "SELECT ts, f_netz, u_l1_l2, u_l2_l3, u_l3_l1, i_l1, i_l2, i_l3 "
        "FROM nq_samples WHERE ts >= ? AND ts < ? ORDER BY ts",
        (ts_start, ts_end)
    )
    rows = cursor.fetchall()
    if not rows:
        return None

    dtype = np.dtype([
        ('ts', np.int64), ('f_netz', np.float64),
        ('u_l1_l2', np.float64), ('u_l2_l3', np.float64), ('u_l3_l1', np.float64),
        ('i_l1', np.float64), ('i_l2', np.float64), ('i_l3', np.float64),
    ])
    data = np.array(rows, dtype=dtype)
    return data


def analyze_15min_block(samples, block_ts):
    """Analysiert einen einzelnen 15-Minuten-Block.

    Args:
        samples: numpy array der Samples im Block
        block_ts: Unix-Timestamp des Blockstarts (auf 900s gerundet)

    Returns:
        dict mit Block-Statistiken
    """
    if len(samples) < MIN_SAMPLES_BLOCK:
        return None

    f = samples['f_netz']
    f_valid = f[np.isfinite(f)]
    if len(f_valid) < MIN_SAMPLES_BLOCK:
        return None

    # Spannungen und Ströme
    u_avgs = []
    for col in ('u_l1_l2', 'u_l2_l3', 'u_l3_l1'):
        vals = samples[col]
        valid = vals[np.isfinite(vals)]
        u_avgs.append(float(np.mean(valid)) if len(valid) > 0 else None)

    i_avgs = []
    for col in ('i_l1', 'i_l2', 'i_l3'):
        vals = samples[col]
        valid = vals[np.isfinite(vals)]
        i_avgs.append(float(np.mean(valid)) if len(valid) > 0 else None)

    # Unsymmetrie: Spread zwischen L-L-Spannungen
    u_valid = [u for u in u_avgs if u is not None]
    u_spread = (max(u_valid) - min(u_valid)) if len(u_valid) >= 2 else None

    # Gesamtstrom (Betrag, alle Phasen)
    i_total = None
    if all(i is not None for i in i_avgs):
        i_total = sum(abs(i) for i in i_avgs) / 3.0

    return {
        'block_ts': block_ts,
        'block_type': classify_boundary(block_ts),
        'f_avg': float(np.mean(f_valid)),
        'f_min': float(np.min(f_valid)),
        'f_max': float(np.max(f_valid)),
        'f_std': float(np.std(f_valid)),
        'f_range': float(np.max(f_valid) - np.min(f_valid)),
        'u_l1_l2_avg': u_avgs[0],
        'u_l2_l3_avg': u_avgs[1],
        'u_l3_l1_avg': u_avgs[2],
        'u_spread': u_spread,
        'i_l1_avg': i_avgs[0],
        'i_l2_avg': i_avgs[1],
        'i_l3_avg': i_avgs[2],
        'i_total_avg': i_total,
        'n_samples': len(samples),
    }


def analyze_boundary(samples_all, boundary_ts):
    """Analysiert den Frequenzübergang an einer 15-Minuten-Grenze.

    Untersucht das DFD-Muster: Frequenzabfall vor der Grenze, Recovery danach.
    Vergleicht Grenzverhalten mit der Blockmitte als Referenz.

    Args:
        samples_all: Alle Tages-Samples (numpy array)
        boundary_ts: Unix-Timestamp der Blockgrenze

    Returns:
        dict mit Grenzübergangs-Metriken, oder None
    """
    bw = BOUNDARY_WINDOW_S

    # Zeitfenster
    pre_mask = (samples_all['ts'] >= boundary_ts - bw) & (samples_all['ts'] < boundary_ts)
    post_mask = (samples_all['ts'] >= boundary_ts) & (samples_all['ts'] < boundary_ts + bw)

    # Referenz: Blockmitte des vorherigen und nachfolgenden Blocks
    mid_pre_mask = (
        (samples_all['ts'] >= boundary_ts - BLOCK_SECONDS + MID_BLOCK_START_S) &
        (samples_all['ts'] < boundary_ts - BLOCK_SECONDS + MID_BLOCK_END_S)
    )
    mid_post_mask = (
        (samples_all['ts'] >= boundary_ts + MID_BLOCK_START_S) &
        (samples_all['ts'] < boundary_ts + MID_BLOCK_END_S)
    )

    pre_samples = samples_all[pre_mask]
    post_samples = samples_all[post_mask]
    mid_pre = samples_all[mid_pre_mask]
    mid_post = samples_all[mid_post_mask]

    if len(pre_samples) < MIN_SAMPLES_BOUNDARY or len(post_samples) < MIN_SAMPLES_BOUNDARY:
        return None

    # Frequenz-Analyse
    f_pre = pre_samples['f_netz']
    f_post = post_samples['f_netz']
    f_pre_valid = f_pre[np.isfinite(f_pre)]
    f_post_valid = f_post[np.isfinite(f_post)]

    if len(f_pre_valid) < MIN_SAMPLES_BOUNDARY or len(f_post_valid) < MIN_SAMPLES_BOUNDARY:
        return None

    f_pre_avg = float(np.mean(f_pre_valid))
    f_post_avg = float(np.mean(f_post_valid))

    # Referenzwerte aus Blockmitte
    f_mid_pre_avg = None
    f_mid_post_avg = None
    if len(mid_pre) >= MIN_SAMPLES_BOUNDARY:
        v = mid_pre['f_netz']
        valid = v[np.isfinite(v)]
        if len(valid) >= MIN_SAMPLES_BOUNDARY:
            f_mid_pre_avg = float(np.mean(valid))
    if len(mid_post) >= MIN_SAMPLES_BOUNDARY:
        v = mid_post['f_netz']
        valid = v[np.isfinite(v)]
        if len(valid) >= MIN_SAMPLES_BOUNDARY:
            f_mid_post_avg = float(np.mean(valid))

    # DFD: Abweichung der Grenzfrequenz von der Referenz
    f_delta_pre = (f_pre_avg - f_mid_pre_avg) if f_mid_pre_avg is not None else None
    f_delta_post = (f_post_avg - f_mid_post_avg) if f_mid_post_avg is not None else None

    # Nadir: Frequenzminimum im Grenzbereich (±30s)
    nadir_mask = (
        (samples_all['ts'] >= boundary_ts - 30) &
        (samples_all['ts'] <= boundary_ts + 30)
    )
    nadir_samples = samples_all[nadir_mask]
    f_nadir = None
    f_nadir_offset_s = None
    if len(nadir_samples) > 0:
        f_nadir_vals = nadir_samples['f_netz']
        valid_mask = np.isfinite(f_nadir_vals)
        if valid_mask.any():
            idx = np.argmin(f_nadir_vals[valid_mask])
            f_nadir = float(f_nadir_vals[valid_mask][idx])
            f_nadir_offset_s = float(nadir_samples['ts'][valid_mask][idx] - boundary_ts)

    # Gradienten (Frequenzänderungsrate)
    f_gradient_pre = linear_gradient(
        pre_samples['ts'].astype(float), f_pre.astype(float)
    )
    f_gradient_post = linear_gradient(
        post_samples['ts'].astype(float), f_post.astype(float)
    )

    # DFD-Amplitude: Differenz zwischen Nadir und Nominale (oder Referenz)
    dfd_ref = f_mid_pre_avg if f_mid_pre_avg is not None else NOMINAL_FREQ
    dfd_amplitude = (dfd_ref - f_nadir) if f_nadir is not None else None

    # --- Lokale Rückwirkung ---
    # Vergleiche Strom und Spannung: Pre vs. Post
    def _avg_valid(arr):
        valid = arr[np.isfinite(arr)]
        return float(np.mean(valid)) if len(valid) > 0 else None

    # Spannungsdelta (Mittel aller L-L)
    u_pre_vals = [_avg_valid(pre_samples[c]) for c in ('u_l1_l2', 'u_l2_l3', 'u_l3_l1')]
    u_post_vals = [_avg_valid(post_samples[c]) for c in ('u_l1_l2', 'u_l2_l3', 'u_l3_l1')]
    u_pre_mean = np.mean([v for v in u_pre_vals if v is not None]) if any(v is not None for v in u_pre_vals) else None
    u_post_mean = np.mean([v for v in u_post_vals if v is not None]) if any(v is not None for v in u_post_vals) else None
    u_delta_pre = float(u_pre_mean - u_post_mean) if (u_pre_mean is not None and u_post_mean is not None) else None

    # Stromdelta (Summe Beträge aller Phasen)
    i_pre_vals = [_avg_valid(pre_samples[c]) for c in ('i_l1', 'i_l2', 'i_l3')]
    i_post_vals = [_avg_valid(post_samples[c]) for c in ('i_l1', 'i_l2', 'i_l3')]
    i_pre_total = np.mean([abs(v) for v in i_pre_vals if v is not None]) if any(v is not None for v in i_pre_vals) else None
    i_post_total = np.mean([abs(v) for v in i_post_vals if v is not None]) if any(v is not None for v in i_post_vals) else None
    i_delta_pre = float(i_post_total - i_pre_total) if (i_pre_total is not None and i_post_total is not None) else None

    # Local Impact Score:
    #   Spannung ändert sich UND Strom ändert sich gleichzeitig → wahrscheinlich lokal
    #   Spannung ändert sich OHNE Stromänderung → wahrscheinlich netzseitig
    #   Score: 0.0 = rein netzseitig, 1.0 = rein lokal
    local_impact = None
    if u_delta_pre is not None and i_delta_pre is not None:
        u_change = abs(u_delta_pre)
        i_change = abs(i_delta_pre)
        # Normalisierung: Stromänderung > 0.5A bei gleichzeitiger Spannungsänderung → lokal
        if u_change > 0.3:  # Mindest-Spannungsänderung 0.3V
            i_sensitivity = min(i_change / 2.0, 1.0)  # 2A Referenz für "volle Lokalität"
            local_impact = round(i_sensitivity, 3)
        else:
            local_impact = 0.0  # Keine nennenswerte Spannungsänderung

    return {
        'boundary_ts': boundary_ts,
        'boundary_type': classify_boundary(boundary_ts),
        'f_pre_avg': round(f_pre_avg, 4),
        'f_post_avg': round(f_post_avg, 4),
        'f_mid_pre_avg': round(f_mid_pre_avg, 4) if f_mid_pre_avg is not None else None,
        'f_mid_post_avg': round(f_mid_post_avg, 4) if f_mid_post_avg is not None else None,
        'f_delta_pre': round(f_delta_pre, 4) if f_delta_pre is not None else None,
        'f_delta_post': round(f_delta_post, 4) if f_delta_post is not None else None,
        'f_nadir': round(f_nadir, 4) if f_nadir is not None else None,
        'f_nadir_offset_s': round(f_nadir_offset_s, 1) if f_nadir_offset_s is not None else None,
        'f_gradient_pre': round(f_gradient_pre, 6) if f_gradient_pre is not None else None,
        'f_gradient_post': round(f_gradient_post, 6) if f_gradient_post is not None else None,
        'dfd_amplitude': round(dfd_amplitude, 4) if dfd_amplitude is not None else None,
        'u_delta_pre': round(u_delta_pre, 2) if u_delta_pre is not None else None,
        'u_delta_post': round(float(u_post_mean - u_pre_mean), 2) if (u_pre_mean is not None and u_post_mean is not None) else None,
        'i_delta_pre': round(i_delta_pre, 3) if i_delta_pre is not None else None,
        'i_delta_post': round(float(i_post_total - i_pre_total), 3) if (i_pre_total is not None and i_post_total is not None) else None,
        'local_impact_score': local_impact,
        'n_samples_pre': len(pre_samples),
        'n_samples_post': len(post_samples),
    }


def analyze_day(conn, date_str):
    """Vollständige Tagesanalyse: 15-min-Blöcke + Grenzübergänge + Tageszusammenfassung.

    Args:
        conn: SQLite-Verbindung zur NQ-Monats-DB
        date_str: Datum als 'YYYY-MM-DD'

    Returns:
        dict mit 'blocks', 'boundaries', 'summary'
    """
    samples = load_day_samples(conn, date_str)
    if samples is None or len(samples) == 0:
        logger.warning(f"Keine Daten für {date_str}")
        return None

    logger.info(f"Analysiere {date_str}: {len(samples)} Samples")

    dt = datetime.strptime(date_str, '%Y-%m-%d')
    day_start_ts = int(dt.timestamp())

    # --- A: 15-Minuten-Block-Statistiken ---
    blocks = []
    for i in range(96):  # 96 Blöcke pro Tag
        block_ts = day_start_ts + i * BLOCK_SECONDS
        block_end = block_ts + BLOCK_SECONDS
        mask = (samples['ts'] >= block_ts) & (samples['ts'] < block_end)
        block_samples = samples[mask]
        result = analyze_15min_block(block_samples, block_ts)
        if result:
            blocks.append(result)

    # --- B: Grenzübergangs-Analyse ---
    boundaries = []
    for i in range(1, 96):  # 95 Grenzen (nicht die erste um 00:00 — kein vorheriger Block)
        boundary_ts = day_start_ts + i * BLOCK_SECONDS
        result = analyze_boundary(samples, boundary_ts)
        if result:
            boundaries.append(result)

    # --- C: Tageszusammenfassung ---
    summary = _compute_daily_summary(date_str, samples, blocks, boundaries)

    # --- Ergebnisse speichern ---
    _store_results(conn, blocks, boundaries, summary, date_str)

    logger.info(
        f"  {date_str}: {len(blocks)} Blöcke, {len(boundaries)} Grenzen, "
        f"DFD-Mittel={summary.get('dfd_mean', '?')} mHz"
    )

    return {
        'blocks': blocks,
        'boundaries': boundaries,
        'summary': summary,
    }


def _compute_daily_summary(date_str, samples, blocks, boundaries):
    """Berechnet die Tageszusammenfassung."""
    f_all = samples['f_netz']
    f_valid = f_all[np.isfinite(f_all)]

    # DFD-Statistiken
    dfd_values = [b['dfd_amplitude'] for b in boundaries if b.get('dfd_amplitude') is not None]
    dfd_hour = [b['dfd_amplitude'] for b in boundaries
                if b.get('dfd_amplitude') is not None and b['boundary_type'] == 'full_hour']
    dfd_quarter = [b['dfd_amplitude'] for b in boundaries
                   if b.get('dfd_amplitude') is not None and b['boundary_type'] == 'quarter_hour']

    # Spannungsmittel über alle Blöcke
    u_avgs = [b['u_l1_l2_avg'] for b in blocks if b.get('u_l1_l2_avg') is not None]
    u_spreads = [b['u_spread'] for b in blocks if b.get('u_spread') is not None]

    # Lokale vs. netzseitige Ereignisse
    local_events = sum(1 for b in boundaries
                       if b.get('local_impact_score') is not None and b['local_impact_score'] > 0.3)
    grid_events = sum(1 for b in boundaries
                      if b.get('local_impact_score') is not None and b['local_impact_score'] <= 0.3
                      and b.get('dfd_amplitude') is not None and abs(b['dfd_amplitude']) > 0.010)

    return {
        'date_str': date_str,
        'n_blocks': len(blocks),
        'n_boundaries': len(boundaries),
        'dfd_mean': round(float(np.mean(dfd_values)) * 1000, 1) if dfd_values else None,  # mHz
        'dfd_std': round(float(np.std(dfd_values)) * 1000, 1) if dfd_values else None,
        'dfd_max': round(float(np.max(np.abs(dfd_values))) * 1000, 1) if dfd_values else None,
        'dfd_hour_mean': round(float(np.mean(dfd_hour)) * 1000, 1) if dfd_hour else None,
        'dfd_quarter_mean': round(float(np.mean(dfd_quarter)) * 1000, 1) if dfd_quarter else None,
        'f_daily_avg': round(float(np.mean(f_valid)), 4) if len(f_valid) > 0 else None,
        'f_daily_std': round(float(np.std(f_valid)), 4) if len(f_valid) > 0 else None,
        'f_daily_min': round(float(np.min(f_valid)), 4) if len(f_valid) > 0 else None,
        'f_daily_max': round(float(np.max(f_valid)), 4) if len(f_valid) > 0 else None,
        'u_avg': round(float(np.mean(u_avgs)), 1) if u_avgs else None,
        'u_spread_avg': round(float(np.mean(u_spreads)), 2) if u_spreads else None,
        'local_events': local_events,
        'grid_events': grid_events,
        'analysis_ts': int(time.time()),
    }


def _store_results(conn, blocks, boundaries, summary, date_str):
    """Speichert Analyseergebnisse in die NQ-DB."""
    # Alte Ergebnisse für diesen Tag löschen (idempotent)
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    day_start = int(dt.timestamp())
    day_end = int((dt + timedelta(days=1)).timestamp())

    conn.execute("DELETE FROM nq_15min_blocks WHERE block_ts >= ? AND block_ts < ?",
                 (day_start, day_end))
    conn.execute("DELETE FROM nq_boundary_events WHERE boundary_ts >= ? AND boundary_ts < ?",
                 (day_start, day_end))
    conn.execute("DELETE FROM nq_daily_summary WHERE date_str = ?", (date_str,))

    # Blöcke
    for b in blocks:
        conn.execute(
            """INSERT INTO nq_15min_blocks
               (block_ts, block_type, f_avg, f_min, f_max, f_std, f_range,
                u_l1_l2_avg, u_l2_l3_avg, u_l3_l1_avg, u_spread,
                i_l1_avg, i_l2_avg, i_l3_avg, i_total_avg, n_samples)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (b['block_ts'], b['block_type'], b['f_avg'], b['f_min'], b['f_max'],
             b['f_std'], b['f_range'], b['u_l1_l2_avg'], b['u_l2_l3_avg'],
             b['u_l3_l1_avg'], b['u_spread'], b['i_l1_avg'], b['i_l2_avg'],
             b['i_l3_avg'], b['i_total_avg'], b['n_samples'])
        )

    # Grenzübergänge
    for be in boundaries:
        conn.execute(
            """INSERT INTO nq_boundary_events
               (boundary_ts, boundary_type, f_pre_avg, f_post_avg,
                f_mid_pre_avg, f_mid_post_avg, f_delta_pre, f_delta_post,
                f_nadir, f_nadir_offset_s, f_gradient_pre, f_gradient_post,
                dfd_amplitude, u_delta_pre, u_delta_post, i_delta_pre, i_delta_post,
                local_impact_score, n_samples_pre, n_samples_post)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (be['boundary_ts'], be['boundary_type'], be['f_pre_avg'], be['f_post_avg'],
             be['f_mid_pre_avg'], be['f_mid_post_avg'], be['f_delta_pre'], be['f_delta_post'],
             be['f_nadir'], be['f_nadir_offset_s'], be['f_gradient_pre'], be['f_gradient_post'],
             be['dfd_amplitude'], be['u_delta_pre'], be['u_delta_post'],
             be['i_delta_pre'], be['i_delta_post'],
             be['local_impact_score'], be['n_samples_pre'], be['n_samples_post'])
        )

    # Tageszusammenfassung
    s = summary
    conn.execute(
        """INSERT INTO nq_daily_summary
           (date_str, n_blocks, n_boundaries, dfd_mean, dfd_std, dfd_max,
            dfd_hour_mean, dfd_quarter_mean, f_daily_avg, f_daily_std,
            f_daily_min, f_daily_max, u_avg, u_spread_avg,
            local_events, grid_events, analysis_ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (s['date_str'], s['n_blocks'], s['n_boundaries'], s['dfd_mean'], s['dfd_std'],
         s['dfd_max'], s['dfd_hour_mean'], s['dfd_quarter_mean'],
         s['f_daily_avg'], s['f_daily_std'], s['f_daily_min'], s['f_daily_max'],
         s['u_avg'], s['u_spread_avg'], s['local_events'], s['grid_events'],
         s['analysis_ts'])
    )

    conn.commit()


def run_analysis(date_str=None, days_back=1):
    """Analysiert einen Tag oder die letzten N Tage.

    Args:
        date_str: Einzelnes Datum (YYYY-MM-DD), oder None für automatisch
        days_back: Anzahl Tage zurück (wenn date_str=None)
    """
    dates = []
    if date_str:
        dates = [date_str]
    else:
        today = datetime.now().date()
        for i in range(days_back):
            d = today - timedelta(days=i)
            dates.append(d.strftime('%Y-%m-%d'))

    for ds in dates:
        t0 = time.time()
        conn = open_nq_db(datetime.strptime(ds, '%Y-%m-%d'))
        if conn is None:
            logger.warning(f"Keine NQ-DB für {ds}")
            continue

        try:
            result = analyze_day(conn, ds)
            duration = time.time() - t0

            if result:
                conn.execute(
                    "INSERT INTO nq_analysis_log (analysis_ts, date_analyzed, n_blocks, n_boundaries, duration_s) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (int(time.time()), ds,
                     result['summary']['n_blocks'],
                     result['summary']['n_boundaries'],
                     round(duration, 2))
                )
                conn.commit()

                # Zusammenfassung auf stdout
                s = result['summary']
                print(f"\n{'='*60}")
                print(f"  Netzqualitäts-Analyse: {ds}")
                print(f"{'='*60}")
                print(f"  Blöcke analysiert:    {s['n_blocks']}/96")
                print(f"  Grenzübergänge:       {s['n_boundaries']}")
                print(f"  Frequenz (Tag):       {s['f_daily_avg']} Hz ± {s['f_daily_std']} Hz")
                print(f"  Frequenzbereich:      {s['f_daily_min']} – {s['f_daily_max']} Hz")
                if s['dfd_mean'] is not None:
                    print(f"  DFD Mittel:           {s['dfd_mean']} mHz")
                    print(f"  DFD Maximum:          {s['dfd_max']} mHz")
                    if s['dfd_hour_mean'] is not None:
                        print(f"  DFD Vollstunde:       {s['dfd_hour_mean']} mHz")
                    if s['dfd_quarter_mean'] is not None:
                        print(f"  DFD Viertelstunde:    {s['dfd_quarter_mean']} mHz")
                print(f"  Spannung (Mittel):    {s['u_avg']} V")
                print(f"  Unsymmetrie (Mittel): {s['u_spread_avg']} V")
                print(f"  Lokale Ereignisse:    {s['local_events']}")
                print(f"  Netzseitige Events:   {s['grid_events']}")
                print(f"  Dauer:                {duration:.1f}s")
                print()
        finally:
            conn.close()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Argumente: --date YYYY-MM-DD oder --days N
    date_str = None
    days_back = 1

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--date' and i + 1 < len(args):
            date_str = args[i + 1]
            i += 2
        elif args[i] == '--days' and i + 1 < len(args):
            days_back = int(args[i + 1])
            i += 2
        else:
            print(f"Nutzung: {sys.argv[0]} [--date YYYY-MM-DD | --days N]")
            sys.exit(1)

    run_analysis(date_str=date_str, days_back=days_back)


if __name__ == '__main__':
    main()
