#!/bin/bash
set -euo pipefail

BASE="/srv/pv-system"
STAMP_DIR="/var/lib/pv-system"
STAMP_FILE="${STAMP_DIR}/backup_db_last_ts"
MIN_AGE_SEC=$((46*3600))
NOW=$(date +%s)

mkdir -p "$STAMP_DIR"

if [ -f "$STAMP_FILE" ]; then
  LAST=$(cat "$STAMP_FILE" 2>/dev/null || echo 0)
  if [[ "$LAST" =~ ^[0-9]+$ ]]; then
    AGE=$((NOW - LAST))
    if [ "$AGE" -lt "$MIN_AGE_SEC" ]; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup übersprungen (zu früh, ${AGE}s)."
      exit 0
    fi
  fi
fi

"${BASE}/scripts/backup_db.sh"
echo "$NOW" > "$STAMP_FILE"
