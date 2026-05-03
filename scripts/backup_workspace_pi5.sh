#!/bin/bash
set -euo pipefail
# =============================================================
# Workspace-Backup: Primary → Pi5 (NVMe)
#
# Erzeugt einen komprimierten Datums-Snapshot des Workspaces:
#   pv-system-backup-YYYYMMDD.tar.gz  unter /home/user/ auf Pi5
#
# Ablauf:
#   1. rsync Code → Staging-Verzeichnis auf Pi5
#   2. SSH: tar -czf pv-system-backup-YYYYMMDD.tar.gz <staging>
#   3. SSH: Staging-Verzeichnis löschen
#
# Was wird GESYNCT:
#   - Python-Quellcode, Scripts, Templates, Static, Automation
#   - Konfiguration (config/*.json — versionierte)
#   - Dokumentation (doc/*, README*, CHANGELOG*)
#   - Tools, Git-Repository (.git/)
#
# Was wird NICHT gesichert:
#   - data.db / RAM-DBs      (eigener GFS-Pfad via backup_db_gfs.sh)
#   - *.log / *.pid          (Laufzeitstatus)
#   - .venv / __pycache__    (lokal reproduzierbar)
#   - backup/                (DB-Backups, eigener Pfad)
#   - config/tls/            (Host-spezifische TLS-Zertifikate)
#   - .secrets / .role       (Host-Identität)
#   - imports/               (große Rohdaten)
#
# Nutzung:
#   ./scripts/backup_workspace_pi5.sh             # Normal
#   ./scripts/backup_workspace_pi5.sh --dry-run   # Nur anzeigen
#   ./scripts/backup_workspace_pi5.sh --force     # Keine Nachfrage
#   ./scripts/backup_workspace_pi5.sh --no-db     # Kein DB-Backup-Sync
#
# Namensschema Pi5: /home/user/pv-system-backup-YYYYMMDD.tar.gz
# Vorhandene Backups: pv-system-backup-20260419.tar.gz usw.
# =============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load_infra_env.sh"

# --- Konfiguration ---
PI5_HOST="${PI5_BACKUP_HOST:-${PV_PI5_BACKUP_HOST:-admin@192.0.2.195}}"
PI5_BACKUP_DIR="/home/user"   # Zielverzeichnis für *.tar.gz auf Pi5
PI5_BACKUP_BASE_RAW="${PV_PI5_BACKUP_BASE:-/srv/pv-system/backup/db}"
PI5_DB_DAILY="${PI5_BACKUP_BASE_RAW}/daily"
STAMP="$(date +%Y%m%d)"
SNAPSHOT_NAME="pv-system-backup-${STAMP}"
STAGING_DIR="${PI5_BACKUP_DIR}/${SNAPSHOT_NAME}"
ARCHIVE="${PI5_BACKUP_DIR}/${SNAPSHOT_NAME}.tar.gz"

# --- Argumente ---
DRY_RUN=""
FORCE=""
SKIP_DB=""
for arg in "$@"; do
    case "$arg" in
        --dry-run|-n) DRY_RUN="1" ;;
        --force|-f)   FORCE="1" ;;
        --no-db)      SKIP_DB="1" ;;
        --help|-h)
            echo "Nutzung: $0 [--dry-run] [--force] [--no-db]"
            echo "  --dry-run  Nur anzeigen, nichts ändern"
            echo "  --force    Keine Bestätigung"
            echo "  --no-db    Kein DB-Backup-Sync"
            exit 0 ;;
        *) echo "Unbekannter Parameter: $arg"; exit 1 ;;
    esac
done

# --- SSH-Check ---
echo "🔍  Prüfe SSH-Verbindung zu $PI5_HOST ..."
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$PI5_HOST" "echo ok" >/dev/null 2>&1; then
    echo "❌  SSH nicht erreichbar: $PI5_HOST"
    echo "    Key-Auth eingerichtet? Ist Pi5 online?"
    exit 1
fi
echo "✅  SSH OK: $PI5_HOST"

# --- Commit-Status + vorhandene Backups anzeigen ---
echo ""
echo "📋  Git HEAD (Primary):"
cd "$REPO_ROOT"
LOCAL_HEAD="$(git rev-parse --short HEAD)"
LOCAL_MSG="$(git log -1 --pretty=format:'%s')"
echo "    $LOCAL_HEAD  $LOCAL_MSG"
GIT_STATUS="$(git status --porcelain | wc -l)"
if [ "$GIT_STATUS" -gt 0 ]; then
    echo "    ⚠️  Working Tree nicht sauber ($GIT_STATUS geänderte Dateien)!"
else
    echo "    ✅  Working Tree sauber"
fi

