"""nq.analysis.nq_hf — HF_local-Analyse: THD-Spikes, U↔I-Korrelation, Residualfilter.

Eingang: Skalare aus nq_5min (pivotiert durch nq_events._load_ts_series).
Ausgang: Liste von Event-Dicts für nq_events (band='HF_local').

Methoden:
  - THD-Spike-Detektion: vmax > Schwelle über ≥2 aufeinanderfolgende 10s-Buckets
  - U↔I-Residual: ΔU_net = ΔU_meas − ΔI × Z_loop → origin-Klassifikation
  - Pearson-Korrelation (ΔI, ΔU) im Ereignisfenster → lokal / netzseitig / unklar
"""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

# Mindest aufeinanderfolgende Buckets (10 s) für THD-Spike
_MIN_CONSEC = 2

_THD_QUANTITIES: dict[str, tuple[str, int]] = {
    "thd_u_l1": ("THDu", 1), "thd_u_l2": ("THDu", 2), "thd_u_l3": ("THDu", 3),
    "thd_i_l1": ("THDi", 1), "thd_i_l2": ("THDi", 2), "thd_i_l3": ("THDi", 3),
}


def _pearson_r(x: np.ndarray, y: np.ndarray) -> float | None:
    """Pearson-Korrelation mit Plausibilitätsprüfungen.

    Filtert NaN/Inf/extreme Werte (>1e15 abs).
    Ergebnis muss im gültigen Bereich [-1, 1] liegen.
    """
    mask = np.isfinite(x) & np.isfinite(y) & (np.abs(x) < 1e15) & (np.abs(y) < 1e15)
    if mask.sum() < 5:
        return None
    xm = x[mask]; ym = y[mask]
    mx, my = xm.mean(), ym.mean()
    num = float(((xm - mx) * (ym - my)).sum())
    den = math.sqrt(float(((xm - mx) ** 2).sum()) * float(((ym - my) ** 2).sum()))
    if den <= 1e-12:
        return None
    r = num / den
    # Plausibilitätsprüfung des Ergebnisses
    if not np.isfinite(r) or abs(r) > 1.0:
        return None
    return r


def detect_thd_spikes(ts_series: dict[str, Any], cfg: dict) -> list[dict]:
    """THD-Spike-Detektion auf nq_5min-Aggregaten (vmax als Spitzenindikator).

    Gibt Events mit kind='thd_spike' zurück.
    """
    thr_u = cfg.get("thd_u_spike_pct", 5.0)
    thr_i = cfg.get("thd_i_spike_pct", 80.0)
    events: list[dict] = []

    for qty, (_, phase) in _THD_QUANTITIES.items():
        if qty not in ts_series:
            continue
        d = ts_series[qty]
        ts = d["ts"]
        vmax = d["vmax"].astype(float)
        thr = thr_u if "thd_u" in qty else thr_i

        above = np.where(np.isfinite(vmax) & (vmax > thr))[0]
        if len(above) == 0:
            continue

        # Zusammenhängende Gruppen
        groups: list[list[int]] = [[above[0]]]
        for idx in above[1:]:
            if idx == groups[-1][-1] + 1:
                groups[-1].append(idx)
            else:
                groups.append([idx])

        for grp in groups:
            if len(grp) < _MIN_CONSEC:
                continue
            peak_val = float(np.nanmax(vmax[grp]))
            severity = min((peak_val - thr) / max(thr, 1.0), 1.0)
            events.append({
                "band": "HF_local",
                "kind": "thd_spike",
                "trigger": qty,
                "ts_start": int(ts[grp[0]]),
                "ts_end": int(ts[grp[-1]]) + 10,
                "duration_s": float((ts[grp[-1]] - ts[grp[0]]) + 10),
                "severity": round(severity, 4),
                "peak_quantity": qty,
                "peak_value": round(peak_val, 2),
                "origin": None,
                "metrics": json.dumps({"phase": phase, "threshold_pct": thr, "n_consec": len(grp)}),
                "n_samples": len(grp),
            })

    return events


def detect_ui_correlation(
    ts_series: dict[str, Any],
    z_loop: dict,
    cfg: dict,
) -> list[dict]:
    """U↔I-Korrelation mit Residualfilterung zur Kausalitätsbestimmung.

    Residual: ΔU_net = ΔU_meas − ΔI × Z_abs_Ω
    RMS(ΔU_net) über 60s-Fenster > Schwelle → Ereignis.
    Pearson(ΔI, ΔU) im Fenster → origin: lokal (r>0.7) / netzseitig (r<0.2) / unklar.
    """
    z_abs = z_loop.get("Z_abs_mOhm", 299) / 1000.0   # Ω
    thr = cfg.get("du_net_step_v", 1.5)
    win = 6   # 6 × 10s = 60s

    events: list[dict] = []

    for phase, (u_qty, i_qty) in {1: ("u_l1", "i_l1"), 2: ("u_l2", "i_l2"), 3: ("u_l3", "i_l3")}.items():
        if u_qty not in ts_series or i_qty not in ts_series:
            continue
        ud = ts_series[u_qty]; id_ = ts_series[i_qty]
        if not np.array_equal(ud["ts"], id_["ts"]):
            continue

        u_avg = ud["vavg"].astype(float)
        i_avg = id_["vavg"].astype(float)
        ts_arr = ud["ts"]

        if np.isfinite(u_avg).sum() < 12:
            continue

        du = np.diff(u_avg)
        di = np.diff(i_avg)
        ts_d = ts_arr[1:]
        valid_d = np.isfinite(du) & np.isfinite(di)

        du_net = du - di * z_abs
        last_event_end = 0

        for i in range(len(du_net) - win + 1):
            seg_v = valid_d[i:i + win]
            if seg_v.sum() < win // 2:
                continue
            rms = float(np.sqrt(np.nanmean(du_net[i:i + win][seg_v] ** 2)))
            if rms <= thr:
                continue
            t = int(ts_d[i])
            if t <= last_event_end:
                continue

            i1 = min(i + win - 1, len(ts_d) - 1)
            r = _pearson_r(di[i:i1 + 1], du[i:i1 + 1])
            if r is None:
                origin = "unklar"
            elif r > 0.7:
                origin = "lokal"
            elif r < 0.2:
                origin = "netzseitig"
            else:
                origin = "unklar"

            peak_net = float(np.nanmax(np.abs(du_net[i:i1 + 1])))
            severity = min(rms / max(thr * 2, 0.01), 1.0)
            events.append({
                "band": "HF_local",
                "kind": "u_residual_event",
                "trigger": f"du_net_l{phase}",
                "ts_start": t,
                "ts_end": int(ts_d[i1]) + 10,
                "duration_s": float(ts_d[i1] - ts_d[i] + 10),
                "severity": round(severity, 4),
                "peak_quantity": f"du_net_l{phase}",
                "peak_value": round(peak_net, 3),
                "origin": origin,
                "metrics": json.dumps({
                    "phase": phase,
                    "pearson_r": round(r, 3) if r is not None else None,
                    "rms_du_net_v": round(rms, 4),
                    "z_abs_ohm": round(z_abs, 4),
                }),
                "n_samples": win,
            })
            last_event_end = int(ts_d[i1]) + 10

    return events


def run_hf(
    ts_series: dict[str, Any],
    z_loop: dict,
    cfg: dict,
) -> list[dict]:
    """Führt alle HF_local-Detektoren aus."""
    events: list[dict] = []
    events.extend(detect_thd_spikes(ts_series, cfg))
    events.extend(detect_ui_correlation(ts_series, z_loop, cfg))
    return events
