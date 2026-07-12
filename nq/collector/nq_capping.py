"""nq.collector.nq_capping — Ring-Buffer/Kappung gegen tmpfs-Überlauf.

Verantwortung (siehe doc/netzqualitaet/NQ_MODUL.md §5):
- Zeit-Ring: DELETE nq_raw_* WHERE ts < now-72h (Event-markierte ausgenommen).
- Größen-Kappung: bei tmpfs > cap_mb älteste Nicht-Event-Zeilen blockweise löschen.
- wal_checkpoint(TRUNCATE) + optimize; Protokoll in nq_capping_log.
"""
from __future__ import annotations

import time

from nq.nq_common import db_size_mb


def enforce_retention(conn, cfg: dict) -> None:
    now = int(time.time())
    ret_h = cfg.get("retention", {}).get("raw_hours", 72)
    cutoff_s = now - ret_h * 3600
    cutoff_ms = cutoff_s * 1000
    agg_cut = now - cfg.get("retention", {}).get("primary_agg10s_hours", 72) * 3600

    deleted = 0
    # Zeit-Ring — Event-markierte RAW-Zeilen bleiben (bis Transfer quittiert)
    deleted += conn.execute(
        "DELETE FROM nq_raw_fast WHERE ts_ms < ? AND event=0", (cutoff_ms,)).rowcount
    deleted += conn.execute(
        "DELETE FROM nq_raw_medium WHERE ts < ? AND event=0", (cutoff_s,)).rowcount
    deleted += conn.execute(
        "DELETE FROM nq_raw_slow WHERE ts < ? AND event=0", (cutoff_s,)).rowcount
    deleted += conn.execute(
        "DELETE FROM nq_agg_10s WHERE ts < ?", (agg_cut,)).rowcount
    trigger = "time"

    # Größen-Kappung: älteste Nicht-Event-Fast-Zeilen blockweise löschen
    cap_mb = cfg.get("tmpfs", {}).get("cap_mb", 1200)
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
