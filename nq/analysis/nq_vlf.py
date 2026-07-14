"""nq.analysis.nq_vlf — VLF-Analyse: Tages-/Wochenprofil, Changepoints, Saisonaldrift.

Eingang: nq_hourly + nq_daily (direkte DB-Abfragen).
Ausgang: Liste von Event-Dicts für nq_events (band='VLF').

Methoden:
  - Profil-Anomalie: stündlicher z-Score gegen 30-Tage-Rollprofil → |z| > sigma_thr
  - CUSUM-Changepoint: rollender Mittelwert-Shift (7d pre vs. 7d post) auf nq_daily
  Keine externen Pakete (kein scipy/ruptures) — pure Python + stdlib math.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime


def _mean_std(vals: list[float]) -> tuple[float | None, float | None]:
    clean = [v for v in vals if v is not None and math.isfinite(v)]
    if len(clean) < 3:
        return None, None
    n = len(clean)
    mean = sum(clean) / n
    var = sum((v - mean) ** 2 for v in clean) / n
    return mean, math.sqrt(var)


def detect_profile_anomalies(
    conn: sqlite3.Connection,
    day: str,
    cfg: dict,
) -> list[dict]:
    """Vergleicht Stundenwerte des Tages gegen 30-Tage-Rollprofil (Stunde-des-Tages).

    Für jede Stunde: z = |v − μ_h| / σ_h. Event wenn z > sigma_thr.
    """
    sigma_thr = cfg.get("vlf_sigma_threshold", 2.0)
    events: list[dict] = []
    day_dt = datetime.strptime(day, "%Y-%m-%d")
    day_ts = int(day_dt.timestamp())
    profile_start = day_ts - 30 * 86400

    for qty in ("f", "u_l1", "u_l2", "u_l3", "thd_u_l1", "thd_u_l2", "thd_u_l3"):
        # Referenzprofil: vavg je Stunde-des-Tages aus den 30 Vortagen
        ref_rows = conn.execute(
            "SELECT CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) h, vavg "
            "FROM nq_hourly "
            "WHERE quantity=? AND meas='' AND phase=0 AND ord=0 "
            "AND ts >= ? AND ts < ? ORDER BY ts",
            (qty, profile_start, day_ts),
        ).fetchall()
        if len(ref_rows) < 24:
            continue

        profile: dict[int, list[float]] = {h: [] for h in range(24)}
        for h, v in ref_rows:
            if v is not None and math.isfinite(v):
                profile[h].append(v)

        # Tageswerte
        day_rows = conn.execute(
            "SELECT ts, "
            "CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) h, "
            "vavg "
            "FROM nq_hourly "
            "WHERE quantity=? AND meas='' AND phase=0 AND ord=0 "
            "AND ts >= ? AND ts < ? ORDER BY ts",
            (qty, day_ts, day_ts + 86400),
        ).fetchall()

        for ts, h, v in day_rows:
            if v is None or not math.isfinite(v):
                continue
            mean, std = _mean_std(profile.get(h, []))
            if mean is None or std is None or std < 1e-6:
                continue
            z = abs(v - mean) / std
            if z <= sigma_thr:
                continue
            sev = min((z - sigma_thr) / max(sigma_thr, 0.1), 1.0)
            events.append({
                "band": "VLF",
                "kind": "profile_anomaly",
                "trigger": f"z_{qty}_h{h}",
                "ts_start": int(ts),
                "ts_end": int(ts) + 3600,
                "duration_s": 3600.0,
                "severity": round(sev, 4),
                "peak_quantity": qty,
                "peak_value": round(float(v), 4),
                "origin": "netzseitig",
                "metrics": json.dumps({
                    "qty": qty, "hour": h,
                    "z_score": round(z, 3),
                    "profile_mean": round(mean, 4),
                    "profile_std": round(std, 4),
                    "n_ref_pts": len(profile.get(h, [])),
                }),
                "n_samples": 1,
            })

    return events


def detect_changepoints(
    conn: sqlite3.Connection,
    day: str,
    cfg: dict,
) -> list[dict]:
    """CUSUM-ähnliche Changepoint-Erkennung: 7d-pre vs. 7d-post auf nq_daily.

    Gibt Event mit kind='changepoint' wenn Shift z-Score > vlf_changepoint_z.
    """
    z_thr = cfg.get("vlf_changepoint_z", 2.5)
    events: list[dict] = []

    for qty in ("u_l1", "u_l2", "u_l3", "thd_u_l1", "f"):
        pre_rows = conn.execute(
            "SELECT vavg FROM nq_daily "
            "WHERE quantity=? AND meas='' AND phase=0 AND ord=0 "
            "AND day >= date(?, '-7 days') AND day < ? ORDER BY day",
            (qty, day, day),
        ).fetchall()
        post_rows = conn.execute(
            "SELECT vavg FROM nq_daily "
            "WHERE quantity=? AND meas='' AND phase=0 AND ord=0 "
            "AND day > ? AND day <= date(?, '+7 days') ORDER BY day",
            (qty, day, day),
        ).fetchall()

        pre_vals = [r[0] for r in pre_rows if r[0] is not None and math.isfinite(r[0])]
        post_vals = [r[0] for r in post_rows if r[0] is not None and math.isfinite(r[0])]
        if len(pre_vals) < 3 or len(post_vals) < 2:
            continue

        pre_mean, pre_std = _mean_std(pre_vals)
        if pre_mean is None or pre_std is None or pre_std < 1e-9:
            continue
        post_mean = sum(post_vals) / len(post_vals)
        z = abs(post_mean - pre_mean) / pre_std
        if z <= z_thr:
            continue

        day_dt = datetime.strptime(day, "%Y-%m-%d")
        day_ts = int(day_dt.timestamp())
        sev = min((z - z_thr) / 5.0, 1.0)
        events.append({
            "band": "VLF",
            "kind": "changepoint",
            "trigger": f"cusum_{qty}",
            "ts_start": day_ts,
            "ts_end": day_ts + 86400,
            "duration_s": 86400.0,
            "severity": round(sev, 4),
            "peak_quantity": qty,
            "peak_value": round(post_mean, 4),
            "origin": "netzseitig",
            "metrics": json.dumps({
                "qty": qty,
                "pre_mean": round(pre_mean, 4),
                "post_mean": round(post_mean, 4),
                "shift": round(abs(post_mean - pre_mean), 4),
                "z_score": round(z, 3),
                "n_pre": len(pre_vals),
                "n_post": len(post_vals),
            }),
            "n_samples": len(pre_vals) + len(post_vals),
        })

    return events


def run_vlf(
    conn: sqlite3.Connection,
    day: str,
    cfg: dict,
) -> list[dict]:
    """Führt alle VLF-Detektoren aus."""
    events: list[dict] = []
    events.extend(detect_profile_anomalies(conn, day, cfg))
    events.extend(detect_changepoints(conn, day, cfg))
    return events
