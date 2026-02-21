#!/bin/bash
set -euo pipefail
# =============================================================
# Code-Sync: Primary (181) → Failover (failover-host/105)
#
# Synchronisiert NUR git-tracked Dateien (Code, Templates, Doku)
# vom Primary-Host zum Failover — OHNE host-spezifische Daten.
#
# Was wird GESYNCT:
#   - Python-Quellcode (*.py)
#   - Shell-Scripts (scripts/*)
#   - Templates (templates/*)
#   - Statische Dateien (static/*)
#   - Konfiguration (config/*.json — nur versionierte)
#   - Dokumentation (doc/*, README.md)
#   - Git-Repository (.git/) — damit git pull/log auf 105 funktioniert
#
# Was wird NICHT gesynct (host-spezifisch):
#   - .role                    (Host-Identität)
#   - .state/                  (Laufzeit-Status)
#   - *.db / *.db-*            (Datenbank — eigener Sync via mirror)
#   - *.log                    (Logfiles)
#   - *.pid                    (Prozess-IDs)
#   - __pycache__/             (Bytecode)
#   - backup/                  (lokale Backups)
#   - .secrets                 (Zugangsdaten)
#   - config/battery_scheduler_state.json  (Laufzeitstatus)
#   - config/battery_bms_checkpoints.json  (Laufzeitstatus)
#
# Nutzung:
#   ./scripts/sync_code_to_peer.sh            # Normal-Sync
#   ./scripts/sync_code_to_peer.sh --dry-run  # Nur anzeigen
#   ./scripts/sync_code_to_peer.sh --force     # Ohne Nachfrage
#
# Voraussetzungen:
#   - SSH-Key-Auth von 181 → 105 (admin → jk)
#   - Aufruf NUR vom Primary-Host (181)
#
# Siehe doc/DUAL_HOST_ARCHITECTURE.md Abschnitt 9.
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Konfiguration (überschreibbar per Env-Variable) ---
FAILOVER_HOST="${FAILOVER_HOST:-failover-user@failover-host}"
FAILOVER_REPO="${FAILOVER_REPO:-/srv/pv-system}"

# --- Role Guard: nur auf Primary ausführen ---
ROLE="primary"
ROLE_FILE="$REPO_ROOT/.role"
if [ -f "$ROLE_FILE" ]; then
    ROLE="$(head -1 "$ROLE_FILE" | tr -d '[:space:]')"
fi

if [ "$ROLE" != "primary" ]; then
    echo "❌  Dieses Script darf nur auf dem PRIMARY-Host laufen."
    echo "    Aktuelle Rolle: $ROLE"
    exit 1
fi

# --- Argumente parsen ---
DRY_RUN=""
FORCE=""
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY_RUN="--dry-run" ;;
        --force|-f)   FORCE="1" ;;
        --help|-h)
            echo "Nutzung: $0 [--dry-run] [--force]"
            echo "  --dry-run  Nur anzeigen, nichts ändern"
            echo "  --force    Keine Nachfrage"
            exit 0 ;;
        *)
            echo "Unbekannter Parameter: $arg"
            exit 1 ;;
    esac
done

# --- SSH-Erreichbarkeit prüfen ---
echo "🔍  Prüfe SSH-Verbindung zu $FAILOVER_HOST ..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$FAILOVER_HOST" "echo ok" >/dev/null 2>&1; then
    echo "❌  SSH-Verbindung zu $FAILOVER_HOST fehlgeschlagen."
    echo "    Ist Key-Auth eingerichtet? Ist der Host erreichbar?"
    exit 1
fi
echo "✅  SSH-Verbindung OK."

# --- Git-Status anzeigen ---
echo ""
echo "📋  Git-Status auf Primary:"
cd "$REPO_ROOT"
git status --short
echo ""

LOCAL_HEAD="$(git rev-parse --short HEAD)"
REMOTE_HEAD="$(ssh "$FAILOVER_HOST" "cd '$FAILOVER_REPO' && git rev-parse --short HEAD" 2>/dev/null || echo "?")"
echo "    HEAD local (181):  $LOCAL_HEAD"
echo "    HEAD peer  (105):  $REMOTE_HEAD"
if [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    echo "    Commit-Stand: ✅ identisch"
else
    echo "    Commit-Stand: ⚠️  DRIFT — Sync wird das beheben"
fi
echo ""

# --- Bestätigung ---
if [ -z "$FORCE" ] && [ -z "$DRY_RUN" ]; then
    echo "Soll der Code-Sync gestartet werden? (j/N)"
    read -r answer
    if [ "$answer" != "j" ] && [ "$answer" != "J" ]; then
        echo "Abgebrochen."
        exit 0
    fi
fi

# --- rsync mit Ausschlüssen ---
echo "🔄  Starte Code-Sync: $REPO_ROOT → $FAILOVER_HOST:$FAILOVER_REPO"
echo ""

rsync -avz --delete \
    $DRY_RUN \
    --exclude='.role' \
    --exclude='.state/' \
    --exclude='.secrets' \
    --exclude='*.db' \
    --exclude='*.db-shm' \
    --exclude='*.db-wal' \
    --exclude='*.db.bak_*' \
    --exclude='*.db.before_restore_*' \
    --exclude='data_backup_*.db' \
    --exclude='*.log' \
    --exclude='*.pid' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.venv/' \
    --exclude='venv/' \
    --exclude='backup/' \
    --exclude='archive/' \
    --exclude='.vscode/' \
    --exclude='.idea/' \
    --exclude='*.swp' \
    --exclude='*.swo' \
    --exclude='E/' \
    --exclude='imports/' \
    --exclude='ToExamine.md' \
    --exclude='config/battery_scheduler_state.json' \
    --exclude='config/battery_bms_checkpoints.json' \
    "$REPO_ROOT/" \
    "$FAILOVER_HOST:$FAILOVER_REPO/"

EXIT_CODE=$?

echo ""
if [ -n "$DRY_RUN" ]; then
    echo "ℹ️  Dry-Run — keine Änderungen durchgeführt."
elif [ $EXIT_CODE -eq 0 ]; then
    echo "✅  Code-Sync abgeschlossen."
    echo ""
    echo "Nächste Schritte auf dem Failover ($FAILOVER_HOST):"
    echo "  1. Hook installieren: ./scripts/install_hooks.sh"
    echo "  2. Prüfen: git log --oneline -3"
    echo "  3. .role prüfen: cat .role  (sollte 'failover' sein)"
else
    echo "❌  rsync beendet mit Exit-Code $EXIT_CODE"
    exit $EXIT_CODE
fi
