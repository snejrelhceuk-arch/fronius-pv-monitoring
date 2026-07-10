#!/bin/bash
# =================================================================
# backup_longterm_offload.sh — Großvater-Ebene (monthly/yearly)
# zusätzlich auf Pi4-Küche als Longterm-Archiv spiegeln.
#
# Rolle: läuft auf dem Backup-Host (Pi5-FB), der die komplette
# GFS-Kette hält. daily/weekly bleiben auf Primary/Pi5-FB;
# monthly/yearly werden hier zusätzlich auf getrennte Hardware
# (Pi4-Küche) gespiegelt → verteilte Großvater-Sicherung.
#
# KEIN role_guard: dieser Job soll gerade auf dem Failover/Backup-
# Host laufen. Steuerung erfolgt über den systemd-Timer, der NUR
# auf Pi5-FB installiert wird (install_longterm_offload.sh).
#
# Konfiguration (.infra.local):
#   PV_KUECHE_HOST=<user>@<pi4-kueche-ip>
#   PV_KUECHE_ARCHIVE_BASE=pv-longterm-archive   # relativ zum Remote-Home
# =================================================================
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
source "$BASE/scripts/load_infra_env.sh" 2>/dev/null || true

BACKUP_BASE="${BACKUP_BASE:-${BASE}/backup/db}"
LOG_FILE="${LOG_FILE:-/tmp/backup_longterm_offload.log}"
KUECHE_HOST="${PV_KUECHE_HOST:-}"
KUECHE_ARCHIVE_BASE="${PV_KUECHE_ARCHIVE_BASE:-pv-longterm-archive}"
TIERS=(monthly yearly)

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"; }

if [ -z "$KUECHE_HOST" ]; then
    log "PV_KUECHE_HOST nicht konfiguriert → Longterm-Offload übersprungen."
    exit 0
fi

if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$KUECHE_HOST" 'true' 2>/dev/null; then
    log "⚠ Pi4-Küche ($KUECHE_HOST) nicht erreichbar → Offload übersprungen (kein Fehler)."
    exit 0
fi

rc=0
for tier in "${TIERS[@]}"; do
    src="$BACKUP_BASE/$tier/"
    [ -d "$src" ] || { log "  (kein $tier-Verzeichnis lokal, überspringe)"; continue; }
    remote="$KUECHE_ARCHIVE_BASE/$tier"
    ssh -o ConnectTimeout=10 "$KUECHE_HOST" "mkdir -p '$remote'" 2>/dev/null || { log "  ⚠ mkdir $tier fehlgeschlagen"; rc=1; continue; }
    # Longterm-Archiv: nur hinzufügen, NIE löschen (kein --delete).
    if rsync -az --timeout=120 --ignore-existing "$src" "$KUECHE_HOST:$remote/" 2>>"$LOG_FILE"; then
        n=$(ls -1 "$src"*.gz 2>/dev/null | wc -l)
        log "  ✓ $tier → $KUECHE_HOST:$remote ($n Dateien geprüft/gespiegelt)"
    else
        log "  ⚠ rsync $tier fehlgeschlagen"; rc=1
    fi
done

log "Longterm-Offload fertig (rc=$rc)."
exit "$rc"
