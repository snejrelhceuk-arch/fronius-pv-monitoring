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
PRIMARY_HOST="${PRIMARY_HOST:-admin@192.168.2.181}"
REMOTE_DB_PATH="${REMOTE_DB_PATH:-/home/admin/Dokumente/PVAnlage/pv-system/data.db}"
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

# SD-Fallback: data.db auf SD aktualisieren (nur wenn > 24h alt)
# Damit ensure_tmpfs_db() nach einem Reboot sofort eine Kopie hat,
# BEVOR der Timer (OnBootSec=45s) den ersten Mirror-Sync durchführt.
SD_DB="${BASE}/data.db"
SD_MAX_AGE=$((24*3600))
need_sd_update=0
if [ ! -f "$SD_DB" ]; then
  need_sd_update=1
elif [ -f "$SD_DB" ]; then
  sd_age=$(( $(date +%s) - $(stat -c %Y "$SD_DB") ))
  if [ "$sd_age" -gt "$SD_MAX_AGE" ]; then
    need_sd_update=1
  fi
fi
if [ "$need_sd_update" -eq 1 ]; then
  if cp "$TMPFS_DB_PATH" "${SD_DB}.tmp" && mv -f "${SD_DB}.tmp" "$SD_DB"; then
    log "SD-Fallback aktualisiert: ${SD_DB}"
  else
    log "WARN: SD-Fallback-Update fehlgeschlagen"
    rm -f "${SD_DB}.tmp"
  fi
fi