echo ""
echo "📦  Vorhandene Workspace-Backups auf Pi5:"
ssh -o ConnectTimeout=10 "$PI5_HOST" \
    "ls -lh ${PI5_BACKUP_DIR}/pv-system-backup-*.tar.gz 2>/dev/null || echo '    (keine)'"

# Prüfen ob heute schon ein Backup existiert
if ssh -o ConnectTimeout=10 "$PI5_HOST" "test -f '$ARCHIVE'" 2>/dev/null; then
    echo ""
    echo "⚠️  Backup für heute existiert bereits: $ARCHIVE"
    if [ -z "$FORCE" ]; then
        echo "    Überschreiben? (j/N)"
        read -r answer
        if [ "$answer" != "j" ] && [ "$answer" != "J" ]; then
            echo "Abgebrochen."
            exit 0
        fi
    fi
fi

echo ""
if [ -n "$DRY_RUN" ]; then
    echo "ℹ️  Dry-Run — Ziel wäre: $PI5_HOST:$ARCHIVE"
    echo "    rsync-Quelle: $REPO_ROOT/"
    exit 0
fi

# --- Bestätigung ---
if [ -z "$FORCE" ]; then
    echo "Snapshot '$SNAPSHOT_NAME.tar.gz' auf $PI5_HOST erstellen? (j/N)"
    read -r answer
    if [ "$answer" != "j" ] && [ "$answer" != "J" ]; then
        echo "Abgebrochen."
        exit 0
    fi
fi

# --- Staging-Verzeichnis auf Pi5 anlegen ---
echo ""
echo "🔄  rsync → Staging: $PI5_HOST:$STAGING_DIR/"
ssh -o ConnectTimeout=10 "$PI5_HOST" "rm -rf '$STAGING_DIR' && mkdir -p '$STAGING_DIR'"

rsync -avz \
    --exclude='.role' \
    --exclude='.state/' \
    --exclude='.secrets' \
    --exclude='*.db' \
    --exclude='*.db-shm' \
    --exclude='*.db-wal' \
    --exclude='*.db.bak_*' \
    --exclude='*.pid' \
    --exclude='*.log' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.venv/' \
    --exclude='venv/' \
    --exclude='backup/' \
    --exclude='imports/' \
    --exclude='config/tls/' \
    --exclude='.vscode/' \
    --exclude='*.swp' \
    --exclude='*.swo' \
    --exclude='config/battery_scheduler_state.json' \
    --exclude='config/battery_bms_checkpoints.json' \
    "$REPO_ROOT/" \
    "$PI5_HOST:$STAGING_DIR/"

echo ""
echo "🗜️  Komprimiere Snapshot auf Pi5 ..."
ssh -o ConnectTimeout=30 "$PI5_HOST" \
    "cd '$PI5_BACKUP_DIR' && tar -czf '${SNAPSHOT_NAME}.tar.gz' '$SNAPSHOT_NAME/' && rm -rf '$SNAPSHOT_NAME/'"

echo ""
ARCHIVE_SIZE="$(ssh -o ConnectTimeout=10 "$PI5_HOST" "du -sh '$ARCHIVE' 2>/dev/null | cut -f1" || echo "?")"
echo "✅  Snapshot erstellt: $PI5_HOST:$ARCHIVE  ($ARCHIVE_SIZE)"

# --- DB-Backup-Sync (neuestes daily) ---
if [ -z "$SKIP_DB" ]; then
    echo ""
    echo "🗄️  DB-Backup-Sync (daily) ..."
    LOCAL_DAILY_DIR="$REPO_ROOT/backup/db/daily"
    LATEST_DB="$(ls -1t "$LOCAL_DAILY_DIR"/*.gz 2>/dev/null | head -1 || true)"
    if [ -z "$LATEST_DB" ]; then
        echo "    ⚠️  Kein lokales DB-Backup unter $LOCAL_DAILY_DIR — übersprungen."
    else
        FNAME="$(basename "$LATEST_DB")"
        if ssh -o ConnectTimeout=10 "$PI5_HOST" "test -f '$PI5_DB_DAILY/$FNAME'" 2>/dev/null; then
            echo "    ✓  $FNAME bereits auf Pi5 vorhanden — übersprungen."
        else
            ssh -o ConnectTimeout=10 "$PI5_HOST" "mkdir -p '$PI5_DB_DAILY'"
            rsync -avz --timeout=60 "$LATEST_DB" "$PI5_HOST:$PI5_DB_DAILY/" && \
                echo "    ✅  $FNAME → Pi5:$PI5_DB_DAILY" || \
                echo "    ⚠️  DB-Backup-Sync fehlgeschlagen (nicht kritisch)."
        fi
    fi
fi

echo ""
echo "✅  Workspace-Backup Pi5 abgeschlossen."
echo "    Archiv: $PI5_HOST:$ARCHIVE"
