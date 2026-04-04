#!/bin/bash
# =================================================================
# Monitoring-Wrapper für Diagnos Schicht D (read-only)
# Single Source of Truth: diagnos/health.py
#
# Exit-Code:
#   0 = alles OK
#   1 = Warnung(en)
#   2 = kritisch/fail
#
# Cron: */15 * * * * /srv/pv-system/scripts/monitor_health.sh
# =================================================================

set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="/tmp/monitor_health.log"
ALERT_FILE="/tmp/monitor_health_alerts.log"
RESULT_FILE="/tmp/monitor_health_last.json"

cd "$BASE_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Logfile Rotation (maximal 1000 Zeilen)
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE" 2>/dev/null)" -gt 1000 ]; then
    tail -500 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

log "=== Health-Check gestartet (diagnos.health) ==="

if python3 -m diagnos.health --pretty > "$RESULT_FILE" 2>> "$ALERT_FILE"; then
    RC=0
else
    RC=$?
fi

if [ "$RC" -eq 0 ]; then
    log "=== ERGEBNIS: Alles OK ==="
elif [ "$RC" -eq 1 ]; then
    log "=== ERGEBNIS: Warnungen gefunden ==="
else
    log "=== ERGEBNIS: Kritisch/Fail ==="
fi

exit "$RC"
