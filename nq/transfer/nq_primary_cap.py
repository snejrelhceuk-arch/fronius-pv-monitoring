"""nq.transfer.nq_primary_cap — Retention-Enforcement für Event-Snippets auf Primary.

Verhindert unbegrenztes Wachstum der nq_event_fast/medium/slow-Tabellen in den
Monats-DBs auf Primary (nq/db/nq_YYYY-MM.db).

Strategie:
- Altersgrenze: Events (nq_events.ts_end) älter als ``event_keep_days`` werden
  gelöscht, samt kaskadierendem Snippet-Inhalt in nq_event_fast/medium/slow.
- Zählgrenze: Wenn nach Alters-Kappung noch mehr als ``event_max_count`` Events
  pro Monats-DB vorhanden sind, werden älteste Events bis zur Grenze gelöscht.
- Betrifft nur ``nq/db/nq_YYYY-MM.db``-Dateien; kein Zugriff auf ``data.db``.

Aufruf:
  python3 -m nq.transfer.nq_primary_cap [--db nq/db/nq_YYYY-MM.db]
  Ohne --db: alle nq_YYYY-MM.db in BASE_DIR/nq/db/ bearbeiten.
  Als Cron/Timer: nach nq_ingest_primary oder täglich.

Konfiguration (config/nq_config.json, Block "retention"):
  event_keep_days   — Maximales Alter eines Events in Tagen (Default 90)
  event_max_count   — Maximale Anzahl Events pro Monats-DB (Default 5000)
"""
from __future__ import annotations

import argparse
import glob
import os
import time

from nq.nq_common import load_config, open_db, BASE_DIR, PRIMARY_SCHEMA


def _cap_db(db_path: str, keep_days: int, max_count: int) -> dict:
    """Kappung einer einzelnen Monats-DB. Gibt Statistik-Dict zurück."""
    if not os.path.exists(db_path):
        return {"db": db_path, "skipped": True}

    conn = open_db(db_path, PRIMARY_SCHEMA)
    now = int(time.time())
    cutoff = now - keep_days * 86400
    stats = {"db": db_path, "age_deleted": 0, "count_deleted": 0, "events_remaining": 0}

    # 1. Alters-Kappung: Events deren Snippet-Ende älter als cutoff ist
    old_ids = [
        r[0] for r in conn.execute(
            "SELECT event_id FROM nq_events WHERE ts_end < ?", (cutoff,)
        ).fetchall()
    ]
    if old_ids:
        placeholders = ",".join("?" * len(old_ids))
        conn.execute(f"DELETE FROM nq_event_fast WHERE event_id IN ({placeholders})", old_ids)
        conn.execute(f"DELETE FROM nq_event_medium WHERE event_id IN ({placeholders})", old_ids)
        conn.execute(f"DELETE FROM nq_event_slow WHERE event_id IN ({placeholders})", old_ids)
        conn.execute(f"DELETE FROM nq_events WHERE event_id IN ({placeholders})", old_ids)
        stats["age_deleted"] = len(old_ids)

    # 2. Zählgrenze: älteste Events löschen bis max_count erreicht
    total = conn.execute("SELECT COUNT(*) FROM nq_events").fetchone()[0]
    if total > max_count:
        overflow = total - max_count
        excess_ids = [
            r[0] for r in conn.execute(
                "SELECT event_id FROM nq_events ORDER BY ts_start ASC LIMIT ?", (overflow,)
            ).fetchall()
        ]
        if excess_ids:
            placeholders = ",".join("?" * len(excess_ids))
            conn.execute(f"DELETE FROM nq_event_fast WHERE event_id IN ({placeholders})", excess_ids)
            conn.execute(f"DELETE FROM nq_event_medium WHERE event_id IN ({placeholders})", excess_ids)
            conn.execute(f"DELETE FROM nq_event_slow WHERE event_id IN ({placeholders})", excess_ids)
            conn.execute(f"DELETE FROM nq_events WHERE event_id IN ({placeholders})", excess_ids)
            stats["count_deleted"] = len(excess_ids)

    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    stats["events_remaining"] = conn.execute("SELECT COUNT(*) FROM nq_events").fetchone()[0]
    conn.close()
    return stats


def run_cap(db_path: str | None = None) -> list[dict]:
    """Kappung aller Monats-DBs oder einer einzelnen DB. Gibt Liste von Statistiken zurück."""
    cfg = load_config()
    retention = cfg.get("retention", {})
    keep_days = retention.get("event_keep_days", 90)
    max_count = retention.get("event_max_count", 5000)

    if db_path:
        paths = [db_path]
    else:
        pattern = os.path.join(BASE_DIR, "nq", "db", "nq_????-??.db")
        paths = sorted(glob.glob(pattern))

    results = []
    for p in paths:
        try:
            st = _cap_db(p, keep_days, max_count)
        except Exception as exc:
            st = {"db": p, "error": str(exc)}
        results.append(st)
        if st.get("age_deleted") or st.get("count_deleted"):
            print(f"[nq_primary_cap] {os.path.basename(p)}: "
                  f"age_deleted={st.get('age_deleted', 0)} "
                  f"count_deleted={st.get('count_deleted', 0)} "
                  f"remaining={st.get('events_remaining', '?')}")
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="NQ Primary Event-Cap")
    ap.add_argument("--db", default=None, help="Einzelne Monats-DB (optional)")
    a = ap.parse_args()
    results = run_cap(a.db)
    errors = [r for r in results if "error" in r]
    if errors:
        for e in errors:
            print(f"[nq_primary_cap] FEHLER {e['db']}: {e['error']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
