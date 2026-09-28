#!/bin/bash
set -euo pipefail
# =============================================================
# Code-Sync: Primary → Tech (Rolle N)  + Poller-Restart-Hook
#
# Synchronisiert NUR git-tracked Dateien (Code, Config, Doku) vom Primary
# zum Tech-Host (.181) — OHNE Laufzeitdaten. Tech hat KEINEN eigenen
# Code-Abgleich; ohne dieses Skript driftet der NQ-Collector (Poller lief
# z. B. mit alter Code-Basis ohne Harmonik-Thread).
#
# Poller-Restart-Hook: Wenn der Sync Dateien unter nq/ oder
# config/nq_config.json geaendert hat, werden pv-nq-poller.service und
# pv-nq-energy.service auf Tech neu gestartet (idempotent, ~0,5 s PAC-Luecke).
# So laeuft nach jedem Sync garantiert der aktuelle Code.
#
# GESYNCT:  *.py, scripts/*, templates/*, static/*, config/*.json, doc/*, .git/
# NICHT:    .role, .secrets, *.db/-wal/-shm, *.log, *.pid, __pycache__, backup/,
#           Laufzeit-States (battery_scheduler_state / battery_bms_checkpoints)
#
# Nutzung:
#   ./scripts/sync_code_to_tech.sh              # Sync + Restart-Hook (mit Nachfrage)
#   ./scripts/sync_code_to_tech.sh --dry-run    # nur anzeigen, nichts aendern
#   ./scripts/sync_code_to_tech.sh --force      # ohne Nachfrage (fuer Cron)
#   ./scripts/sync_code_to_tech.sh --no-restart # nur Code, Poller nicht neu starten
#
# Automatisierung (optional, nur auf Primary — <REPO> = absoluter Workspace-Pfad):
#   7 * * * *  <REPO>/scripts/sync_code_to_tech.sh --force >> /tmp/pv_sync_tech.log 2>&1
#
# Voraussetzungen: SSH-Key-Auth Primary→Tech, passwortloses `sudo -n systemctl`
# auf Tech. Aufruf NUR vom Primary-Host.
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load_infra_env.sh"

# --- Ziel (ueberschreibbar per Env / .infra.local) ---
TECH_USER="${PV_TECH_USER:-admin}"
TECH_IP="${PV_TECH_IP:-192.0.2.181}"
TECH="${TECH_USER}@${TECH_IP}"
REMOTE_PATH="${PV_SYNC_REMOTE_PATH:-Dokumente/PVAnlage/pv-system}"

# --- Role Guard: nur auf Primary ausfuehren ---
ROLE="primary"
[ -f "$REPO_ROOT/.role" ] && ROLE="$(head -1 "$REPO_ROOT/.role" | tr -d '[:space:]')"
if [ "$ROLE" != "primary" ]; then
    echo "❌  Dieses Script darf nur auf dem PRIMARY-Host laufen (Rolle: $ROLE)."
    exit 1
fi

# --- Argumente ---
DRY_RUN=""
FORCE=""
NO_RESTART=""
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n)   DRY_RUN="--dry-run" ;;
        --force|-f)     FORCE="1" ;;
        --no-restart)   NO_RESTART="1" ;;
        --help|-h)
            echo "Nutzung: $0 [--dry-run] [--force] [--no-restart]"
            exit 0 ;;
        *) echo "Unbekannter Parameter: $arg"; exit 1 ;;
    esac
done

# --- SSH-Erreichbarkeit ---
echo "🔍  Prüfe SSH-Verbindung zu $TECH ..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$TECH" "echo ok" >/dev/null 2>&1; then
    echo "❌  SSH-Verbindung zu $TECH fehlgeschlagen (Key-Auth? Host erreichbar?)."
    exit 1
fi
echo "✅  SSH-Verbindung OK."

# --- Commit-Stand vergleichen ---
cd "$REPO_ROOT"
LOCAL_HEAD="$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
REMOTE_HEAD="$(ssh "$TECH" "cd '$REMOTE_PATH' && git rev-parse --short HEAD" 2>/dev/null || echo '?')"
echo "    HEAD Primary: $LOCAL_HEAD   HEAD Tech: $REMOTE_HEAD"
[ "$LOCAL_HEAD" = "$REMOTE_HEAD" ] && echo "    Commit-Stand: ✅ identisch" \
                                   || echo "    Commit-Stand: ⚠️  DRIFT — Sync behebt das"

# --- Bestätigung ---
if [ -z "$FORCE" ] && [ -z "$DRY_RUN" ]; then
    echo "Code-Sync Primary → Tech starten? (j/N)"
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

echo ""
echo "🔄  rsync: $REPO_ROOT → $TECH:$REMOTE_PATH"
RSYNC_OUT="$(rsync -az --itemize-changes --delete $DRY_RUN \
    "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "$TECH:$REMOTE_PATH/")"
printf '%s\n' "$RSYNC_OUT"

# --- Poller-Restart-Hook: nur bei geaendertem NQ-Code / -Config ---
CHANGED_NQ="$(printf '%s\n' "$RSYNC_OUT" | awk 'NF{print $NF}' \
    | grep -E '^(nq/|config/nq_config\.json)' || true)"

echo ""
if [ -n "$DRY_RUN" ]; then
    echo "ℹ️  Dry-Run — keine Änderungen, kein Restart."
    exit 0
fi
echo "✅  Code-Sync abgeschlossen."

if [ -n "$NO_RESTART" ]; then
    echo "⏭️  --no-restart gesetzt — Poller nicht neu gestartet."
    exit 0
fi
if [ -z "$CHANGED_NQ" ]; then
    echo "ℹ️  Kein NQ-Code/-Config geändert — Poller-Restart nicht nötig."
    exit 0
fi

echo "🔁  NQ-Dateien geändert → Neustart pv-nq-poller / pv-nq-energy auf Tech:"
printf '     %s\n' $CHANGED_NQ
if ssh -o BatchMode=yes -o ConnectTimeout=8 "$TECH" \
        "sudo -n systemctl restart pv-nq-poller.service"; then
    echo "     ▶ pv-nq-poller neugestartet."
else
    echo "     ❌ pv-nq-poller-Restart fehlgeschlagen — Tech manuell prüfen."
    exit 1
fi
# pv-nq-energy best-effort (nicht kritisch für den Fast-Loop)
ssh -o BatchMode=yes -o ConnectTimeout=8 "$TECH" \
        "sudo -n systemctl restart pv-nq-energy.service" \
    && echo "     ▶ pv-nq-energy neugestartet." \
    || echo "     ⚠️ pv-nq-energy-Restart fehlgeschlagen (best-effort)."
