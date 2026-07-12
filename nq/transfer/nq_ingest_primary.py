"""nq.transfer.nq_ingest_primary — Primary-seitige Übernahme.

Skelett (Phase 2). Verantwortung (siehe NQ_MODUL.md §6):
- Empfängt/liest den Tech-Export, schreibt nq_agg_10s + nq_event_* in die
  Monats-DB nq/db/nq_YYYY-MM.db, quittiert an Tech.
- Protokoll in nq_ingest_log.

Start: python3 -m nq.transfer.nq_ingest_primary
Implementierung: .github/prompts/nq-2-transfer-aggregation.prompt.md.
"""
from __future__ import annotations


def run_ingest() -> None:
    raise NotImplementedError("Phase 2: siehe nq-2-transfer-aggregation.prompt.md")


if __name__ == "__main__":
    run_ingest()
