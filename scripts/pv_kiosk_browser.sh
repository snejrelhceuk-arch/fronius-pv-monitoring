#!/bin/bash
# =============================================================
# pv_kiosk_browser.sh — Startet einen GPU-beschleunigten Browser,
# der automatisch die PV-API-Oberflaeche oeffnet (Display-Host).
#
# Zweck: Auf einem Host mit Bildschirm (z. B. Pi4-Failover) beim
# Boot/Login automatisch das PV-Dashboard anzeigen.
#
# Startet das App-Fenster standardmaessig MAXIMIERT (nicht echtes Vollbild),
# damit die labwc-Titelleiste (Schliessen-Button) und das Panel per
# Touch erreichbar bleiben — ein Touch-Display hat keine Tastatur fuer
# F11/ESC. Echtes Vollbild optional via PV_KIOSK_FULLSCREEN=1.
# Chromium mit nativem Wayland-Backend + V3D-GPU laeuft auf dem Pi4
# deutlich ruckelfreier (Ticker!) als Firefox.
#
# PV_KIOSK_FULLSCREEN=1  -> --start-fullscreen (nur mit Tastatur/onboard verlassbar)
# PV_KIOSK_FULLSCREEN=0  -> --start-maximized  (Default, touch-bedienbar)
#
# --password-store=basic: verhindert, dass Chromium beim Start den
# Gnome-Keyring/Secret-Service entsperren will (sonst Passwort-Dialog
# bei jedem Start). Fuer ein reines Anzeige-Dashboard ohne Logins ok.
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

# Fenstermodus: Default = maximiert (touch-bedienbar), Vollbild nur auf Wunsch.
if [ "${PV_KIOSK_FULLSCREEN:-0}" = "1" ]; then
    WINDOW_FLAG="--start-fullscreen"
else
    WINDOW_FLAG="--start-maximized"
fi

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
        --password-store=basic \
        --disable-session-crashed-bubble \
        --disable-infobars \
        --no-first-run \
        "$WINDOW_FLAG" \
        --user-data-dir="$PROFILE_DIR" \
        --app="$URL"
else
    # Fallback: Firefox — im Fenstermodus (kein --kiosk), sonst ohne Tastatur
    # nicht verlassbar. Vollbild optional via PV_KIOSK_FULLSCREEN=1.
    if [ "${PV_KIOSK_FULLSCREEN:-0}" = "1" ]; then
        exec firefox --kiosk "$URL"
    else
        exec firefox "$URL"
    fi
fi
