#!/bin/bash
set -euo pipefail
# =============================================================
# Failover Mirror Sync: DB vom Primär-Pi → tmpfs (RAM)
#
# Ziel: /dev/shm/fronius_data.db (tmpfs = kein SD-Karten-Verschleiß)
# Die SD-Card-Kopie (data.db) wird NUR vom 2-Tage-Backup aktualisiert.
#
# Ablauf:
#   1. rsync vom Primär nach /tmp (incoming)
#   2. Integrity-Check
#   3. Atomar nach /dev/shm verschieben (mv innerhalb tmpfs)
#
# Siehe doc/DUAL_HOST_ARCHITECTURE.md
# =============================================================

BASE="$(cd "$(dirname "$0")/.." && pwd)"
PRIMARY_HOST="${PRIMARY_HOST:-admin@192.0.2.181}"
REMOTE_DB_PATH="${REMOTE_DB_PATH:-/srv/pv-system/data.db}"
TMPFS_DB_PATH="/dev/shm/fronius_data.db"
TMP_INCOMING="/dev/shm/fronius_data.db.incoming"
LOCK_FILE="/tmp/pv_failover_sync.lock"
LOG_FILE="/tmp/pv_failover_sync.log"
SYNC_MARKER_FILE="${BASE}/.state/last_mirror_sync.ok"
TIMEOUT_SEC="${SYNC_TIMEOUT_SEC:-15}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

if ! flock -n 9; then
  log "Sync läuft bereits – übersprungen"
  exit 0
fi 9>"$LOCK_FILE"

mkdir -p "$(dirname "$SYNC_MARKER_FILE")"

# rsync direkt nach tmpfs (incoming) — kein SD-Karten-Write
if ! rsync -a --timeout="$TIMEOUT_SEC" "${PRIMARY_HOST}:${REMOTE_DB_PATH}" "$TMP_INCOMING"; then
  log "WARN: rsync fehlgeschlagen (${PRIMARY_HOST}:${REMOTE_DB_PATH})"
  rm -f "$TMP_INCOMING"
  exit 1
fi

# Integrity-Check
if command -v sqlite3 >/dev/null 2>&1; then
  CHECK=$(sqlite3 "$TMP_INCOMING" "PRAGMA integrity_check;" 2>/dev/null || echo "error")
  if [ "$CHECK" != "ok" ]; then
    log "WARN: integrity_check fehlgeschlagen (${CHECK})"
    rm -f "$TMP_INCOMING"
    exit 1
  fi
fi

# Atomar ins tmpfs verschieben (mv innerhalb /dev/shm = instant)
mv -f "$TMP_INCOMING" "$TMPFS_DB_PATH"
touch "$SYNC_MARKER_FILE"
log "OK: DB synchronisiert nach tmpfs von ${PRIMARY_HOST}"
