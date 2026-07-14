"""nq.transfer.nq_agg_transfer — 4-stündlicher Transfer Tech tmpfs → Primary SD (Rolle N).

Überträgt alle 4h:
- ``nq_agg_10s`` (Skalare, 10-s-Buckets) — Fenster letzte 5 h (at-least-once)
- ``nq_raw_slow`` (Harmonische, 1-s-RAW) — gleiches Zeitfenster

Löscht auf Tech erst nach Primary-Quittung (at-least-once). INSERT OR REPLACE
auf Primary → idempotent bei Wiederholung.
Retention-Enforcement auf Primary nach jedem Lauf.
Protokoll: nq_ingest_log auf Primary.

Start:  python3 -m nq.transfer.nq_agg_transfer [--hours N]
Timer:  pv-nq-agg-transfer.timer (alle 4 h, Persistent=yes)
Doku:   doc/netzqualitaet/NQ_MODUL.md §6.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

from nq.nq_common import load_config, open_db, PRIMARY_SCHEMA, BASE_DIR

_WINDOW_H = 5     # Übernahme-Fenster in Stunden (>4 h → at-least-once bei 4-h-Timer)


def _tech_host(cfg: dict) -> str:
    host = os.environ.get("PV_TECH_IP")
    if not host:
        try:
            import config
            host = getattr(config, "NQ_TECH_IP", None)
        except Exception:
            host = None
    return (host
            or cfg.get("transfer", {}).get("tech_host")
            or "192.0.2.181")


def _primary_db(ts: int) -> str:
    import time as _t
    month = _t.strftime("%Y-%m", _t.localtime(ts))
    return os.path.join(BASE_DIR, "nq", "db", f"nq_{month}.db")


def _window_bounds(hours: float = _WINDOW_H) -> tuple[int, int]:
    """Zeitfenster [now - hours*3600, now) in Unix-Sekunden."""
    t1 = int(time.time())
    t0 = t1 - int(hours * 3600)
    return t0, t1


# ---------------------------------------------------------------------------
# Fetch / Delete Hilfsfunktionen
# ---------------------------------------------------------------------------

def _ssh_fetch(host: str, tmpfs_db: str, query: str, params: tuple, timeout: int = 90) -> list:
    """Führt eine SELECT-Query auf der Tech-tmpfs-DB via SSH aus und gibt Zeilen zurück."""
    params_json = json.dumps(list(params))
    remote = (
        "import sqlite3,json;"
        f"c=sqlite3.connect('file:{tmpfs_db}?mode=ro',uri=True);"
        f"print(json.dumps(c.execute({query!r},{params_json}).fetchall()))"
    )
    remote_dir = os.environ.get("PV_REPO_DIR", BASE_DIR)
    out = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
         f"admin@{host}",
         "cd %s && python3 -c \"%s\"" % (remote_dir, remote)],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"Tech-Fetch fehlgeschlagen: {out.stderr.strip()[:200]}")
    raw = out.stdout.strip()
    return [tuple(r) for r in json.loads(raw)] if raw else []


def _ssh_delete(host: str, tmpfs_db: str, table: str, t0: int, t1: int) -> int:
    """Löscht Zeilen [t0, t1) in `table` auf Tech — erst nach Primary-Quittung aufrufen."""
    remote = (
        "import sqlite3;"
        f"c=sqlite3.connect('{tmpfs_db}');"
        f"r=c.execute('DELETE FROM {table} WHERE ts>={t0} AND ts<{t1}');"
        "c.commit();print(r.rowcount)"
    )
    remote_dir = os.environ.get("PV_REPO_DIR", BASE_DIR)
    out = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes",
         f"admin@{host}",
         "cd %s && python3 -c \"%s\"" % (remote_dir, remote)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"Tech-Delete ({table}) fehlgeschlagen: {out.stderr.strip()[:200]}")
    return int(out.stdout.strip() or "0")


def _ssh_compute_transients(host: str, hours: float) -> None:
    """Best-effort: löst die 5-min-Transienten-Berechnung auf Tech aus (nq_raw_fast
    lebt nur dort). Fehler werden nur geloggt, blockieren den Transfer nicht."""
    remote_dir = os.environ.get("PV_REPO_DIR", BASE_DIR)
    subprocess.run(
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", f"admin@{host}",
         "cd %s && python3 -m nq.aggregate.nq_transients --hours %s" % (remote_dir, hours)],
        capture_output=True, text=True, timeout=120, check=False,
    )


def _enforce_retention(conn, cfg: dict) -> None:
    ret = cfg.get("retention", {})
    hours = ret.get("primary_agg10s_hours", 72)
    cutoff = int(time.time()) - hours * 3600
    conn.execute("DELETE FROM nq_agg_10s WHERE ts < ?", (cutoff,))
    # nq_raw_slow (1-s-Harmonik-RAW) auf Primary nur kurz halten (SD-Schonung);
    # nach der 5-min-Aggregation nicht mehr nötig. Fenster > Aggregationszyklus.
    slow_h = ret.get("primary_rawslow_hours", 12)
    conn.execute("DELETE FROM nq_raw_slow WHERE ts < ?",
                 (int(time.time()) - slow_h * 3600,))
    conn.commit()


# ---------------------------------------------------------------------------
# Transfer
# ---------------------------------------------------------------------------

def transfer(hours: float = _WINDOW_H) -> dict:
    """Überträgt nq_agg_10s + nq_raw_slow der letzten `hours` Stunden Tech → Primary."""
    t_start = time.time()
    cfg = load_config()
    host = _tech_host(cfg)
    t0, t1 = _window_bounds(hours)
    db_path = _primary_db(t0)

    # --- nq_agg_10s (Skalare) ---
    agg_rows = _ssh_fetch(
        host, cfg["tmpfs"]["db_path"],
        "SELECT ts,quantity,meas,phase,ord,vmin,vavg,vmax,n FROM nq_agg_10s "
        "WHERE ts>=? AND ts<? ORDER BY ts",
        (t0, t1),
    )

    # --- nq_raw_slow (Harmonische) ---
    harm_rows = _ssh_fetch(
        host, cfg["tmpfs"]["db_path"],
        "SELECT ts,meas,phase,ord,value,event FROM nq_raw_slow "
        "WHERE ts>=? AND ts<? ORDER BY ts",
        (t0, t1),
        timeout=120,   # 5h × 144 rows/s → ~2.6M rows, kann etwas dauern
    )

    # --- nq_transient_5min (NQ2 WP2): erst auf Tech berechnen, dann übernehmen ---
    try:
        _ssh_compute_transients(host, hours)
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[nq_agg_transfer] Transienten-Berechnung (Tech) übersprungen: {exc}")
    trans_rows = _ssh_fetch(
        host, cfg["tmpfs"]["db_path"],
        "SELECT ts,phase,trans_u_pos,trans_u_neg,slew_u_avg,slew_u_max,"
        "trans_i_pos,trans_i_neg,slew_i_avg,slew_i_max,n FROM nq_transient_5min "
        "WHERE ts>=? AND ts<? ORDER BY ts",
        (t0, t1),
    )

    if not agg_rows and not harm_rows and not trans_rows:
        return {"t0": t0, "t1": t1, "agg_written": 0, "harm_written": 0,
                "trans_written": 0, "reason": "keine Tech-Daten im Fenster"}

    conn = open_db(db_path, PRIMARY_SCHEMA)

    if agg_rows:
        conn.executemany(
            "INSERT OR REPLACE INTO nq_agg_10s "
            "(ts,quantity,meas,phase,ord,vmin,vavg,vmax,n) VALUES (?,?,?,?,?,?,?,?,?)",
            agg_rows,
        )
        conn.commit()
        _ssh_delete(host, cfg["tmpfs"]["db_path"], "nq_agg_10s", t0, t1)

    if harm_rows:
        conn.executemany(
            "INSERT OR REPLACE INTO nq_raw_slow "
            "(ts,meas,phase,ord,value,event) VALUES (?,?,?,?,?,?)",
            harm_rows,
        )
        conn.commit()
        _ssh_delete(host, cfg["tmpfs"]["db_path"], "nq_raw_slow", t0, t1)

    if trans_rows:
        conn.executemany(
            "INSERT OR REPLACE INTO nq_transient_5min "
            "(ts,phase,trans_u_pos,trans_u_neg,slew_u_avg,slew_u_max,"
            "trans_i_pos,trans_i_neg,slew_i_avg,slew_i_max,n) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            trans_rows,
        )
        conn.commit()
        _ssh_delete(host, cfg["tmpfs"]["db_path"], "nq_transient_5min", t0, t1)

    _enforce_retention(conn, cfg)

    duration = time.time() - t_start
    conn.execute(
        "INSERT INTO nq_ingest_log (ts, date_covered, agg_rows, event_rows, duration_s) "
        "VALUES (?,?,?,?,?)",
        (int(time.time()),
         time.strftime("%Y-%m-%dT%H:%M", time.localtime(t0)),
         len(agg_rows), len(harm_rows), round(duration, 2)),
    )
    conn.commit()
    conn.close()
    return {"t0": t0, "t1": t1, "agg_written": len(agg_rows),
            "harm_written": len(harm_rows), "trans_written": len(trans_rows),
            "duration_s": round(duration, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Transfer nq_agg_10s + nq_raw_slow Tech → Primary (Rolle N)")
    ap.add_argument("--hours", type=float, default=_WINDOW_H,
                    help=f"Übernahme-Fenster in Stunden (Default: {_WINDOW_H})")
    a = ap.parse_args()
    result = transfer(a.hours)
    print(f"[nq_agg_transfer] {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
