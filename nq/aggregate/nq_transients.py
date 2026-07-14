"""nq.aggregate.nq_transients — Transienten-Erkennung je 5-min-Fenster (Rolle N, Tech).

NQ2 WP2: Aus dem 200-ms-RAW (``nq_raw_fast``) werden je 5-min-Fenster und Phase
schnelle Sprünge (Transienten) in U und I gezählt und die Anstiegsgeschwindigkeit
(slew rate) gemessen — zusätzlich zu min/avg/max. Ziel: eine gleichmäßige Rampe
(400→420 V über 5 min) von einem echten Sprung (400→420 V in 0,4 s) unterscheiden.

Läuft **auf Tech** (nq_raw_fast lebt nur dort, 12-h-Ring) und schreibt
``nq_transient_5min``; der 4-h-Transfer übernimmt die Zeilen nach Primary.

Start (Tech):  python3 -m nq.aggregate.nq_transients [--hours N] [--db PATH]
Doku:  doc/netzqualitaet/NQ_MODUL.md §6.
"""
from __future__ import annotations

import argparse
import time

from nq.nq_common import load_config, open_db, TECH_SCHEMA

_PHASES = (1, 2, 3)
_U_COLS = {1: "u_l1", 2: "u_l2", 3: "u_l3"}
_I_COLS = {1: "i_l1", 2: "i_l2", 3: "i_l3"}


def analyze_jumps(series: list, threshold: float, max_dt_s: float = 0.3) -> tuple:
    """Zählt Sprünge >= ``threshold`` zwischen aufeinanderfolgenden Samples.

    ``series``: Liste ``(ts_ms, value)`` aufsteigend. Nur zeitlich benachbarte
    Paare (dt <= max_dt_s) werden gewertet — verhindert Fehlzählung über Lücken.
    Returns ``(count_pos, count_neg, slew_avg, slew_max)`` (slew in Einheit/s).
    """
    prev_ts = prev_v = None
    cpos = cneg = 0
    slews: list = []
    for ts_ms, v in series:
        if v is None:
            continue
        if prev_v is not None:
            dt = (ts_ms - prev_ts) / 1000.0
            if 0 < dt <= max_dt_s:
                dv = v - prev_v
                slews.append(abs(dv / dt))
                if abs(dv) >= threshold:
                    if dv > 0:
                        cpos += 1
                    else:
                        cneg += 1
        prev_ts, prev_v = ts_ms, v
    slew_avg = round(sum(slews) / len(slews), 3) if slews else 0.0
    slew_max = round(max(slews), 3) if slews else 0.0
    return cpos, cneg, slew_avg, slew_max


def detect_transients_in_window(rows: list, cfg: dict) -> dict:
    """Berechnet Transienten-Metriken je Phase aus nq_raw_fast-Zeilen.

    ``rows``: ``(ts_ms, u_l1, u_l2, u_l3, i_l1, i_l2, i_l3)`` aufsteigend.
    Returns ``{phase: {trans_u_pos, trans_u_neg, slew_u_avg, slew_u_max,
    trans_i_pos, trans_i_neg, slew_i_avg, slew_i_max, n}}``.
    """
    ef = cfg.get("event_filter", {})
    thr_v = ef.get("trans_threshold_v", 3.0)
    thr_a = ef.get("trans_threshold_a", 5.0)
    max_dt_s = ef.get("trans_dt_ms", 200) / 1000.0 * 1.5
    # Spaltenindex: ts_ms=0, u_l1=1, u_l2=2, u_l3=3, i_l1=4, i_l2=5, i_l3=6
    idx_u = {1: 1, 2: 2, 3: 3}
    idx_i = {1: 4, 2: 5, 3: 6}
    out: dict = {}
    for ph in _PHASES:
        u_series = [(r[0], r[idx_u[ph]]) for r in rows]
        i_series = [(r[0], abs(r[idx_i[ph]]) if r[idx_i[ph]] is not None else None)
                    for r in rows]
        u_pos, u_neg, su_avg, su_max = analyze_jumps(u_series, thr_v, max_dt_s)
        i_pos, i_neg, si_avg, si_max = analyze_jumps(i_series, thr_a, max_dt_s)
        out[ph] = {
            "trans_u_pos": u_pos, "trans_u_neg": u_neg,
            "slew_u_avg": su_avg, "slew_u_max": su_max,
            "trans_i_pos": i_pos, "trans_i_neg": i_neg,
            "slew_i_avg": si_avg, "slew_i_max": si_max,
            "n": len(rows),
        }
    return out


def compute_window(conn, cfg: dict, w0: int, w1: int) -> int:
    """Liest nq_raw_fast [w0,w1) (Sekunden), berechnet Transienten, upsertet."""
    rows = conn.execute(
        "SELECT ts_ms, u_l1, u_l2, u_l3, i_l1, i_l2, i_l3 FROM nq_raw_fast "
        "WHERE ts_ms >= ? AND ts_ms < ? ORDER BY ts_ms",
        (w0 * 1000, w1 * 1000),
    ).fetchall()
    if not rows:
        return 0
    metrics = detect_transients_in_window(rows, cfg)
    upsert = []
    for ph, m in metrics.items():
        upsert.append((w0, ph, m["trans_u_pos"], m["trans_u_neg"],
                       m["slew_u_avg"], m["slew_u_max"], m["trans_i_pos"],
                       m["trans_i_neg"], m["slew_i_avg"], m["slew_i_max"], m["n"]))
    conn.executemany(
        "INSERT OR REPLACE INTO nq_transient_5min "
        "(ts,phase,trans_u_pos,trans_u_neg,slew_u_avg,slew_u_max,"
        "trans_i_pos,trans_i_neg,slew_i_avg,slew_i_max,n) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)", upsert)
    conn.commit()
    return len(upsert)


def run_tech(db_path: str, cfg: dict, hours: float = 5.0) -> dict:
    """Berechnet 5-min-Transienten für die letzten ``hours`` Stunden (Tech)."""
    now = int(time.time())
    start = now - int(hours * 3600)
    w0 = start - (start % 300)
    conn = open_db(db_path, TECH_SCHEMA)
    windows = written = 0
    w = w0
    while w < now:
        written += compute_window(conn, cfg, w, w + 300)
        windows += 1
        w += 300
    conn.close()
    return {"windows": windows, "rows_written": written, "from": w0, "to": now}


def main() -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description="NQ Transienten-Erkennung (Tech)")
    ap.add_argument("--db", default=cfg.get("tmpfs", {}).get("db_path", "/dev/shm/nq_cache.db"))
    ap.add_argument("--hours", type=float, default=5.0)
    a = ap.parse_args()
    print(run_tech(a.db, cfg, a.hours))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
