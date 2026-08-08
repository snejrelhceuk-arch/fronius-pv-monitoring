"""nq.collector.nq_energy — Energiezähler-Erfassung mit Differenzmethode (Rolle N).

Liest die kumulativen PAC4200-Energiezähler (read-only, via ``pac_live``) in
langsamem Takt und legt sie als Snapshots ab (``nq_energy_raw``). Aus den
Snapshots werden per **Differenzmethode** Tages-Deltas berechnet
(``compute_daily``) — konsistent zur Produktion (``aggregate_daily`` /
``_counter_or_fallback``): ``delta = end - start`` mit Reset-Erkennung.

Härtung: WAL + busy_timeout, tolerant gegen Modbus-Ausfälle, idempotent
(``INSERT OR REPLACE``), Schema idempotent. Kein Schreibpfad zum Gerät oder in
``data.db``.

Start (Tech, Snapshotter):  python3 -m nq.collector.nq_energy --db /dev/shm/nq_cache.db --interval-s 60
Siehe doc/netzqualitaet/NQ_TESTS_UND_DB.md §4/§5.
"""
from __future__ import annotations

import argparse
import signal
import time

from nq.nq_common import open_db, load_config, TECH_SCHEMA
from nq.pac_live import read_snapshot

# Zähler-Reihenfolge = Spalten in nq_energy_raw
COUNTERS = ["wh_imp", "wh_exp", "varh_imp", "varh_exp", "vah"]
# PAC-Snapshot-Keys -> DB-Spalten
_SNAP_KEYS = {
    "wh_imp": "Wh_imp", "wh_exp": "Wh_exp",
    "varh_imp": "varh_imp", "varh_exp": "varh_exp", "vah": "VAh",
}

# Reset-Erkennung (Wh) — Muster aus aggregate_daily._counter_or_fallback
_MIN_DELTA = 1.0        # Wh: darunter kein signifikanter Unterschied
_RESET_FACTOR = 3.0     # end-start > RESET_FACTOR * Σ(teil-deltas) -> Sprung

_STOP = False


def _handle_stop(_sig, _frm):
    global _STOP
    _STOP = True


def append_snapshot(conn, snap: dict | None = None,
                    host: str | None = None) -> bool:
    """Liest (falls ``snap`` None) einen PAC-Snapshot und schreibt die
    kumulativen Energiezähler nach ``nq_energy_raw``. Gibt True bei Erfolg."""
    if snap is None:
        snap = read_snapshot(host=host)
    if not snap.get("ok"):
        return False
    v = snap["values"]
    row = [snap["ts"]] + [v.get(_SNAP_KEYS[c]) for c in COUNTERS]
    conn.execute(
        "INSERT OR REPLACE INTO nq_energy_raw "
        "(ts, wh_imp, wh_exp, varh_imp, varh_exp, vah) VALUES (?,?,?,?,?,?)",
        row,
    )
    conn.commit()
    return True


def _reset_aware_delta(start, end, sum_partial):
    """Delta mit Reset-Erkennung. Returns (delta, src).

    src: 'counter' | 'reset_fallback' | 'partial'. Gespiegelt aus der
    Produktions-Logik ``_counter_or_fallback``.
    """
    if start is None or end is None:
        return (sum_partial if sum_partial is not None else 0.0, "partial")
    diff = end - start
    if diff < -_MIN_DELTA:
        return (sum_partial if sum_partial is not None else 0.0, "reset_fallback")
    if sum_partial is not None and sum_partial > _MIN_DELTA \
            and diff > _RESET_FACTOR * sum_partial:
        return (sum_partial, "reset_fallback")
    return (diff, "counter")


def compute_daily(rows: list[tuple]) -> dict | None:
    """Berechnet Tages-Start/End/Delta je Zähler aus sortierten Snapshots.

    ``rows``: Liste ``(ts, wh_imp, wh_exp, varh_imp, varh_exp, vah)`` eines Tages,
    aufsteigend nach ts. Reine Funktion (testbar), kein DB-Zugriff.
    Returns dict mit ``<c>_start/_end/_delta`` je Zähler + ``src`` + ``n_samples``.
    """
    if not rows:
        return None
    out: dict = {"n_samples": len(rows)}
    src_overall = "counter"
    for idx, c in enumerate(COUNTERS, start=1):
        vals = [(r[0], r[idx]) for r in rows if r[idx] is not None]
        if not vals:
            out[f"{c}_start"] = out[f"{c}_end"] = out[f"{c}_delta"] = None
            src_overall = "partial"
            continue
        start = vals[0][1]
        end = vals[-1][1]
        # Σ positiver Teil-Deltas als Reset-Referenz
        sum_partial = 0.0
        for i in range(1, len(vals)):
            d = vals[i][1] - vals[i - 1][1]
            if d > 0:
                sum_partial += d
        delta, src = _reset_aware_delta(start, end, sum_partial)
        out[f"{c}_start"] = start
        out[f"{c}_end"] = end
        out[f"{c}_delta"] = delta
        if src != "counter":
            src_overall = src
    out["src"] = src_overall
    return out


