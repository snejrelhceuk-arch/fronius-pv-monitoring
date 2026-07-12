"""nq.transfer.nq_export_tech — Tech-seitiger Tages-Export.

Skelett (Phase 2). Verantwortung (siehe NQ_MODUL.md §6.1):
- Exportiert nur nq_agg_10s (Vortag) + Event-markierte RAW-Segmente.
- Batch nach Primary (LAN); Löschung aus tmpfs erst nach Quittung (at-least-once).
- Protokoll in nq_transfer_log.

Start: python3 -m nq.transfer.nq_export_tech
Implementierung: .github/prompts/nq-2-transfer-aggregation.prompt.md.
"""
from __future__ import annotations


def run_export() -> None:
    raise NotImplementedError("Phase 2: siehe nq-2-transfer-aggregation.prompt.md")


if __name__ == "__main__":
    run_export()
