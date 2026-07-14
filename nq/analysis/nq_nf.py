"""nq.analysis.nq_nf — NF_global-Analyse: DFD, df/dt-Gradienten, Trafofilter, U-Band.

Eingang: nq_agg_10s (ts_series-Dict) + nq_5min (direkte DB-Abfrage).
Ausgang: Liste von Event-Dicts für nq_events (band='NF_global').

Methoden:
  - DFD: Frequenzsprung an :00/:15/:30/:45-Grenzen — normal vs. Anomalie
  - df/dt: rollendes 60s-Fenster → Nadir / Peak-Erkennung
  - Tap-Filter: diskrete U-Sprünge an 15-min-Grenzen → gefiltert; außerhalb → u_step
  - U-Band (EN 50160): u_avg außerhalb 207..253 V über ≥2 × 5min-Buckets → Verletzung
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from typing import Any

import numpy as np

NOMINAL_FREQ = 50.0
BLOCK_S = 900
MIN_SAMPLES_BOUNDARY = 3   # mindest 10s-Buckets im Grenzfenster


def _linear_slope(ts: np.ndarray, vals: np.ndarray) -> float | None:
    """Lineare Steigung via OLS (ohne numpy.polyfit)."""
    mask = np.isfinite(vals)
    if mask.sum() < 3:
        return None
    t = ts[mask].astype(float); v = vals[mask].astype(float)
    t -= t[0]
    if t[-1] < 1e-9:
        return None
    n = len(t)
    sx, sy = float(t.sum()), float(v.sum())
    sxy = float((t * v).sum()); sx2 = float((t * t).sum())
    denom = n * sx2 - sx * sx
    return float((n * sxy - sx * sy) / denom) if abs(denom) > 1e-12 else None


def _classify_boundary(ts: int) -> str:
    m = datetime.fromtimestamp(ts).minute
    if m == 0:
        return "full_hour"
    if m == 30:
        return "half_hour"
    return "quarter_hour"


def detect_dfd_events(
    ts_arr: np.ndarray,
    f_arr: np.ndarray,
    day_ts_start: int,
    cfg: dict,
) -> list[dict]:
    """DFD an den 15-min-Handelsgrenzen.

    Adaptiert aus netzqualitaet/nq_analysis.py:analyze_boundary.
    Alle Grenzereignisse werden geschrieben (kind='dfd_normal' oder 'dfd_anomaly').
    DFD-Anomalie: |f_post_avg − f_pre_avg| > dfd_anomaly_hz.
    """
    dfd_win = int(cfg.get("dfd_window_s", 180))
    anomaly_hz = cfg.get("dfd_anomaly_hz", 0.1)
    events: list[dict] = []
    day_ts_end = day_ts_start + 86400

    b = ((day_ts_start // BLOCK_S) + 1) * BLOCK_S
    while b < day_ts_end:
        pre_m = (ts_arr >= b - dfd_win) & (ts_arr < b)
        post_m = (ts_arr >= b) & (ts_arr < b + dfd_win)
        f_pre_v = f_arr[pre_m][np.isfinite(f_arr[pre_m])]
        f_post_v = f_arr[post_m][np.isfinite(f_arr[post_m])]

        if len(f_pre_v) < MIN_SAMPLES_BOUNDARY or len(f_post_v) < MIN_SAMPLES_BOUNDARY:
            b += BLOCK_S
            continue

        f_pre_avg = float(np.mean(f_pre_v))
        f_post_avg = float(np.mean(f_post_v))
        dfd_amp = abs(f_post_avg - f_pre_avg)

        # Nadir im ±30s-Fenster
        nadir_m = (ts_arr >= b - 30) & (ts_arr <= b + 30)
        f_nadir_v = f_arr[nadir_m][np.isfinite(f_arr[nadir_m])]
        f_nadir = float(np.min(f_nadir_v)) if len(f_nadir_v) > 0 else None

        slope_post = _linear_slope(ts_arr[post_m], f_arr[post_m])

        is_anomaly = dfd_amp > anomaly_hz
        severity = min(dfd_amp / max(anomaly_hz, 1e-9), 1.0) if is_anomaly else 0.0

        events.append({
            "band": "NF_global",
            "kind": "dfd_anomaly" if is_anomaly else "dfd_normal",
            "trigger": "df_step",
            "ts_start": int(b - dfd_win),
            "ts_end": int(b + dfd_win),
            "duration_s": float(2 * dfd_win),
            "severity": round(severity, 4),
            "peak_quantity": "f",
            "peak_value": round(f_nadir, 4) if f_nadir is not None else round(f_pre_avg, 4),
            "origin": "netzseitig",
            "metrics": json.dumps({
                "boundary_type": _classify_boundary(b),
                "dfd_amplitude_hz": round(dfd_amp, 4),
                "f_pre_avg": round(f_pre_avg, 4),
                "f_post_avg": round(f_post_avg, 4),
                "f_nadir": round(f_nadir, 4) if f_nadir is not None else None,
                "slope_post_hz_per_s": round(slope_post, 6) if slope_post is not None else None,
                "is_anomaly": is_anomaly,
            }),
            "n_samples": int(len(f_pre_v) + len(f_post_v)),
        })
        b += BLOCK_S

    return events


def detect_freq_gradient(
    ts_arr: np.ndarray,
    f_arr: np.ndarray,
    cfg: dict,
) -> list[dict]:
    """Rollendes 60s-Fenster df/dt → freq_nadir / freq_peak bei Schwellwertüberschreitung."""
    thr_hz_per_s = cfg.get("df_gradient_hz_per_min", 0.05) / 60.0
    win_s = 60
    events: list[dict] = []
    last_event_end = 0

    for i in range(len(ts_arr)):
        t0 = int(ts_arr[i])
        if t0 <= last_event_end:
            continue
        win_m = (ts_arr >= t0) & (ts_arr < t0 + win_s)
        f_win = f_arr[win_m]
        ts_win = ts_arr[win_m]
        f_v = f_win[np.isfinite(f_win)]
        if len(f_v) < 4:
            continue
        slope = _linear_slope(ts_win, f_win)
        if slope is None or abs(slope) <= thr_hz_per_s:
            continue

        kind = "freq_nadir" if slope < 0 else "freq_peak"
        severity = min(abs(slope) / max(thr_hz_per_s * 3, 1e-9), 1.0)
        events.append({
            "band": "NF_global",
            "kind": kind,
            "trigger": "df_gradient",
            "ts_start": t0,
            "ts_end": t0 + win_s,
            "duration_s": float(win_s),
            "severity": round(severity, 4),
            "peak_quantity": "f",
            "peak_value": round(float(np.nanmin(f_v) if slope < 0 else np.nanmax(f_v)), 4),
            "origin": "netzseitig",
            "metrics": json.dumps({
                "slope_hz_per_s": round(slope, 6),
                "threshold_hz_per_s": round(thr_hz_per_s, 6),
                "f_min": round(float(np.nanmin(f_v)), 4),
                "f_max": round(float(np.nanmax(f_v)), 4),
            }),
            "n_samples": int(len(f_v)),
        })
        last_event_end = t0 + win_s

    return events


def detect_tap_and_u_steps(
    ts_arr: np.ndarray,
    u_avgs: dict[str, np.ndarray],
    cfg: dict,
) -> list[dict]:
    """Diskrete U-Sprünge detektieren und Trafo-Taps herausfiltern.

    Filter: Sprung innerhalb ±30 s einer :00/:15/:30/:45-Grenze → Tap, kein Event.
    Außerhalb → kind='u_step'.
    """
    thr = cfg.get("thres_tap_v", 2.0)
    events: list[dict] = []

    for qty, u in u_avgs.items():
        u = u.astype(float)
        du = np.diff(u)
        ts_d = ts_arr[1:]
        cooldown_end = 0

        for i, dui in enumerate(du):
            if not math.isfinite(dui) or abs(dui) <= thr:
                continue
            t = int(ts_d[i])
            if t <= cooldown_end:
                continue
            # Tap-Filter: Sprung nahe einer 15-min-Grenze?
            mod = t % BLOCK_S
            if mod <= 30 or mod >= BLOCK_S - 30:
                continue   # normaler Trafo-Tap → ignorieren

            peak = float(u[i + 1]) if math.isfinite(u[i + 1]) else float(u[i] + dui)
            severity = min(abs(dui) / max(thr * 2, 0.01), 1.0)
            events.append({
                "band": "NF_global",
                "kind": "u_step",
                "trigger": "du_step",
                "ts_start": t - 10,
                "ts_end": t + 10,
                "duration_s": 20.0,
                "severity": round(severity, 4),
                "peak_quantity": qty,
                "peak_value": round(peak, 2),
                "origin": None,
                "metrics": json.dumps({"qty": qty, "du_v": round(float(dui), 3)}),
                "n_samples": 1,
            })
            cooldown_end = t + 120  # 2 min Cooldown

    return events


def detect_u_rms_violations(
    conn: sqlite3.Connection,
    ts_start: int,
    ts_end: int,
    cfg: dict,
) -> list[dict]:
    """EN 50160 U-Band (207..253 V) — aus nq_5min, ≥2 aufeinanderfolgende Verletzungs-Buckets."""
    u_min = cfg.get("u_band_min_v", 207.0)
    u_max = cfg.get("u_band_max_v", 253.0)
    events: list[dict] = []

    for qty in ("u_l1", "u_l2", "u_l3"):
        rows = conn.execute(
            "SELECT ts, vmin, vavg, vmax, n FROM nq_5min "
            "WHERE quantity=? AND meas='' AND phase=0 AND ord=0 "
            "AND ts >= ? AND ts < ? ORDER BY ts",
            (qty, ts_start, ts_end),
        ).fetchall()

        run: list[tuple] = []
        for row in rows:
            ts, _, vavg, _, _ = row
            if vavg is None or not math.isfinite(vavg):
                if len(run) >= 2:
                    _emit_u_violation(events, run, qty, u_min, u_max)
                run = []
                continue
            if vavg < u_min or vavg > u_max:
                run.append(row)
            else:
                if len(run) >= 2:
                    _emit_u_violation(events, run, qty, u_min, u_max)
                run = []
        if len(run) >= 2:
            _emit_u_violation(events, run, qty, u_min, u_max)

    return events


def _emit_u_violation(
    events: list[dict],
    buckets: list[tuple],
    qty: str,
    u_min: float,
    u_max: float,
) -> None:
    vavg_vals = [r[2] for r in buckets if r[2] is not None and math.isfinite(r[2])]
    if not vavg_vals:
        return
    peak = min(vavg_vals) if min(vavg_vals) < u_min else max(vavg_vals)
    if peak < u_min:
        sev = min((u_min - peak) / max(u_min - 195.0, 1.0), 1.0)
    else:
        sev = min((peak - u_max) / max(267.0 - u_max, 1.0), 1.0)
    events.append({
        "band": "NF_global",
        "kind": "u_rms_violation",
        "trigger": "u_rms",
        "ts_start": int(buckets[0][0]),
        "ts_end": int(buckets[-1][0]) + 300,
        "duration_s": float(buckets[-1][0] - buckets[0][0] + 300),
        "severity": round(max(sev, 0.0), 4),
        "peak_quantity": qty,
        "peak_value": round(peak, 2),
        "origin": "netzseitig",
        "metrics": json.dumps({
            "qty": qty,
            "u_min_band": u_min, "u_max_band": u_max,
            "n_buckets": len(buckets),
        }),
        "n_samples": int(sum(r[4] or 0 for r in buckets)),
    })


def run_nf(
    conn: sqlite3.Connection,
    ts_series: dict[str, Any],
    ts_start: int,
    ts_end: int,
    cfg: dict,
) -> list[dict]:
    """Führt alle NF_global-Detektoren aus."""
    events: list[dict] = []

    f_d = ts_series.get("f")
    if f_d is not None:
        ts_arr = f_d["ts"]
        f_arr = f_d["vavg"].astype(float)
        events.extend(detect_dfd_events(ts_arr, f_arr, ts_start, cfg))
        events.extend(detect_freq_gradient(ts_arr, f_arr, cfg))

    u_avgs = {q: ts_series[q]["vavg"] for q in ("u_l1", "u_l2", "u_l3") if q in ts_series}
    if u_avgs:
        ts_ref = ts_series[next(iter(u_avgs))]["ts"]
        events.extend(detect_tap_and_u_steps(ts_ref, u_avgs, cfg))

    events.extend(detect_u_rms_violations(conn, ts_start, ts_end, cfg))
    return events
