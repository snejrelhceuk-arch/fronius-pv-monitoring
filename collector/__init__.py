"""
collector — Modbus/Fronius-Datensammler (Rolle A).

Aufteilung (Refactor 2026-05-16, vormals modbus_v3.py monolithisch):
  - pid_lock         — Single-Instance-Schutz
  - wp_power_protocol — Minutliches WP-Leistungsmaximum (Netzbetreiber-Nachweis)
  - modbus_client    — Eigenbau Modbus-TCP-Client + read_registers_safe
  - sunspec          — SunSpec-Parser + Discovery
  - energy_state     — Energie-Akkumulatoren (restore/save)
  - buffer           — RAM-Buffer + Batch-Flush in DB
  - attachment_state — Versions-Snapshot + Vollpruefung der Anknuepfungen
  - poller           — poll_once + poller_loop (Orchestrator)

Public Entry-Points: poller_loop, flush_buffer_to_db (via collector.poller).
"""

from .poller import poller_loop
from .buffer import flush_buffer_to_db

__all__ = ['poller_loop', 'flush_buffer_to_db']
