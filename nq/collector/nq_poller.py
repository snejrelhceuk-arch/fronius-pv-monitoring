"""nq.collector.nq_poller — Fast/Medium-Poller für PAC4200 (Rolle N, Tech).

Liest den PAC4200 in dichtem Takt (read-only, via ``pac_live.read_snapshot`` —
kein separater Block-Reader nötig) und schreibt:
- ``nq_raw_fast`` / ``nq_raw_medium`` — hochauflösende RAW-Werte (72 h Ring),
- ``nq_agg_10s`` — min/avg/max je Größe im 10-s-Raster (Charting-/Transfer-Basis),
- Event-Vorfilter: markiert Transienten (``event=1``) für dauerhafte Schnipsel.

Härtung: WAL + busy_timeout, tolerant gegen Modbus-Ausfälle, Kappung gegen
tmpfs-Überlauf (``nq_capping.enforce_retention``). Kein Schreibpfad zum Gerät.

Start (Tech):  python3 -m nq.collector.nq_poller
Doku: doc/netzqualitaet/NQ_TESTS_UND_DB.md, doc/netzqualitaet/NQ_MODUL.md §4/§5.
"""
from __future__ import annotations

import argparse
import signal
import time

from nq.nq_common import open_db, load_config, TECH_SCHEMA
from nq.pac_live import read_snapshot
from nq.collector.nq_capping import enforce_retention

# Charting-/Analyse-Größen (Skalare) — Name = nq_agg_10s.quantity.
# Ströme vorzeichenbehaftet (Is_*, Zweirichtungszähler).
AGG_QUANTITIES = [
    "U_L1N", "U_L2N", "U_L3N", "U_L12", "U_L23", "U_L31",
    "Is_L1", "Is_L2", "Is_L3", "I_N",
    "P_L1", "P_L2", "P_L3", "P_tot", "Q_tot", "S_tot",
    "PF_L1", "PF_L2", "PF_L3", "PF_tot",
    "cosphi_L1", "cosphi_L2", "cosphi_L3",
    "THDu_L1", "THDu_L2", "THDu_L3", "THDi_L1", "THDi_L2", "THDi_L3",
    "THDu_L12", "THDu_L23", "THDu_L31",
    "FREQ", "Unbal_U", "Unbal_I",
]

# Fast-RAW-Spalten (nq_raw_fast) -> Snapshot-Key
_FAST_COLS = {
    "u_l1": "U_L1N", "u_l2": "U_L2N", "u_l3": "U_L3N",
    "u_l12": "U_L12", "u_l23": "U_L23", "u_l31": "U_L31",
    "i_l1": "Is_L1", "i_l2": "Is_L2", "i_l3": "Is_L3",
    "p_tot": "P_tot", "q_tot": "Q_tot", "s_tot": "S_tot",
    "pf": "PF_tot", "f": "FREQ",
}
# Medium-RAW-Spalten (nq_raw_medium) -> Snapshot-Key
_MED_COLS = {
    "thd_u_l1": "THDu_L1", "thd_u_l2": "THDu_L2", "thd_u_l3": "THDu_L3",
    "thd_i_l1": "THDi_L1", "thd_i_l2": "THDi_L2", "thd_i_l3": "THDi_L3",
    "unbalance_u": "Unbal_U", "unbalance_i": "Unbal_I",
}

_STOP = False


def _handle_stop(_sig, _frm):
    global _STOP
    _STOP = True


class _Bucket:
    """min/avg/max-Akkumulator für ein 10-s-Raster je Größe."""

    def __init__(self):
        self.acc: dict[str, list] = {}   # name -> [min, sum, max, n]

    def add(self, vals: dict):
        for q in AGG_QUANTITIES:
            v = vals.get(q)
            if v is None:
                continue
            a = self.acc.get(q)
            if a is None:
                self.acc[q] = [v, v, v, 1]
            else:
                if v < a[0]:
                    a[0] = v
                a[1] += v
                if v > a[2]:
                    a[2] = v
                a[3] += 1

    def rows(self, ts_bucket: int):
        # Skalare: meas='', phase=0, ord=0 (PK-Spalten in WITHOUT-ROWID dürfen
        # nicht NULL sein). Harmonische späterer Ausbau: meas='U'/'I', phase, ord.
        return [(ts_bucket, q, "", 0, 0, vmin, vsum / n, vmax, n)
                for q, (vmin, vsum, vmax, n) in self.acc.items()]


