#!/bin/bash
# ============================================================
# recovery/export_usb.sh — Recovery-Paket auf externen USB-Datentraeger
#
# Kopiert das neueste Recovery-Paket (+ Secrets-Bundle, falls vorhanden) auf
# einen gemounteten USB-Stick und hinterlegt dort einen Versions-Marker
# (USB_RECOVERY_VERSION) mit der MAJOR-Version. Der Selfcheck mahnt die
# Neu-Uebertragung, sobald die Major-Version springt.
#
# Dieser Stick ist der Standard-Datentraeger fuer das Extrem-Szenario
# "alle Pis aus" und gehoert raeumlich getrennt gelagert (anderes Gebaeude).
#
# Nutzung:
#   recovery/export_usb.sh --dest /media/<user>/<stick>        # kopieren
#   recovery/export_usb.sh --dest /media/<user>/<stick> --with-secrets
# ============================================================
set -uo pipefail
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SELF_DIR/lib/recovery_common.sh"

DEST=""; WITH_SECRETS=""
while [ $# -gt 0 ]; do case "$1" in
  --dest) shift; DEST="${1:-}" ;;
  --with-secrets) WITH_SECRETS=1 ;;
esac; shift; done
[ -n "$DEST" ] || r_die "--dest <mount-pfad> erforderlich"
[ -d "$DEST" ] || r_die "Ziel nicht gemountet/kein Verzeichnis: $DEST"

OUT_DIR="$R_REPO_ROOT/backup/recovery"
[ -f "$OUT_DIR/LATEST_RECOVERY" ] || r_die "Kein Recovery-Paket. Zuerst: recovery/build_recovery_bundle.sh"

read -r MAJOR HEAD CREATED PKG < "$OUT_DIR/LATEST_RECOVERY"
SRC="$OUT_DIR/$PKG"
[ -f "$SRC" ] || r_die "Paket-Datei fehlt: $SRC"

USB_DIR="$DEST/pv-system-recovery"
mkdir -p "$USB_DIR"
r_log "Kopiere $PKG -> $USB_DIR"
rsync -a "$SRC" "$SRC.sha256" "$USB_DIR/"
( cd "$USB_DIR" && sha256sum -c "$(basename "$SRC").sha256" ) || r_die "Checksum-Fehler auf USB"

if [ -n "$WITH_SECRETS" ]; then
  cp "$OUT_DIR"/secrets_*.tar.gz.gpg "$USB_DIR/" 2>/dev/null \
    && r_log "Secrets-Bundle mitkopiert (verschluesselt)." \
    || r_warn "kein Secrets-Bundle vorhanden (ggf. build --with-secrets)."
fi

echo "$MAJOR $HEAD $(date -u +%FT%TZ) $PKG" > "$USB_DIR/USB_RECOVERY_VERSION"
# Host-seitiger Vermerk fuer den Selfcheck (Veralterungs-Mahnung).
echo "$MAJOR $HEAD $(date -u +%FT%TZ) $PKG" > "$OUT_DIR/USB_LAST_EXPORT"
sync
r_log "USB aktuell auf Major $MAJOR (HEAD $HEAD)."
r_log "Stick abziehen und RAEUMLICH GETRENNT lagern (anderes Gebaeude)."
