#!/bin/bash
# =============================================================
# install_kiosk_autologin.sh — Passwortloses Hochfahren fuer den Kiosk-Host
#
# Richtet auf einem Display-Host (Pi4-Küche, rpd-labwc/Wayland) ein, dass das
# Geraet OHNE Passwort direkt in die grafische Desktop-Sitzung bootet (Desktop-
# Autologin) und der Bildschirm NICHT abdunkelt/sperrt. Erst dadurch startet die
# User-Autostart (install_kiosk_autostart.sh) den PV-Browser ohne manuelles Login.
#
# Trennung der Zustaendigkeiten:
#   install_kiosk_autologin.sh  → SYSTEM: Autologin + Bildschirm-Blanking aus (sudo)
#   install_kiosk_autostart.sh  → USER:   Browser-/Onboard-Autostart in der Session
#
# Vorgehen (idempotent):
#   1. Desktop-Autologin via `raspi-config nonint do_boot_behaviour B4`.
#   2. Bildschirm-Blanking aus via `raspi-config nonint do_blanking 1`.
#   3. Fallback ohne raspi-config: LightDM-Autologin-Drop-In schreiben.
#
# Nutzung:  bash scripts/install_kiosk_autologin.sh
#   KIOSK_USER=<name>  Login-User ueberschreiben (Default: aktueller User).
#   Wirksam nach dem naechsten Reboot.
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Role-Guard: nur auf dem Kiosk-Host (Küche) sinnvoll ------------------
PV_ROLE_GUARD_AUTO=0 source "$SCRIPT_DIR/role_guard.sh"
if ! require_role kueche; then
    echo "❌  Nur auf dem Kiosk-Host (role=kueche) vorgesehen. Abbruch." >&2
    exit 1
fi

KIOSK_USER="${KIOSK_USER:-$(id -un)}"
echo "=== Kiosk-Autologin einrichten (User: $KIOSK_USER) ==="

configured=0

# --- 1./2. Bevorzugt raspi-config (abstrahiert die OS-Version) ------------
if command -v raspi-config >/dev/null 2>&1; then
    echo "→ raspi-config: Desktop-Autologin (B4) + Bildschirm-Blanking aus…"
    sudo raspi-config nonint do_boot_behaviour B4 && echo "  ✓ Desktop-Autologin aktiv"
    sudo raspi-config nonint do_blanking 1        && echo "  ✓ Bildschirm-Blanking deaktiviert"
    configured=1
fi

# --- 3. Fallback: LightDM-Autologin-Drop-In ------------------------------
if [ "$configured" -ne 1 ]; then
    if [ -d /etc/lightdm ]; then
        echo "→ raspi-config fehlt — LightDM-Autologin-Drop-In schreiben…"
        DROPIN=/etc/lightdm/lightdm.conf.d/20-pv-kiosk-autologin.conf
        sudo install -d -m 0755 /etc/lightdm/lightdm.conf.d
        sudo tee "$DROPIN" >/dev/null <<EOF
# PV-SYSTEM-MANAGED — Kiosk-Autologin (install_kiosk_autologin.sh)
[Seat:*]
autologin-user=$KIOSK_USER
autologin-user-timeout=0
EOF
        # Auf vielen Distributionen muss der User in der Gruppe 'autologin' sein.
        getent group autologin >/dev/null 2>&1 && sudo gpasswd -a "$KIOSK_USER" autologin || true
        echo "  ✓ LightDM-Autologin geschrieben: $DROPIN"
        configured=1
    fi
fi

if [ "$configured" -ne 1 ]; then
    echo "❌  Weder raspi-config noch LightDM gefunden — Autologin konnte nicht" >&2
    echo "    automatisch gesetzt werden. Bitte Display-Manager manuell konfigurieren." >&2
    exit 1
fi

echo ""
echo "OK: Autologin eingerichtet. Der Host bootet kuenftig OHNE Passwort in den"
echo "    Desktop; der Bildschirm bleibt an. Browser-Autostart separat:"
echo "    bash scripts/install_kiosk_autostart.sh"
echo "Wirksam nach: sudo systemctl reboot"
