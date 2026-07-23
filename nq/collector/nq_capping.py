"""nq.collector.nq_capping — Ring-Buffer/Kappung gegen tmpfs-Überlauf.

Verantwortung (siehe doc/netzqualitaet/NQ_MODUL.md §5):
- Zeit-Ring: DELETE nq_raw_* WHERE ts_ms < now-12h (retention.raw_hours; Event-markierte ausgenommen).
- Stale-Event-Kappung: event=1-Zeilen älter als event_stale_cap_s (Default 3600 s)
  werden ebenfalls gelöscht — verhindert unbegrenzte Akkumulation wenn kein Transfer
  quittiert (Sicherheitsnetz; Warnung auf stderr).
- Größen-Kappung: bei tmpfs > cap_mb älteste Nicht-Event-Zeilen blockweise löschen.
- wal_checkpoint(TRUNCATE) + optimize; Protokoll in nq_capping_log.
- Speicherwarnung auf stderr bei Annäherung an budget_mb oder wenig freiem tmpfs.
"""
from __future__ import annotations

import sys
import time

from nq.nq_common import db_size_mb, tmpfs_free_mb


def enforce_retention(conn, cfg: dict) -> None:
    now = int(time.time())
    ret_h = cfg.get("retention", {}).get("raw_hours", 12)
    cutoff_s = now - ret_h * 3600
    cutoff_ms = cutoff_s * 1000

    tmpfs_cfg = cfg.get("tmpfs", {})
    cap_mb = tmpfs_cfg.get("cap_mb", 1200)
    budget_mb = tmpfs_cfg.get("budget_mb", 1500)
    warn_free_mb = tmpfs_cfg.get("warn_free_mb", 200)

    ef = cfg.get("event_filter", {})
    stale_cap_s = ef.get("event_stale_cap_s", 3600)
    stale_cut_ms = (now - stale_cap_s) * 1000
    stale_cut_s = now - stale_cap_s

    deleted = 0
    # Zeit-Ring — Event-markierte RAW-Zeilen bleiben (bis Transfer quittiert)
    deleted += conn.execute(
        "DELETE FROM nq_raw_fast WHERE ts_ms < ? AND event=0", (cutoff_ms,)).rowcount
    # BUG FIX: war `ts < cutoff_s` — nq_raw_medium PK heißt ts_ms (Millisekunden)
    deleted += conn.execute(
        "DELETE FROM nq_raw_medium WHERE ts_ms < ? AND event=0", (cutoff_ms,)).rowcount
    deleted += conn.execute(
        "DELETE FROM nq_raw_slow WHERE ts < ? AND event=0", (cutoff_s,)).rowcount
    trigger = "time"

    # Stale-Event-Kappung: event=1-Zeilen ohne Transfer-Quittung nach stale_cap_s löschen.
    # Verhindert tmpfs-Überlauf wenn nq_event_transfer fehlt oder dauerhaft ausfällt.
    stale = 0
    stale += conn.execute(
        "DELETE FROM nq_raw_fast WHERE ts_ms < ? AND event=1", (stale_cut_ms,)).rowcount
    stale += conn.execute(
        "DELETE FROM nq_raw_medium WHERE ts_ms < ? AND event=1", (stale_cut_ms,)).rowcount
    stale += conn.execute(
        "DELETE FROM nq_raw_slow WHERE ts < ? AND event=1", (stale_cut_s,)).rowcount
    if stale:
        print(
            f"[nq_capping] WARNUNG: {stale} stale Event-Zeilen (>={stale_cap_s}s) "
            f"ohne Transfer-Quittung gelöscht — Transfer-Modul prüfen!",
            file=sys.stderr,
        )
        conn.execute(
            "INSERT INTO nq_capping_log (ts,trigger,table_name,rows_deleted,tmpfs_mb) "
            "VALUES (?,?,?,?,?)",
            (now, "stale_event", "nq_raw_*", stale, round(db_size_mb(conn), 2)),
        )
        conn.commit()

    # Größen-Kappung: älteste Nicht-Event-Fast-Zeilen blockweise löschen
    if db_size_mb(conn) > cap_mb:
        trigger = "size"
        for _ in range(200):  # Sicherung gegen Endlosschleife
            if db_size_mb(conn) <= cap_mb * 0.95:
                break
            n = conn.execute(
                "DELETE FROM nq_raw_fast WHERE ts_ms IN "
                "(SELECT ts_ms FROM nq_raw_fast WHERE event=0 ORDER BY ts_ms ASC LIMIT 5000)"
            ).rowcount
            deleted += n
            if n == 0:
                break

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("PRAGMA optimize")
    if deleted > 0:
        conn.execute(
            "INSERT INTO nq_capping_log (ts,trigger,table_name,rows_deleted,tmpfs_mb) "
            "VALUES (?,?,?,?,?)", (now, trigger, "nq_raw_*", deleted, round(db_size_mb(conn), 2)))
        conn.commit()

    # Speicherwarnung: zu nahe am Budget oder wenig freier Platz im tmpfs
    cur_mb = db_size_mb(conn)
    if cur_mb > budget_mb * 0.8:
        print(
            f"[nq_capping] WARNUNG: tmpfs-DB {cur_mb:.0f} MB > 80 % Budget ({budget_mb} MB)!",
            file=sys.stderr,
        )
    try:
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]
        free = tmpfs_free_mb(db_path)
        if free < warn_free_mb:
            print(
                f"[nq_capping] WARNUNG: tmpfs freier Speicher {free:.0f} MB < {warn_free_mb} MB!",
                file=sys.stderr,
            )
    except Exception:
        pass
