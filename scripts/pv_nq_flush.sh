#!/bin/bash
# ============================================================
# scripts/pv_nq_flush.sh — erzwingt JETZT den NQ-Transfer Tech->Primary.
#
# Zweck: vor einem PLANMAESSIGEN Reboot von Pi4-Tech (oder on demand) alle
# anhaengigen NQ-Daten dauerhaft auf Primary-SD sichern. Tech haelt die
# PAC4200-Daten RAM-first (tmpfs /dev/shm/nq_cache.db, WAL) OHNE SD-Persistenz;
# der regulaere Pull laeuft nur alle 4h. Dieses Skript zieht sofort:
#   1. 5min-Aggregate + Harmonik (nq_agg_transfer)
#   2. Event-Schnipsel (nq_event_transfer)
#   3. Kaskaden-Aggregation 5min->hourly->daily (nq_aggregate)
#   4. HF/NF-Analyse des Fensters (nq_events)
#   5. Event-Retention (nq_primary_cap)
#
# Pull-Modell: LAEUFT AUF PRIMARY (zieht von Tech via SSH). Rohdaten 200ms/1s
# sind bauartbedingt fluechtig und werden bewusst NICHT persistiert.
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE"
HOURS="${1:-12}"
PY=/usr/bin/python3   # NQ-Dienste laufen unter System-Python (siehe systemd-Units)

run() {
  echo "-> $*"
  "$@" || echo "   WARN: rc=$? bei: $*"
}

echo "=== NQ-Flush Tech->Primary (Fenster ${HOURS}h) — $(date '+%F %T') ==="
run "$PY" -m nq.transfer.nq_agg_transfer --hours "$HOURS"
run "$PY" -m nq.transfer.nq_event_transfer --hours 2
run "$PY" -m nq.aggregate.nq_aggregate all
run "$PY" -m nq.analysis.nq_events --hours "$HOURS" --bands HF_local,NF_global
run "$PY" -m nq.transfer.nq_primary_cap
echo "=== NQ-Flush fertig — $(date '+%F %T') ==="