def _detect_event(prev: dict, cur: dict, ef: dict) -> str | None:
    """Transienten-Trigger (Δu, Δf, THD-U, Δi). Returns Trigger-Name oder None."""
    if not prev:
        return None
    du = ef.get("du_step_v", 3.0)
    df = ef.get("df_step_hz", 0.02)
    thd = ef.get("thd_u_pct", 5.0)
    di = ef.get("di_step_a", 5.0)
    for ph in ("U_L1N", "U_L2N", "U_L3N"):
        if prev.get(ph) is not None and cur.get(ph) is not None \
                and abs(cur[ph] - prev[ph]) >= du:
            return "du_step"
    if prev.get("FREQ") is not None and cur.get("FREQ") is not None \
            and abs(cur["FREQ"] - prev["FREQ"]) >= df:
        return "df_step"
    for q in ("THDu_L1", "THDu_L2", "THDu_L3"):
        if cur.get(q) is not None and cur[q] >= thd:
            return "thd_u"
    for q in ("Is_L1", "Is_L2", "Is_L3"):
        if prev.get(q) is not None and cur.get(q) is not None \
                and abs(cur[q] - prev[q]) >= di:
            return "di_step"
    return None


def poller_loop(db_path: str, cfg: dict) -> None:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    conn = open_db(db_path, TECH_SCHEMA)

    poll_s = max(cfg.get("polling", {}).get("fast_ms", 500) / 1000.0, 0.25)
    grid_s = cfg.get("aggregate", {}).get("grid_s", 10)
    ef = cfg.get("event_filter", {})
    cooldown_s = ef.get("cooldown_s", 120)
    cap_every_s = 60

    bucket = _Bucket()
    cur_bucket = None
    fast_buf: list = []
    med_buf: list = []
    prev_vals: dict = {}
    last_event_ts = 0.0
    last_cap = time.time()
    polls = errors = events = 0

    fast_sql = ("INSERT OR REPLACE INTO nq_raw_fast (ts_ms,%s,event) VALUES (%s)"
                % (",".join(_FAST_COLS), ",".join(["?"] * (len(_FAST_COLS) + 2))))
    med_sql = ("INSERT OR REPLACE INTO nq_raw_medium (ts,%s,event) VALUES (%s)"
               % (",".join(_MED_COLS), ",".join(["?"] * (len(_MED_COLS) + 2))))

    print(f"[nq_poller] db={db_path} poll={poll_s:.2f}s grid={grid_s}s (read-only PAC)")
    while not _STOP:
        t0 = time.time()
        try:
            snap = read_snapshot(timeout=2.0)
            if snap.get("ok"):
                polls += 1
                v = snap["values"]
                now = snap["ts"]
                ts_ms = int(t0 * 1000)

                ev = 0
                trig = _detect_event(prev_vals, v, ef)
                if trig and (t0 - last_event_ts) >= cooldown_s:
                    ev = 1
                    events += 1
                    last_event_ts = t0
                prev_vals = v

                b = now - (now % grid_s)
                if cur_bucket is None:
                    cur_bucket = b
                elif b != cur_bucket:
                    conn.executemany(
                        "INSERT OR REPLACE INTO nq_agg_10s "
                        "(ts,quantity,meas,phase,ord,vmin,vavg,vmax,n) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", bucket.rows(cur_bucket))
                    conn.commit()
                    bucket = _Bucket()
                    cur_bucket = b
                bucket.add(v)

                fast_buf.append([ts_ms] + [v.get(k) for k in _FAST_COLS.values()] + [ev])
                med_buf.append([now] + [v.get(k) for k in _MED_COLS.values()] + [ev])
            else:
                errors += 1
        except Exception as e:  # tolerant: nie crashen
            errors += 1
            print(f"[nq_poller] Fehler: {e}")

        if len(fast_buf) >= 8:
            conn.executemany(fast_sql, fast_buf)
            conn.executemany(med_sql, med_buf)
            conn.commit()
            fast_buf.clear()
            med_buf.clear()

        if (time.time() - last_cap) >= cap_every_s:
            try:
                enforce_retention(conn, cfg)
            except Exception as e:
                print(f"[nq_poller] Kappung-Fehler: {e}")
            last_cap = time.time()

        sleep = poll_s - (time.time() - t0)
        while sleep > 0 and not _STOP:
            time.sleep(min(0.2, sleep))
            sleep -= 0.2

    # Final-Flush: restliche Puffer + laufender Bucket nicht verlieren
    try:
        if fast_buf:
            conn.executemany(fast_sql, fast_buf)
            conn.executemany(med_sql, med_buf)
        if cur_bucket is not None and bucket.acc:
            conn.executemany(
                "INSERT OR REPLACE INTO nq_agg_10s "
                "(ts,quantity,meas,phase,ord,vmin,vavg,vmax,n) VALUES (?,?,?,?,?,?,?,?,?)",
                bucket.rows(cur_bucket))
        conn.commit()
    except Exception as e:
        print(f"[nq_poller] Final-Flush-Fehler: {e}")
    conn.close()
    print(f"[nq_poller] Ende. polls={polls} errors={errors} events={events}")


def main() -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    cfg = load_config()
    ap = argparse.ArgumentParser(description="NQ Fast/Medium-Poller (Tech)")
    ap.add_argument("--db", default=cfg.get("tmpfs", {}).get("db_path", "/dev/shm/nq_cache.db"))
    a = ap.parse_args()
    poller_loop(a.db, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
