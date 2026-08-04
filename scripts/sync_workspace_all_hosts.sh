#!/bin/bash
set -euo pipefail
# =============================================================
# sync_workspace_all_hosts.sh — Workspace-Redundanz auf alle Pi
#
# Verteilt den git-tracked Workspace vom PRIMARY auf alle konfigurierten
# Hosts (Failover .195, Küche .105, Tech .181) — für Code-Redundanz.
# NUR git-tracked Code/Doku, KEINE Laufzeitdaten (siehe Ausschlüsse unten).
#
# ABCDEN-konform: gemeinsamer Code-Stand auf allen Hosts, Verhalten wird
# über die (nie gesyncte) .role-Datei gesteuert — nicht über divergenten Code.
#
# SD-schonend: rsync überträgt nur geänderte Dateien. Empfohlen 1×/Woche
# (bei Bedarf täglich). Beispiel-Crontab (nur auf dem Primary; <REPO> =
# absoluter Pfad zum pv-system-Workspace):
#   17 3 * * 0  <REPO>/scripts/sync_workspace_all_hosts.sh --force >> /tmp/pv_sync_all.log 2>&1
#
# Zielhosts: aus .infra.local (KEINE realen IPs im Repo).
#   PV_SYNC_HOSTS="user@host1 user@host2 user@host3"
#   PV_SYNC_REMOTE_PATH="Dokumente/PVAnlage/pv-system"   # relativ zum Home
#
# Nutzung:
#   ./scripts/sync_workspace_all_hosts.sh            # mit Nachfrage
#   ./scripts/sync_workspace_all_hosts.sh --dry-run  # nur anzeigen
#   ./scripts/sync_workspace_all_hosts.sh --force    # ohne Nachfrage (für Cron)
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load_infra_env.sh"

REMOTE_PATH="${PV_SYNC_REMOTE_PATH:-Dokumente/PVAnlage/pv-system}"
HOSTS_RAW="${PV_SYNC_HOSTS:-}"

# --- Role Guard: nur auf Primary ---
ROLE="primary"
[ -f "$REPO_ROOT/.role" ] && ROLE="$(head -1 "$REPO_ROOT/.role" | tr -d '[:space:]')"
if [ "$ROLE" != "primary" ]; then
    echo "❌  Nur auf dem PRIMARY-Host ausführen (Rolle: $ROLE)."
    exit 1
fi

if [ -z "$HOSTS_RAW" ]; then
    echo "❌  Keine Zielhosts konfiguriert."
    echo "    In ~/.infra.local setzen, z. B.:"
    echo "      PV_SYNC_HOSTS=\"user@host1 user@host2 user@host3\""
    exit 1
fi
read -r -a HOSTS <<< "$HOSTS_RAW"

# --- Argumente ---
DRY_RUN=""
FORCE=""
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY_RUN="--dry-run" ;;
        --force|-f)   FORCE="1" ;;
        --help|-h) echo "Nutzung: $0 [--dry-run] [--force]"; exit 0 ;;
        *) echo "Unbekannter Parameter: $arg"; exit 1 ;;
    esac
done

echo "📋  Primary-HEAD: $(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo '?')"
echo "🎯  Zielhosts: ${HOSTS[*]}  (Pfad: ~/$REMOTE_PATH)"
if [ -z "$FORCE" ] && [ -z "$DRY_RUN" ]; then
    echo "Workspace auf alle Hosts synchronisieren? (j/N)"
    read -r answer
    [ "$answer" = "j" ] || [ "$answer" = "J" ] || { echo "Abgebrochen."; exit 0; }
fi

RSYNC_EXCLUDES=(
    --exclude='.role' --exclude='.state/' --exclude='.secrets'
    --exclude='*.db' --exclude='*.db-shm' --exclude='*.db-wal'
    --exclude='*.db.bak_*' --exclude='*.db.before_restore_*' --exclude='data_backup_*.db'
    --exclude='*.log' --exclude='*.pid'
    --exclude='__pycache__/' --exclude='*.pyc'
    --exclude='.venv/' --exclude='venv/' --exclude='backup/' --exclude='imports/'
    --exclude='.vscode/' --exclude='.idea/' --exclude='*.swp' --exclude='*.swo'
    --exclude='config/tls/'
    --exclude='config/battery_scheduler_state.json'
    --exclude='config/battery_bms_checkpoints.json'
)

FAILED=()
for HOST in "${HOSTS[@]}"; do
    echo ""
    echo "────────────────────────────────────────────"
    echo "🔄  $HOST:~/$REMOTE_PATH"
    if ! ssh -o ConnectTimeout=8 -o BatchMode=yes "$HOST" "echo ok" >/dev/null 2>&1; then
        echo "⚠️  SSH nicht erreichbar — übersprungen."
        FAILED+=("$HOST (ssh)")
        continue
    fi
    if rsync -az --delete $DRY_RUN "${RSYNC_EXCLUDES[@]}" \
            "$REPO_ROOT/" "$HOST:$REMOTE_PATH/"; then
        echo "✅  $HOST synchronisiert."
    else
        echo "❌  rsync fehlgeschlagen: $HOST"
        FAILED+=("$HOST (rsync)")
    fi
done

echo ""
echo "────────────────────────────────────────────"
if [ -n "$DRY_RUN" ]; then
    echo "ℹ️  Dry-Run — keine Änderungen."
fi
if [ ${#FAILED[@]} -eq 0 ]; then
    echo "✅  Alle Hosts synchronisiert."
else
    echo "⚠️  Fehlgeschlagen: ${FAILED[*]}"
    exit 1
fi
