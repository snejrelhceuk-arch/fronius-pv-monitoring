#!/bin/bash
# =============================================================
# Git Post-Commit Hook — Automatischer Ollama Wissens-Sync
# =============================================================
#
# Wird nach jedem erfolgreichen Commit auf dem Primary-Host
# ausgeführt und synchronisiert das PV-System-Wissen zum
# Ollama-Host (192.0.2.116).
#
# Der Sync läuft im Hintergrund, um den Git-Workflow nicht
# zu blockieren. Ergebnis wird geloggt.
#
# Installation:
#   cp ollama/post-commit-ollama.sh .git/hooks/post-commit
#   chmod +x .git/hooks/post-commit
#
# Oder: install_hooks.sh nutzen (wenn vorhanden)
# =============================================================

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
SYNC_SCRIPT="${REPO_ROOT}/ollama/ollama_sync.py"
LOG_FILE="/tmp/ollama_sync.log"

# Guard: Nur auf Primary ausführen
ROLE_FILE="${REPO_ROOT}/.role"
ROLE="primary"
if [ -f "$ROLE_FILE" ]; then
    ROLE="$(head -1 "$ROLE_FILE" | tr -d '[:space:]')"
fi
if [ "$ROLE" != "primary" ]; then
    exit 0
fi

# Guard: Sync-Script muss existieren
if [ ! -f "$SYNC_SCRIPT" ]; then
    exit 0
fi

# Hintergrund-Sync (blockiert Git nicht)
(
    echo "──────────────────────────────────────" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Post-Commit Ollama Sync" >> "$LOG_FILE"
    cd "$REPO_ROOT" || exit 1
    python3 "$SYNC_SCRIPT" --quiet >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date '+%H:%M:%S')] Sync OK" >> "$LOG_FILE"
    else
        echo "[$(date '+%H:%M:%S')] Sync FEHLER (Exit $EXIT_CODE)" >> "$LOG_FILE"
    fi
) &

# Kurze Info an den Benutzer
echo "  🔄 Ollama-Sync gestartet (Hintergrund)"
