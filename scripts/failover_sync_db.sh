#!/bin/bash
set -euo pipefail

BASE="/srv/pv-system"
PRIMARY_HOST="${PRIMARY_HOST:-admin@192.0.2.181}"
REMOTE_DB_PATH="${REMOTE_DB_PATH:-/srv/pv-system/data.db}"
LOCAL_DB_PATH="${LOCAL_DB_PATH:-${BASE}/data.db}"
TMP_DB_PATH="${LOCAL_DB_PATH}.incoming"
LOCK_FILE="/tmp/pv_failover_sync.lock"
LOG_FILE="/tmp/pv_failover_sync.log"
TIMEOUT_SEC="${SYNC_TIMEOUT_SEC:-15}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

if ! flock -n 9; then
  log "Sync läuft bereits – übersprungen"
  exit 0
fi 9>"$LOCK_FILE"

mkdir -p "$(dirname "$LOCAL_DB_PATH")"

if ! rsync -a --timeout="$TIMEOUT_SEC" "${PRIMARY_HOST}:${REMOTE_DB_PATH}" "$TMP_DB_PATH"; then
  log "WARN: rsync fehlgeschlagen (${PRIMARY_HOST}:${REMOTE_DB_PATH})"
  rm -f "$TMP_DB_PATH"
  exit 1
fi

if command -v sqlite3 >/dev/null 2>&1; then
  CHECK=$(sqlite3 "$TMP_DB_PATH" "PRAGMA integrity_check;" 2>/dev/null || echo "error")
  if [ "$CHECK" != "ok" ]; then
    log "WARN: integrity_check fehlgeschlagen (${CHECK})"
    rm -f "$TMP_DB_PATH"
    exit 1
  fi
fi

mv -f "$TMP_DB_PATH" "$LOCAL_DB_PATH"
log "OK: DB synchronisiert von ${PRIMARY_HOST}"
