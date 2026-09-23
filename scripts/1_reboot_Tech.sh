#!/bin/bash
# ============================================================
# 1_reboot_Tech.sh — Pi4-Tech (WP-Bridge + NQ-Collector, Rolle N)
# kontrolliert neu starten und selbstprüfend verifizieren.
# Von Primary ausführen. Reihenfolge: 1) Tech 2) Küche 3) FB 4) Primary.
# ============================================================
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load_infra_env.sh"
source "$SCRIPT_DIR/_reboot_remote_host.sh"

TECH="${PV_TECH_USER:-admin}@${PV_TECH_IP:-192.0.2.181}"

reboot_remote_host "Tech" "$TECH" \
    pv-nq-poller.service pv-nq-energy.service pv-wp-bridge.service
exit $?
