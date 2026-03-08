#!/bin/bash
# =============================================================
# Log-Rotation für PV-System (/tmp = tmpfs, 256 MB)
# =============================================================
# Rotiert ALLE PV-System-Logs auf tmpfs:
#   - Gunicorn (access/error) — mit USR1-Signal für nahtloses Reopen
#   - Cron-Aggregate-Logs, Collector-Logs, Daemon-Logs
#   - Failover/Backup/Ollama-Logs
#
# Strategie:
#   1. Logs >10 MB oder >7 Tage → rotieren (mv + gzip)
#   2. Gunicorn: USR1 nach Rotation → Reopen der Log-FDs
#   3. Rotierte .gz älter 7 Tage → löschen
#   4. tmpfs-Nutzung im Blick behalten (<80%)
#
# Einplanung (crontab):
#   30 2 * * * /srv/pv-system/logrotate.sh >> /tmp/logrotate.log 2>&1
#   (02:30 — vor pv-backup-gfs um 03:00, nach system-logrotate um 00:00)
#
# Autor: PV-System, Datum: 2026-03-08
# =============================================================

set -euo pipefail

LOG_DIR="/tmp"
MAX_SIZE_MB=10       # Rotiere einzelne Logs ab dieser Größe
MAX_AGE_DAYS=7       # Rotiere auch wenn kleiner als MAX_SIZE_MB
KEEP_ROTATED_DAYS=7  # .gz-Archive aufbewahren (tmpfs → weg nach Reboot sowieso)
GUNICORN_PID="/tmp/pv_web.pid"

# Dynamisch: ALLE .log-Dateien auf tmpfs (nicht nur bekannte).
# Neue Logs (z.B. wp_modbus.log) werden automatisch erfasst.
# Ausgenommen: bereits rotierte (.log.*.gz) und systemd-private-Verzeichnisse.

TS=$(date +%Y%m%d_%H%M)
ROTATED=0
GUNICORN_NEEDS_REOPEN=false

echo "=== Log-Rotation Start: $(date) ==="

# ── 1. Rotieren: Zu groß oder zu alt ──
for LOGPATH in "${LOG_DIR}"/*.log; do
    [[ -f "$LOGPATH" ]] || continue
    LOGNAME=$(basename "$LOGPATH")

    SIZE_KB=$(du -k "$LOGPATH" 2>/dev/null | cut -f1)
    SIZE_MB=$(( SIZE_KB / 1024 ))
    AGE_DAYS=$(( ( $(date +%s) - $(stat -c %Y "$LOGPATH") ) / 86400 ))

    ROTATE=false
    if [[ "$SIZE_MB" -ge "$MAX_SIZE_MB" ]]; then
        ROTATE=true
        REASON="${SIZE_MB}MB ≥ ${MAX_SIZE_MB}MB"
    elif [[ "$AGE_DAYS" -ge "$MAX_AGE_DAYS" && "$SIZE_KB" -gt 100 ]]; then
        ROTATE=true
        REASON="${AGE_DAYS}d ≥ ${MAX_AGE_DAYS}d"
    fi

    if $ROTATE; then
        ARCHIVE="${LOGPATH}.${TS}"
        mv "$LOGPATH" "$ARCHIVE"
        gzip -q "$ARCHIVE" 2>/dev/null || true
        echo "  ✓ ${LOGNAME} rotiert (${REASON}) → $(basename "${ARCHIVE}.gz")"
        ROTATED=$((ROTATED + 1))

        # Gunicorn braucht USR1 zum Reopen
        if [[ "$LOGNAME" == pv_web_access.log || "$LOGNAME" == pv_web_error.log ]]; then
            GUNICORN_NEEDS_REOPEN=true
        fi
    fi
done

# ── 2. Gunicorn Log-Reopen (USR1-Signal) ──
if $GUNICORN_NEEDS_REOPEN; then
    if [[ -f "$GUNICORN_PID" ]]; then
        PID=$(cat "$GUNICORN_PID" 2>/dev/null)
        if kill -0 "$PID" 2>/dev/null; then
            kill -USR1 "$PID"
            echo "  ✓ Gunicorn (PID $PID) USR1 → Log-Reopen"
        else
            echo "  ⚠ Gunicorn PID $PID nicht aktiv"
        fi
    else
        echo "  ⚠ Gunicorn PID-File nicht gefunden ($GUNICORN_PID)"
    fi
fi

# ── 3. Alte Archive löschen ──
DELETED=$(find "$LOG_DIR" -maxdepth 1 -name "*.log.*.gz" -type f -mtime +${KEEP_ROTATED_DAYS} -delete -print 2>/dev/null | wc -l || true)
if [[ "$DELETED" -gt 0 ]]; then
    echo "  ✓ ${DELETED} alte Archive gelöscht (>${KEEP_ROTATED_DAYS}d)"
fi

# ── 4. tmpfs-Nutzung prüfen ──
USAGE_PCT=$(df /tmp | awk 'NR==2 {gsub(/%/,""); print $5}')
USAGE_MB=$(df -BM /tmp | awk 'NR==2 {gsub(/M/,""); print $3}')
echo "  tmpfs: ${USAGE_MB}MB belegt (${USAGE_PCT}%)"
if [[ "$USAGE_PCT" -gt 80 ]]; then
    echo "  ⚠ WARNUNG: tmpfs >80% belegt! DB-Betrieb gefährdet."
fi

echo "=== Log-Rotation: ${ROTATED} Logs rotiert ==="
