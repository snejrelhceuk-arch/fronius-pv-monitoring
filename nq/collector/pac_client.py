"""nq.collector.pac_client — Modbus-TCP-Leser für den Siemens PAC4200.

Skelett (Phase 1). Verantwortung:
- Verbindung zum PAC4200 (Modbus TCP, read-only).
- Lesen der drei Registerblöcke Fast / Medium / Slow.
- FLOAT32-Dekodierung (2 Register/Wert) gem. verifizierter Siemens-Registerliste.

WICHTIG: Registeradressen NICHT erfinden. Sie stammen aus der verifizierten
Siemens-PAC4200-Modbus-Doku und dem 48h-Feldtest (Phase 0). Siehe
doc/netzqualitaet/MESSTECHNIK.md und .github/prompts/nq-1-tech-collector.prompt.md.
"""
from __future__ import annotations


def read_fast_block(client, unit_id: int) -> dict:
    """RMS U/I, P/Q/S, cos φ, f. -> dict der Fast-Größen."""
    raise NotImplementedError("Phase 1: siehe nq-1-tech-collector.prompt.md")


def read_medium_block(client, unit_id: int) -> dict:
    """THD U/I, Unsymmetrie."""
    raise NotImplementedError("Phase 1: siehe nq-1-tech-collector.prompt.md")


def read_slow_block(client, unit_id: int) -> list:
    """Einzelharmonische 2..64 (U+I je Phase) -> Long-Format-Zeilen."""
    raise NotImplementedError("Phase 1: siehe nq-1-tech-collector.prompt.md")
