"""nq.collector.nq_poller — Orchestrator des Block-Pollings auf Tech.

Skelett (Phase 1). Verantwortung (Vorbild: collector/poller.py + collector/buffer.py):
- Getrennte Poll-Takte je Block (Fast 500 ms / Medium 1 s / Slow 5 s).
- deque-RAM-Buffer + Batch-executemany-Flush in die tmpfs-DB.
- Event-Vorfilter setzt das event-Flag auf RAW-Zeilen.
- 3–10 s-Aggregat (min/avg/max) fortlaufend fortschreiben.

Start: python3 -m nq.collector.nq_poller
Implementierung: .github/prompts/nq-1-tech-collector.prompt.md.
"""
from __future__ import annotations


def poller_loop() -> None:
    raise NotImplementedError("Phase 1: siehe nq-1-tech-collector.prompt.md")


if __name__ == "__main__":
    poller_loop()
