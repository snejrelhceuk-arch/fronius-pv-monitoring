#!/bin/bash
set -euo pipefail

# check_journal_db_io_health.sh
#
# Ziel:
# - Relevante Journald-Logs auf DB/Locking- und Kernel-I/O-Probleme pruefen
# - Keine False-Errors bei "0 Treffer" (rg exit 1)
# - Echte Ausfuehrungsfehler weiterhin mit Exit-Code != 0 melden
#
# Exit-Codes:
#   0 = keine Treffer
#   1 = mindestens ein Treffer gefunden
#   2 = technischer Fehler (journalctl/rg/Datei)

SINCE="${1:-$(date +%F) 00:00:00}"

TMP_DIR="/var/tmp/pv-system"
mkdir -p "$TMP_DIR"
APP_LOG="$(mktemp "$TMP_DIR/pv_app_db_health.XXXXXX.log")"
KERNEL_LOG="$(mktemp "$TMP_DIR/pv_kernel_io_health.XXXXXX.log")"
trap 'rm -f "$APP_LOG" "$KERNEL_LOG"' EXIT

APP_PATTERN='database is locked|database disk image is malformed|automation-log-db fehlgeschlagen|persist-db logging fehlgeschlagen|buffer flush error|ram-buffer voll'
KERNEL_PATTERN='ext4-fs error|i/o error|buffer i/o error|read-only file system|blk_update_request|journal has aborted'

status=0

scan_file() {
    local label="$1"
    local file="$2"
    local pattern="$3"

    set +e
    rg -in "$pattern" "$file"
    local rc=$?
    set -e

    if [[ $rc -eq 0 ]]; then
        echo "WARN: $label Treffer gefunden"
        status=1
        return 0
    fi

    if [[ $rc -eq 1 ]]; then
        echo "OK: keine $label Treffer"
        return 0
    fi

    echo "FEHLER: Scan fuer $label fehlgeschlagen (rc=$rc)" >&2
    exit 2
}

if ! journalctl -u pv-collector -u pv-automation -u pv-web --since "$SINCE" --no-pager > "$APP_LOG"; then
    echo "FEHLER: journalctl App-Logs fehlgeschlagen" >&2
    exit 2
fi

if ! journalctl -k --since "$SINCE" --no-pager > "$KERNEL_LOG"; then
    echo "FEHLER: journalctl Kernel-Logs fehlgeschlagen" >&2
    exit 2
fi

scan_file "App-DB" "$APP_LOG" "$APP_PATTERN"
scan_file "Kernel-I/O" "$KERNEL_LOG" "$KERNEL_PATTERN"

exit "$status"
