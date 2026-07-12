"""nq.collector.nq_capping — Ring-Buffer/Kappung gegen tmpfs-Überlauf.

Skelett (Phase 1). Verantwortung (siehe doc/netzqualitaet/NQ_MODUL.md §5):
- Zeit-Ring: DELETE nq_raw_* WHERE ts < now-72h (Event-markierte ausgenommen).
- Größen-Kappung: bei tmpfs > cap_mb älteste Nicht-Event-Zeilen blockweise löschen.
- wal_checkpoint(TRUNCATE) + optimize; Protokoll in nq_capping_log.

Implementierung: .github/prompts/nq-1-tech-collector.prompt.md.
"""
from __future__ import annotations


def enforce_retention(conn, cfg: dict) -> None:
    raise NotImplementedError("Phase 1: siehe nq-1-tech-collector.prompt.md")
