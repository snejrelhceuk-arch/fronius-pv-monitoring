#!/bin/bash
# =============================================================
# pv_kiosk_browser.sh — Startet einen GPU-beschleunigten Browser,
# der automatisch die PV-API-Oberflaeche oeffnet (Display-Host).
#
# Zweck: Auf einem Host mit Bildschirm (z. B. Pi4-Failover) beim
# Boot/Login automatisch das PV-Dashboard anzeigen.
#
# KEIN harter Kiosk-Lockdown — bewusst nur Auto-Start mit App-Fenster.
# Chromium mit nativem Wayland-Backend + V3D-GPU laeuft auf dem Pi4
# deutlich ruckelfreier (Ticker!) als Firefox.
#
# URL ueberschreibbar:  PV_KIOSK_URL=http://host:8000 ./pv_kiosk_browser.sh
# Default kommt aus .infra.local (PV_PRIMARY_IP) oder Fallback unten.
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Infra-Env laden (liefert ggf. PV_PRIMARY_IP), Fehler tolerieren
if [ -f "$SCRIPT_DIR/load_infra_env.sh" ]; then
    # shellcheck disable=SC1090
    source "$SCRIPT_DIR/load_infra_env.sh" 2>/dev/null || true
fi

PRIMARY_IP="${PV_PRIMARY_IP:-192.0.2.181}"
URL="${PV_KIOSK_URL:-http://${PRIMARY_IP}:8000}"

# Browser ermitteln (Chromium bevorzugt — effizienter auf Pi4)
BROWSER=""
for b in chromium chromium-browser; do
    if command -v "$b" >/dev/null 2>&1; then BROWSER="$b"; break; fi
done

# Display-Cache pro Profil getrennt halten (verhindert "restore session"-Popups)
PROFILE_DIR="${HOME}/.config/pv-kiosk-chromium"
mkdir -p "$PROFILE_DIR"

if [ -n "$BROWSER" ]; then
    # Auf das Web-API warten, bevor der Browser oeffnet (max ~60 s)
    for _ in $(seq 1 30); do
        if curl -fsS -o /dev/null --max-time 2 "$URL"; then break; fi
        sleep 2
    done

    # "Sitzung wiederherstellen?"-Dialog nach hartem Reboot unterdruecken
    PREFS="$PROFILE_DIR/Default/Preferences"
    if [ -f "$PREFS" ]; then
        sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/; s/"exited_cleanly":false/"exited_cleanly":true/' "$PREFS" 2>/dev/null || true
    fi

    exec "$BROWSER" \
        --ozone-platform=wayland \
        --enable-features=UseOzonePlatform \
        --ignore-gpu-blocklist \
        --enable-gpu-rasterization \
        --enable-zero-copy \
        --disable-session-crashed-bubble \
        --disable-infobars \
        --no-first-run \
        --start-maximized \
        --user-data-dir="$PROFILE_DIR" \
        --app="$URL"
else
    # Fallback: Firefox, falls kein Chromium vorhanden
    exec firefox --new-window "$URL"
fi
