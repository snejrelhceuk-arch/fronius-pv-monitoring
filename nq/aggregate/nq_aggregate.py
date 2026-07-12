"""nq.aggregate.nq_aggregate — Kaskade 3–10 s → 5 min → hourly → daily.

Skelett (Phase 2). Vorbild: collector/aggregate/*. min/avg/max(/std) je Größe,
Cron-gestaffelt, Retention gem. config/nq_config.json.

Start: python3 -m nq.aggregate.nq_aggregate <stufe>
Implementierung: .github/prompts/nq-2-transfer-aggregation.prompt.md.
"""
from __future__ import annotations


def run(stage: str) -> None:
    """stage in {'5min','hourly','daily'}."""
    raise NotImplementedError("Phase 2: siehe nq-2-transfer-aggregation.prompt.md")
