#!/bin/bash
# ============================================================
# 2_reboot_K.sh — Pi4-Küche (Kiosk-Display + Longterm-GFS-Backup)
# kontrolliert neu starten und selbstprüfend verifizieren.
# Von Primary ausführen. Reihenfolge: 1) Tech 2) Küche 3) FB 4) Primary.
#
# Hinweis: Das Kiosk-Display ist eine grafische Autostart-Sitzung (kein
# pv-*-Dienst) — nach dem Boot bitte zusätzlich den Touch-Screen sichten.
# ============================================================
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load_infra_env.sh"
source "$SCRIPT_DIR/_reboot_remote_host.sh"

KUECHE="${PV_KUECHE_HOST:?PV_KUECHE_HOST nicht gesetzt (.infra.local)}"

reboot_remote_host "Küche" "$KUECHE" \
    pv-failover-init.service pv-backup-2d.timer pv-failover-health.timer
rc=$?
echo "  ℹ  Kiosk-Anzeige (Touch-Screen) bitte visuell prüfen."
exit $rc
