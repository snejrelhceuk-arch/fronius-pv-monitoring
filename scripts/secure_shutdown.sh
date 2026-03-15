#!/bin/bash
# Sicheres Herunterfahren des PV-Systems
# Persistiert die RAM-DB auf SD, stoppt Services, dann Shutdown.
#
# Verwendung:
#   ./scripts/secure_shutdown.sh           # Persist + Stop + Shutdown
#   ./scripts/secure_shutdown.sh --no-halt # Persist + Stop (ohne Shutdown)

set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TMPFS_DB="/dev/shm/fronius_data.db"
PERSIST_DB="${BASE_DIR}/data.db"
LOG_FILE="/tmp/secure_shutdown.log"
NO_HALT=0

[[ "${1:-}" == "--no-halt" ]] && NO_HALT=1

log() { echo "$(date '+%H:%M:%S') $1" | tee -a "$LOG_FILE"; }

log "=== Secure Shutdown gestartet ==="

# ── 1. DB-Persist erzwingen ──────────────────────────────────
log "1. Erzwinge DB-Persist (tmpfs → SD)..."
if [[ -f "$TMPFS_DB" ]]; then
    SIZE_BEFORE=$(stat -c%s "$TMPFS_DB" 2>/dev/null || echo 0)
    if (( SIZE_BEFORE > 100000 )); then
        python3 -c "
import sys
sys.path.insert(0, '${BASE_DIR}')
import config, db_init
ok = db_init._persist_tmpfs_to_sd(config.DB_PATH, config.DB_PERSIST_PATH)
sys.exit(0 if ok else 1)
"
        if [[ $? -eq 0 ]]; then
            SIZE_AFTER=$(stat -c%s "$PERSIST_DB" 2>/dev/null || echo 0)
            log "  ✓ DB persistiert ($(( SIZE_AFTER / 1048576 )) MB)"
        else
            log "  ✗ Persist fehlgeschlagen — Fallback: direktes sqlite3 .backup"
            sqlite3 "$TMPFS_DB" ".backup '${PERSIST_DB}'"
            log "  ✓ Fallback-Backup geschrieben"
        fi
    else
        log "  ⚠ tmpfs-DB zu klein (${SIZE_BEFORE} Bytes) — übersprungen"
    fi
else
    log "  ⚠ Keine tmpfs-DB vorhanden — übersprungen"
fi

# ── 2. Services stoppen ──────────────────────────────────────
log "2. Stoppe PV-Services..."
for svc in pv-automation pv-observer pv-wattpilot; do
    if systemctl is-active --quiet "$svc.service" 2>/dev/null; then
        sudo systemctl stop "$svc.service" && log "  ✓ $svc gestoppt" || log "  ✗ $svc Stop fehlgeschlagen"
    else
        log "  – $svc nicht aktiv"
    fi
done

# Gunicorn/Web separat (verschiedene Service-Namen möglich)
for svc in pv-web pv-collector; do
    if systemctl is-active --quiet "$svc.service" 2>/dev/null; then
        sudo systemctl stop "$svc.service" && log "  ✓ $svc gestoppt" || true
    fi
done

# Aggregate-Prozesse beenden
pkill -f "pv-system/aggregate" 2>/dev/null && log "  ✓ Aggregate-Prozesse beendet" || true

# PID-Files aufräumen
for pf in "${BASE_DIR}/collector.pid" "${BASE_DIR}/wattpilot_collector.pid" "${BASE_DIR}/automation_daemon.pid"; do
    [[ -f "$pf" ]] && rm -f "$pf" && log "  ✓ $(basename "$pf") entfernt"
done

sleep 1

# ── 3. Verifikation ─────────────────────────────────────────
log "3. Verifikation..."
REMAINING=$(ps aux | grep -E "pv-system" | grep -v grep | grep -v "secure_shutdown" | grep python3 || true)
if [[ -n "$REMAINING" ]]; then
    log "  ⚠ Verbleibende Prozesse:"
    echo "$REMAINING" | tee -a "$LOG_FILE"
else
    log "  ✓ Keine PV-Prozesse mehr aktiv"
fi

log "=== Services gestoppt, DB gesichert ==="

# ── 4. Shutdown ──────────────────────────────────────────────
if [[ $NO_HALT -eq 0 ]]; then
    log "4. System wird heruntergefahren..."
    sync
    sudo shutdown now
else
    log "4. --no-halt: Kein Shutdown (nur Services gestoppt)"
    log "   Zum Herunterfahren: sudo shutdown now"
fi
