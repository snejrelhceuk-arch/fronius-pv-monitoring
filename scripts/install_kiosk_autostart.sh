#!/bin/bash
# =============================================================
# install_kiosk_autostart.sh — Browser-Autostart fuer das PV-Dashboard
#
# Richtet auf einem Display-Host (Pi4-Küche, rpd-labwc/Wayland)
# den automatischen Browser-Start beim Login ein. Idempotent.
#
# WICHTIG (labwc-pi): Raspberry Pi OS startet SOWOHL die System-Autostart
# (/etc/xdg/labwc/autostart, liefert Panel/Dateimanager) ALS AUCH die
# User-Autostart (~/.config/labwc/autostart). Die User-Datei darf daher
# NUR eigene Zeilen enthalten — NICHT die System-Zeilen kopieren, sonst
# starten Panel (wf-panel-pi) und Dateimanager (pcmanfm-pi) doppelt
# ("doppelte Taskleiste").
#
# Diese User-Autostart startet:
#   - das PV-Dashboard im Vollbild (pv_kiosk_browser.sh)
#   - die On-Screen-Keyboard 'onboard' mit verschiebbarem Floating-Icon
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

# User-Autostart enthaelt NUR eigene Zeilen (labwc-pi laeuft system+user).
# Falls die Datei frueher faelschlich eine Kopie der System-Autostart war,
# wird sie hier auf den reinen pv-Block reduziert.
: > "$AUTOSTART"

cat >>"$AUTOSTART" <<EOF
# >>> pv-kiosk-autostart >>>
# On-Screen-Keyboard (verschiebbar, mit F-/Pfeiltasten); blendet ein kleines
# Floating-Icon zum Ein-/Ausblenden ein, statt die Tastatur dauerhaft zu zeigen.
onboard &
# Automatischer Start des PV-Dashboards (GPU-beschleunigtes Browser-Fenster, Vollbild).
$LAUNCHER &
# <<< pv-kiosk-autostart <<<
EOF

echo "OK: User-Autostart (nur pv-Zeilen) geschrieben: $AUTOSTART"
echo "Launcher: $LAUNCHER"
echo "Panel/Dateimanager kommen weiterhin aus /etc/xdg/labwc/autostart (System)."
echo "Wirksam nach naechstem Login/Reboot (Autologin-Session)."
