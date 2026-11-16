#!/bin/bash
# ============================================================
# scripts/dynamic_price_update.sh
# Tägliche Pflege der dynamischen Tarif-Schiene (Rolle A):
#   1. EPEX Day-Ahead Spot-Preise holen (heute + morgen, 3 Tage Lücken-Backfill)
#   2. Verbrauchsgewichtete Tarif-Kosten der letzten Tage neu aggregieren
# Die permanente Spiegelung nach analysis.db übernimmt der nächtliche
# Tiered-Sync (scripts/sync_tiered_daily.sh). Idempotent.
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
PY="$BASE/.venv/bin/python"
cd "$BASE"

echo "=== Dynamische Tarif-Schiene: Spot-Preise holen ==="
"$PY" -m collector.dynamic_price --days-forward 1 --backfill-days 3 || true

echo "=== Dynamische Tarif-Schiene: Kosten aggregieren ==="
"$PY" -m collector.aggregate.tariff_cost --days-back 3 || true

echo "=== fertig ==="
