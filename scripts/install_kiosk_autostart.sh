#!/bin/bash
# =============================================================
# install_kiosk_autostart.sh — Browser-Autostart fuer das PV-Dashboard
#
# Richtet auf einem Display-Host (z. B. Pi4-Failover, rpd-labwc/Wayland)
# den automatischen Browser-Start beim Login ein. Idempotent.
#
# Mechanik: schreibt ~/.config/labwc/autostart so, dass nach dem Start
# der Desktop-Basis pv_kiosk_browser.sh ausgefuehrt wird.
#
# Nutzung:  bash scripts/install_kiosk_autostart.sh
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCHER="$SCRIPT_DIR/pv_kiosk_browser.sh"
chmod +x "$LAUNCHER"

AUTOSTART_DIR="${HOME}/.config/labwc"
AUTOSTART="${AUTOSTART_DIR}/autostart"
mkdir -p "$AUTOSTART_DIR"

# Vorhandene Desktop-Basiszeile von Raspberry Pi OS erhalten, falls vorhanden.
if [ ! -f "$AUTOSTART" ]; then
    if [ -f /etc/xdg/labwc/autostart ]; then
        cp /etc/xdg/labwc/autostart "$AUTOSTART"
    else
        : > "$AUTOSTART"
    fi
fi

MARKER="# >>> pv-kiosk-autostart >>>"
ENDMARK="# <<< pv-kiosk-autostart <<<"

# Alten Block entfernen (idempotent), dann neu anhaengen.
if grep -qF "$MARKER" "$AUTOSTART"; then
    sed -i "/$MARKER/,/$ENDMARK/d" "$AUTOSTART"
fi

cat >>"$AUTOSTART" <<EOF
$MARKER
# Automatischer Start des PV-Dashboards (GPU-beschleunigtes Browser-Fenster).
$LAUNCHER &
$ENDMARK
EOF

echo "OK: Autostart eingerichtet in $AUTOSTART"
echo "Launcher: $LAUNCHER"
echo "Wirksam nach naechstem Login/Reboot (Autologin-Session)."
