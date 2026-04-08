#!/usr/bin/env python3
"""
nq_trade_switch_detect.py — Datengetriebene Erkennung handelsgetriebener Schaltzeiten.

Ziel:
  Schaltzeiten (15-min-Handelstakt) direkt aus Rohdaten nachweisen,
  ohne feste Annahme auf :00/:15/:30/:45.

Methode:
    1) Kandidaten-Perioden in einem Suchbereich scannen (z. B. 300..1800s).
    2) Für jede Periode die beste Phase aus Pre/Post-Dip-Score schätzen.
    3) Beste (Periode, Phase)-Kombination datengetrieben auswählen.
    4) Aus der Kombination Tagesgrenzen erzeugen und pro Grenze Event-Stärke
         sowie lokale Rückwirkung berechnen.

Ausgabe:
  Tabelle pro Grenze auf stdout + Tageszusammenfassung mit
  geschätzter Phase, Jitter und Evidenz.
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


NQ_DB_DIR = os.path.join(config.BASE_DIR, 'netzqualitaet', 'db')

PHASE_BIN_S = 3
BOUNDARY_HALF_WINDOW_S = 45
MIN_SAMPLES_WINDOW = 10


def get_db_path(date_obj):
    return os.path.join(NQ_DB_DIR, f"nq_{date_obj.strftime('%Y-%m')}.db")


def load_day_samples(conn, date_str):
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    ts_start = int(dt.timestamp())
    ts_end = int((dt + timedelta(days=1)).timestamp())

    cur = conn.execute(
        "SELECT ts, f_netz, u_l1_l2, u_l2_l3, u_l3_l1, i_l1, i_l2, i_l3 "
        "FROM nq_samples WHERE ts >= ? AND ts < ? ORDER BY ts",
        (ts_start, ts_end),
    )
    rows = cur.fetchall()
    if not rows:
        return None

    dtype = np.dtype([
        ('ts', np.int64), ('f', np.float64),
        ('u12', np.float64), ('u23', np.float64), ('u31', np.float64),
        ('i1', np.float64), ('i2', np.float64), ('i3', np.float64),
    ])
    return np.array(rows, dtype=dtype)


def moving_average(x, n):
    if n <= 1:
        return x.copy()
    kernel = np.ones(n, dtype=np.float64) / float(n)
    return np.convolve(x, kernel, mode='same')


def circular_smooth(v, width_bins):
    if width_bins <= 1:
        return v
    w = np.ones(width_bins, dtype=np.float64) / float(width_bins)
    ext = np.concatenate([v, v, v])
    sm = np.convolve(ext, w, mode='same')
    n = len(v)
    return sm[n:2 * n]


def build_second_grid(samples):
    """Resample Frequenz auf 1s-Raster (linear) fuer schnelle Fenstermittel."""
    ts = samples['ts'].astype(np.int64)
    f = samples['f'].astype(np.float64)
    valid = np.isfinite(f)
    ts = ts[valid]
    f = f[valid]
    if len(ts) < 100:
        return None

    day_start = int((ts[0] // 86400) * 86400)
    sec = np.arange(day_start, day_start + 86400, dtype=np.int64)

    # Lineare Interpolation auf Sekundenbasis.
    f_1s = np.interp(sec.astype(np.float64), ts.astype(np.float64), f)
    if not np.isfinite(f_1s).any():
        return None

    cs = np.concatenate([[0.0], np.cumsum(f_1s)])
    return {
        'day_start': day_start,
        'f_1s': f_1s,
        'cum_sum': cs,
    }


def compute_dip_series(csum, pre_s=60, post_s=60):
    """Berechnet Dip(t) = mean(pre) - mean(post) für jeden Sekundentakt."""
    n = len(csum) - 1
    dip = np.full(n, np.nan, dtype=np.float64)
    t = np.arange(pre_s, n - post_s + 1, dtype=np.int64)
    if len(t) == 0:
        return dip

    pre_mean = (csum[t] - csum[t - pre_s]) / float(pre_s)
    post_mean = (csum[t + post_s] - csum[t]) / float(post_s)
    dip[t] = pre_mean - post_mean
    return dip


def window_mean_from_cumsum(csum, a, b):
    """Mittelwert auf [a, b) in Sekundenindizes."""
    if b <= a:
        return None
    return float((csum[b] - csum[a]) / float(b - a))


def evaluate_period_from_dip(dip_series, period_s, smooth_width=11):
    """Bestimmt für eine feste Periode die beste Phase und Evidenz."""
    if period_s < 2:
        return None

    phase_scores = np.zeros(period_s, dtype=np.float64)
    phase_signed = np.zeros(period_s, dtype=np.float64)
    phase_count = np.zeros(period_s, dtype=np.int32)

    for phase in range(period_s):
        vals = dip_series[phase::period_s]
        vals = vals[np.isfinite(vals)]
        if len(vals) == 0:
            continue
        # Richtungsunabhaengige Ereignisenergie: verhindert 2x-Perioden-Bias
        # bei alternierenden Vorzeichen (z. B. +/− an benachbarten Grenzen).
        phase_scores[phase] = float(np.mean(np.abs(vals)))
        phase_signed[phase] = float(np.mean(vals))
        phase_count[phase] = int(len(vals))

    sm = circular_smooth(phase_scores, width_bins=min(smooth_width, max(3, period_s // 3)))
    best_phase = int(np.argmax(sm))
    peak = float(sm[best_phase]) if len(sm) else 0.0
    med = float(np.median(sm)) if len(sm) else 0.0
    evidence = (peak / med) if med > 1e-12 else None

    return {
        'period_s': int(period_s),
        'phase_s': int(best_phase),
        'peak_score': peak,
        'evidence_ratio': evidence,
        'phase_scores': sm,
        'phase_signed': phase_signed,
        'phase_count': phase_count,
    }


def infer_period_and_phase(samples, period_min_s=300, period_max_s=1800,
                          coarse_step_s=15, pre_s=60, post_s=60):
    """Scant den Periodenraum und liefert beste Periode+Phase (coarse/fine)."""
    grid = build_second_grid(samples)
    if grid is None:
        return None

    dip_series = compute_dip_series(grid['cum_sum'], pre_s=pre_s, post_s=post_s)

    pmin = max(int(period_min_s), pre_s + post_s + 1)
    pmax = int(period_max_s)
    if pmax <= pmin:
        return None

    coarse_step = max(1, int(coarse_step_s))
    coarse_periods = list(range(pmin, pmax + 1, coarse_step))
    if coarse_periods[-1] != pmax:
        coarse_periods.append(pmax)

    coarse_results = []
    for p in coarse_periods:
        r = evaluate_period_from_dip(dip_series, p)
        if r is not None:
            coarse_results.append(r)

    if not coarse_results:
        return None

    best_coarse = max(coarse_results, key=lambda x: x['peak_score'])

    # Feinscan um bestes coarse-Periodenfenster
    fine_lo = max(pmin, best_coarse['period_s'] - coarse_step)
    fine_hi = min(pmax, best_coarse['period_s'] + coarse_step)

    fine_results = []
    for p in range(fine_lo, fine_hi + 1):
        r = evaluate_period_from_dip(dip_series, p)
        if r is not None:
            fine_results.append(r)

    if not fine_results:
        return None

    best_peak = max(r['peak_score'] for r in fine_results)

    # Harmonische entkoppeln: kuerzeste nahezu gleich starke Periode bevorzugen.
    near_opt = [r for r in fine_results if r['peak_score'] >= 0.90 * best_peak]
    best = min(near_opt, key=lambda x: x['period_s']) if near_opt else max(fine_results, key=lambda x: x['peak_score'])

    top_periods = sorted(fine_results, key=lambda x: x['peak_score'], reverse=True)[:8]

    best['sample_count'] = int(len(samples))
    best['search_min_s'] = int(pmin)
    best['search_max_s'] = int(pmax)
    best['coarse_step_s'] = int(coarse_step)
    best['top_period_candidates'] = [
        {
            'period_s': int(r['period_s']),
            'peak_score': float(r['peak_score']),
            'evidence_ratio': float(r['evidence_ratio']) if r['evidence_ratio'] is not None else None,
            'phase_s': int(r['phase_s']),
        }
        for r in top_periods
    ]
    return best


def infer_phase_from_frequency(samples, detrend_window_s=300, smooth_phase_bins=9):
    ts = samples['ts'].astype(np.float64)
    f = samples['f'].astype(np.float64)

    valid = np.isfinite(f)
    ts = ts[valid]
    f = f[valid]
    if len(f) < 100:
        return None

    # Langsame Drift entfernen, damit Grenzereignisse dominieren.
    dt_med = np.median(np.diff(ts))
    points = max(3, int(round(detrend_window_s / max(dt_med, 1.0))))
    if points % 2 == 0:
        points += 1

    trend = moving_average(f, points)
    f_hp = f - trend

    dts = np.diff(ts)
    dfs = np.diff(f_hp)
    keep = dts > 0
    dts = dts[keep]
    dfs = dfs[keep]
    ts_g = ts[1:][keep]

    grad = np.abs(dfs / dts)
    # Robuste Kappung gegen Ausreisser
    p95 = np.percentile(grad, 95)
    if p95 > 0:
        grad = np.minimum(grad, p95)

    n_bins = PERIOD_S // PHASE_BIN_S
    bins = np.zeros(int(n_bins), dtype=np.float64)

    phase = np.mod(ts_g, PERIOD_S)
    idx = np.floor(phase / PHASE_BIN_S).astype(int)
    idx = np.clip(idx, 0, int(n_bins) - 1)
    np.add.at(bins, idx, grad)

    bins_sm = circular_smooth(bins, smooth_phase_bins)
    best_idx = int(np.argmax(bins_sm))
    phase_s = best_idx * PHASE_BIN_S

    # Evidenz: Peak gegen Median
    med = float(np.median(bins_sm)) if len(bins_sm) else 0.0
    peak = float(bins_sm[best_idx]) if len(bins_sm) else 0.0
    evidence = (peak / med) if med > 1e-12 else None

    return {
        'phase_s': int(phase_s),
        'phase_bins': bins_sm,
        'evidence_ratio': evidence,
        'sample_count': int(len(ts)),
    }


def build_boundaries_for_day(date_str, period_s, phase_s):
    day_start = int(datetime.strptime(date_str, '%Y-%m-%d').timestamp())
    day_end = day_start + 86400
    first = day_start + int(phase_s)
    if first < day_start:
        first += period_s

    out = []
    t = first
    while t < day_end:
        out.append(t)
        t += period_s
    return out


def classify_local_impact(pre_samples, post_samples):
    def _avg_valid(arr):
        arr = arr[np.isfinite(arr)]
        return float(np.mean(arr)) if len(arr) else None

    u_pre = [_avg_valid(pre_samples[c]) for c in ('u12', 'u23', 'u31')]
    u_post = [_avg_valid(post_samples[c]) for c in ('u12', 'u23', 'u31')]
    i_pre = [_avg_valid(pre_samples[c]) for c in ('i1', 'i2', 'i3')]
    i_post = [_avg_valid(post_samples[c]) for c in ('i1', 'i2', 'i3')]

    u_pre_m = np.mean([v for v in u_pre if v is not None]) if any(v is not None for v in u_pre) else None
    u_post_m = np.mean([v for v in u_post if v is not None]) if any(v is not None for v in u_post) else None
    i_pre_m = np.mean([abs(v) for v in i_pre if v is not None]) if any(v is not None for v in i_pre) else None
    i_post_m = np.mean([abs(v) for v in i_post if v is not None]) if any(v is not None for v in i_post) else None

    if u_pre_m is None or u_post_m is None or i_pre_m is None or i_post_m is None:
        return None, None, None

    u_delta = float(u_pre_m - u_post_m)
    i_delta = float(i_post_m - i_pre_m)

    if abs(u_delta) <= 0.3:
        return 0.0, u_delta, i_delta
    return round(min(abs(i_delta) / 2.0, 1.0), 3), u_delta, i_delta


def score_boundaries(samples, boundaries):
    ts = samples['ts']
    f = samples['f']

    events = []
    for bt in boundaries:
        pre_mask = (ts >= bt - BOUNDARY_HALF_WINDOW_S) & (ts < bt)
        post_mask = (ts >= bt) & (ts < bt + BOUNDARY_HALF_WINDOW_S)
        pre = samples[pre_mask]
        post = samples[post_mask]

        if len(pre) < MIN_SAMPLES_WINDOW or len(post) < MIN_SAMPLES_WINDOW:
            continue

        f_pre = pre['f'][np.isfinite(pre['f'])]
        f_post = post['f'][np.isfinite(post['f'])]
        if len(f_pre) < MIN_SAMPLES_WINDOW or len(f_post) < MIN_SAMPLES_WINDOW:
            continue

        f_pre_avg = float(np.mean(f_pre))
        f_post_avg = float(np.mean(f_post))
        step_hz = f_post_avg - f_pre_avg

        nadir_mask = (ts >= bt - 30) & (ts <= bt + 30)
        nadir_f = f[nadir_mask]
        nadir_ts = ts[nadir_mask]
        valid_nadir = np.isfinite(nadir_f)
        if valid_nadir.any():
            min_idx = np.argmin(nadir_f[valid_nadir])
            f_nadir = float(nadir_f[valid_nadir][min_idx])
            nadir_offset_s = int(nadir_ts[valid_nadir][min_idx] - bt)
        else:
            f_nadir = None
            nadir_offset_s = None

        lis, u_delta, i_delta = classify_local_impact(pre, post)

        strength = abs(step_hz)
        events.append({
            'boundary_ts': int(bt),
            'step_hz': step_hz,
            'strength_hz': strength,
            'f_pre_avg': f_pre_avg,
            'f_post_avg': f_post_avg,
            'f_nadir': f_nadir,
            'nadir_offset_s': nadir_offset_s,
            'local_impact': lis,
            'u_delta': u_delta,
            'i_delta': i_delta,
            'n_pre': int(len(pre)),
            'n_post': int(len(post)),
        })
    return events


def summarize(date_str, phase_info, events):
    phase = int(phase_info['phase_s'])
    period = int(phase_info['period_s'])

    # Optionaler Bezug auf 15-min-Raster zur Einordnung.
    quarter_phase = phase % 900
    quarter_offset = min(quarter_phase, 900 - quarter_phase)

    if not events:
        return {
            'date': date_str,
            'period_s': period,
            'phase_s': phase,
            'phase_offset_to_quarter_s': int(quarter_offset),
            'evidence_ratio': phase_info['evidence_ratio'],
            'n_events': 0,
        }

    strengths = np.array([e['strength_hz'] for e in events], dtype=np.float64)
    steps = np.array([e['step_hz'] for e in events], dtype=np.float64)
    local = np.array([e['local_impact'] for e in events if e['local_impact'] is not None], dtype=np.float64)

    strong_thr = float(np.percentile(strengths, 75))
    strong_events = [e for e in events if e['strength_hz'] >= strong_thr]

    jitter = []
    for e in strong_events:
        offs = np.mod(e['boundary_ts'], period)
        diff = min(abs(offs - phase_info['phase_s']), period - abs(offs - phase_info['phase_s']))
        jitter.append(diff)

    return {
        'date': date_str,
        'period_s': period,
        'phase_s': phase,
        'phase_offset_to_quarter_s': int(quarter_offset),
        'evidence_ratio': phase_info['evidence_ratio'],
        'n_events': int(len(events)),
        'step_abs_mean_mhz': round(float(np.mean(np.abs(steps)) * 1000.0), 1),
        'step_abs_max_mhz': round(float(np.max(np.abs(steps)) * 1000.0), 1),
        'strong_threshold_mhz': round(strong_thr * 1000.0, 1),
        'strong_events': int(len(strong_events)),
        'jitter_median_s': int(np.median(jitter)) if jitter else None,
        'jitter_max_s': int(np.max(jitter)) if jitter else None,
        'local_events': int(np.sum(local > 0.3)) if len(local) else 0,
        'grid_like_events': int(np.sum(local <= 0.3)) if len(local) else 0,
    }


def run_day(date_str, max_rows=30, period_min_s=300, period_max_s=1800, coarse_step_s=15):
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    db_path = get_db_path(date_obj)
    if not os.path.exists(db_path):
        print(f"Keine NQ-DB gefunden: {db_path}")
        return 1

    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        samples = load_day_samples(conn, date_str)
        if samples is None:
            print(f"Keine Samples fuer {date_str}")
            return 1

        phase_info = infer_period_and_phase(
            samples,
            period_min_s=period_min_s,
            period_max_s=period_max_s,
            coarse_step_s=coarse_step_s,
            pre_s=60,
            post_s=60,
        )
        fallback_used = False
        if phase_info is None:
            phase_info = infer_phase_from_frequency(samples)
            fallback_used = True
            if phase_info is not None:
                phase_info['period_s'] = 900

        if phase_info is None:
            print(f"Zu wenige gueltige Frequenzdaten fuer {date_str}")
            return 1

        boundaries = build_boundaries_for_day(
            date_str,
            period_s=phase_info['period_s'],
            phase_s=phase_info['phase_s'],
        )
        events = score_boundaries(samples, boundaries)
        summary = summarize(date_str, phase_info, events)

        print("=" * 84)
        print(f"Trade-Switch Detection {date_str}")
        print("=" * 84)
        print(f"DB:                  {os.path.basename(db_path)}")
        print(f"Samples:             {phase_info['sample_count']}")
        print(f"Periode (geschaetzt): {summary['period_s']}s")
        if not fallback_used:
            print(f"Suchraum:            {phase_info['search_min_s']}..{phase_info['search_max_s']}s, step={phase_info['coarse_step_s']}s")
            if phase_info.get('top_period_candidates'):
                top = phase_info['top_period_candidates'][:3]
                top_str = ', '.join([f"{p['period_s']}s" for p in top])
                print(f"Top-Perioden:        {top_str}")
        print(f"Geschaetzte Phase:   +{summary['phase_s']}s ab Tagesstart")
        print(f"Offset zu Viertelst.: {summary['phase_offset_to_quarter_s']}s")
        print(f"Methode:             {'Gradient-Phase (Fallback)' if fallback_used else 'Boundary-Scan (datengetrieben)'}")
        print(f"Evidenz (Peak/Med):  {summary['evidence_ratio']:.2f}" if summary['evidence_ratio'] else "Evidenz (Peak/Med):  n/a")
        print(f"Events:              {summary['n_events']}")
        if summary['n_events'] > 0:
            print(f"|Step| Mittel/Max:   {summary['step_abs_mean_mhz']} / {summary['step_abs_max_mhz']} mHz")
            print(f"Starke Events >=:    {summary['strong_threshold_mhz']} mHz")
            print(f"Starke Events:       {summary['strong_events']}")
            print(f"Jitter med/max:      {summary['jitter_median_s']} / {summary['jitter_max_s']} s")
            print(f"Lokal vs Netz:       {summary['local_events']} / {summary['grid_like_events']}")
        print()

        print("boundary_time         step_mHz  f_pre    f_post   f_nadir  nadir_s  local  u_deltaV  i_deltaA")
        print("-------------------  --------  -------  -------  -------  -------  -----  --------  --------")

        events_sorted = sorted(events, key=lambda e: e['boundary_ts'])
        for e in events_sorted[:max_rows]:
            t = datetime.fromtimestamp(e['boundary_ts']).strftime('%Y-%m-%d %H:%M:%S')
            step_mhz = e['step_hz'] * 1000.0
            f_nadir = e['f_nadir'] if e['f_nadir'] is not None else float('nan')
            nadir_s = e['nadir_offset_s'] if e['nadir_offset_s'] is not None else 0
            local = e['local_impact'] if e['local_impact'] is not None else float('nan')
            u_d = e['u_delta'] if e['u_delta'] is not None else float('nan')
            i_d = e['i_delta'] if e['i_delta'] is not None else float('nan')
            print(
                f"{t}  "
                f"{step_mhz:8.1f}  {e['f_pre_avg']:7.4f}  {e['f_post_avg']:7.4f}  "
                f"{f_nadir:7.4f}  {nadir_s:7d}  {local:5.2f}  {u_d:8.2f}  {i_d:8.3f}"
            )

        return 0
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description='Datengetriebene Erkennung handelsgetriebener Schaltzeiten')
    parser.add_argument('--date', required=True, help='Datum YYYY-MM-DD')
    parser.add_argument('--rows', type=int, default=30, help='Maximal ausgegebene Event-Zeilen')
    parser.add_argument('--period-min', type=int, default=300, help='Minimale Suchperiode in Sekunden')
    parser.add_argument('--period-max', type=int, default=1800, help='Maximale Suchperiode in Sekunden')
    parser.add_argument('--period-step', type=int, default=15, help='Coarse-Step der Periodensuche in Sekunden')
    args = parser.parse_args()
    raise SystemExit(
        run_day(
            args.date,
            max_rows=args.rows,
            period_min_s=args.period_min,
            period_max_s=args.period_max,
            coarse_step_s=args.period_step,
        )
    )


if __name__ == '__main__':
    main()