def _interp_at(samples: list[tuple], boundary_ts: int, max_gap_s: float):
    """Kumulativen Zählerstand am ``boundary_ts`` aus (ts, val)-Stützstellen schätzen.

    ``samples``: aufsteigend sortierte Liste ``(ts, val)`` mit ``val`` != None.
    Returns ``(value|None, quality)`` — ``quality`` ∈ {'interp' (bracketiert,
    linear), 'edge' (nur eine Seite bzw. Bracket zu breit → nächster Randwert),
    'none' (keine Stützstelle im Toleranzfenster)}.

    Energieerhaltend: Der Wert an einer Grenze hängt nur von den umgebenden
    Stützstellen + Regel ab → Tagesende(D) == Tagesanfang(D+1).
    """
    before = after = None
    for ts, val in samples:
        if ts <= boundary_ts:
            before = (ts, val)
        else:
            after = (ts, val)
            break
    if before and after:
        (tb, vb), (ta, va) = before, after
        if ta > tb and (ta - tb) <= max_gap_s:
            frac = (boundary_ts - tb) / (ta - tb)
            return (vb + (va - vb) * frac, "interp")
        near = before if (boundary_ts - tb) <= (ta - boundary_ts) else after
        return (near[1], "edge") if abs(near[0] - boundary_ts) <= max_gap_s else (None, "none")
    cand = before or after
    if cand and abs(cand[0] - boundary_ts) <= max_gap_s:
        return (cand[1], "edge")
    return (None, "none")


def compute_daily_boundary(rows: list[tuple], t0: int, t1: int,
                           max_gap_s: float = 1800.0,
                           min_samples_ok: int = 200) -> dict | None:
    """Tages-Delta per **Randwert-Interpolation** auf die exakten Mitternachts-
    grenzen ``t0`` (Tagesanfang) und ``t1`` (Tagesende = nächste Mitternacht).

    Behebt den Verlust der Differenzmethode ``compute_daily`` (delta =
    letzter − erster Snapshot **innerhalb** des Tages), die die Energie in der
    Lücke zwischen letztem Snapshot eines Tages und erstem des Folgetages
    verliert — bei dünnem 5-min-Takt (und erst recht bei Collector-Ausfall)
    systematisch. Der interpolierte Grenzwert ist für aufeinanderfolgende Tage
    identisch → **energieerhaltend** (Monats-/Jahressumme = Zählerfortschritt).

    ``rows``: ``(ts, wh_imp, wh_exp, varh_imp, varh_exp, vah)`` aufsteigend, darf
    (und soll) über ``[t0, t1)`` hinausreichen (Rand-Bracketing). Reine Funktion.
    """
    if not rows:
        return None
    n_in_day = sum(1 for r in rows if t0 <= r[0] < t1)
    out: dict = {"n_samples": n_in_day}
    src_overall = "counter"
    qual = []
    for idx, c in enumerate(COUNTERS, start=1):
        samples = [(r[0], r[idx]) for r in rows if r[idx] is not None]
        in_day = [(ts, v) for ts, v in samples if t0 <= ts < t1]
        sum_partial = 0.0
        for i in range(1, len(in_day)):
            d = in_day[i][1] - in_day[i - 1][1]
            if d > 0:
                sum_partial += d
        if not samples:
            out[f"{c}_start"] = out[f"{c}_end"] = out[f"{c}_delta"] = None
            src_overall = "partial"
            qual.append("none")
            continue
        v0, q0 = _interp_at(samples, t0, max_gap_s)
        v1, q1 = _interp_at(samples, t1, max_gap_s)
        if v0 is None or v1 is None:
            # kein sauberer Rand → within-day-Fallback (wie compute_daily), markiert partial
            s = in_day[0][1] if in_day else None
            e = in_day[-1][1] if in_day else None
            delta, _ = _reset_aware_delta(s, e, sum_partial if sum_partial > 0 else None)
            out[f"{c}_start"], out[f"{c}_end"], out[f"{c}_delta"] = s, e, delta
            src_overall = "partial"
            qual.append("none")
            continue
        delta, src = _reset_aware_delta(v0, v1, sum_partial if sum_partial > 0 else None)
        out[f"{c}_start"], out[f"{c}_end"], out[f"{c}_delta"] = v0, v1, delta
        if src != "counter":
            src_overall = src if src_overall == "counter" else src_overall
            qual.append("reset")
        elif q0 == "interp" and q1 == "interp":
            qual.append("interp")
        else:
            qual.append("edge")
            if src_overall == "counter":
                src_overall = "counter_edge"
    # Konfidenz: sauber nur bei durchgehender Interpolation + genügend Tagesdeckung
    clean = all(q == "interp" for q in qual) and n_in_day >= min_samples_ok
    out["quality"] = "clean" if clean else ("estimated" if any(q in ("interp", "edge") for q in qual) else "none")
    out["src"] = src_overall
    return out


def run(db_path: str, interval_s: float, host: str | None = None) -> None:
    """Snapshotter-Loop (Tech): schreibt Energiezähler in langsamem Takt."""
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    conn = open_db(db_path, TECH_SCHEMA)
    ok = err = 0
    print(f"[nq_energy] db={db_path} interval={interval_s:.0f}s (read-only PAC)")
    while not _STOP:
        t0 = time.time()
        try:
            if append_snapshot(conn, host=host):
                ok += 1
            else:
                err += 1
        except Exception as e:  # tolerant: nie crashen
            err += 1
            print(f"[nq_energy] Fehler: {e}")
        sleep = interval_s - (time.time() - t0)
        # feingranular schlafen, damit SIGTERM schnell greift
        while sleep > 0 and not _STOP:
            time.sleep(min(1.0, sleep))
            sleep -= 1.0
    conn.close()
    print(f"[nq_energy] Ende. ok={ok} err={err}")


def main() -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    cfg = load_config()
    ap = argparse.ArgumentParser(description="NQ Energie-Snapshotter (Differenzmethode)")
    ap.add_argument("--db", default=cfg.get("tmpfs", {}).get("db_path", "/dev/shm/nq_cache.db"))
    ap.add_argument("--interval-s", type=float,
                    default=cfg.get("polling", {}).get("energy_s", 60))
    ap.add_argument("--host", default=None)
    a = ap.parse_args()
    run(a.db, a.interval_s, a.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
