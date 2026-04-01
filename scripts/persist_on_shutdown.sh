#!/bin/bash
# Persistiert die RAM-DB einmalig auf SD beim System-Shutdown/Reboot.
# Wird durch pv-shutdown-persist.service aufgerufen.

set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="/tmp/pv_shutdown_persist.log"
TMPFS_DB="/dev/shm/fronius_data.db"
PERSIST_DB="${BASE_DIR}/data.db"
export PV_BASE_DIR="$BASE_DIR"
export PV_TMPFS_DB="$TMPFS_DB"
export PV_PERSIST_DB="$PERSIST_DB"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
}

log "=== Shutdown-Persist gestartet ==="

rc=0
python3 - <<'PY' || rc=$?
import os
import sys

base_dir = os.environ.get('PV_BASE_DIR', '/home/admin/Dokumente/PVAnlage/pv-system')
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

try:
    import config
    import db_init
except Exception as exc:
    print(f"IMPORT_ERROR:{exc}")
    raise

ok = db_init._persist_tmpfs_to_sd(config.DB_PATH, config.DB_PERSIST_PATH)
if ok:
    print('PERSIST_OK')
    sys.exit(0)

print('PERSIST_SKIPPED')
sys.exit(2)
PY

if [[ $rc -eq 0 ]]; then
    log "Persist erfolgreich"
elif [[ $rc -eq 2 ]]; then
    log "Persist übersprungen (Sicherheitscheck/Fallback-Bedingung)"
    rc=0
else
    log "Persist mit db_init fehlgeschlagen (rc=$rc) — versuche sqlite3 Fallback"
    if [[ -f "$TMPFS_DB" ]]; then
        if sqlite3 "$TMPFS_DB" ".backup '${PERSIST_DB}'"; then
            log "Fallback sqlite3 .backup erfolgreich"
            rc=0
        else
            log "Fallback sqlite3 .backup ebenfalls fehlgeschlagen"
        fi
    else
        log "Fallback nicht möglich: tmpfs-DB fehlt ($TMPFS_DB)"
    fi
fi

log "=== Shutdown-Persist beendet (rc=$rc) ==="

# PID-Files entfernen, damit nach Reboot kein Stale-PID-Konflikt entsteht
for pidfile in "$BASE_DIR"/collector.pid "$BASE_DIR"/wattpilot_collector.pid "$BASE_DIR"/automation_daemon.pid; do
    if [[ -f "$pidfile" ]]; then
        rm -f "$pidfile"
        log "PID-File entfernt: $pidfile"
    fi
done

exit $rc
