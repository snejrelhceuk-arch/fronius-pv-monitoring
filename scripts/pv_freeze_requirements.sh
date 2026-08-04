#!/bin/bash
# ============================================================
# scripts/pv_freeze_requirements.sh — regeneriert requirements.txt aus dem venv.
# Bedingung „update/upgrade": wird von pv_maintenance_upgrade.sh aufgerufen (oder
# manuell), damit requirements.txt die REALEN Paketversionen abbildet (kein Drift).
# Deterministisch (sortiert, kein Zeitstempel) -> nur echte Aenderungen = Diff.
# ============================================================
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
PIP="${BASE}/.venv/bin/pip"
REQ="${BASE}/requirements.txt"

if [[ ! -x "$PIP" ]]; then
  echo "Kein venv ($PIP) — requirements.txt unveraendert."
  exit 0
fi

{
  echo "# PV-System — Python-Abhaengigkeiten (AUTO-generiert)."
  echo "# Quelle: scripts/pv_freeze_requirements.sh (pip freeze des Produktions-venv)."
  echo "# NICHT von Hand editieren — wird bei update/upgrade neu erzeugt."
  echo "# Rebuild:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  echo "#"
  "$PIP" freeze --exclude-editable | sort -f
} > "$REQ"

echo "requirements.txt regeneriert ($(grep -cvE '^#|^$' "$REQ") Pakete)."
