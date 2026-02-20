#!/bin/bash
# =============================================================
# Role Guard — zentrale Rollenprüfung für alle Shell-Scripts
# =============================================================
#
# Nutzung in Cron-Jobs und Monitor-Scripts:
#   source "$(dirname "$0")/scripts/role_guard.sh" || exit 0
#   # Ab hier: nur primary-Code
#
# Oder mit explizitem Pfad:
#   source /srv/pv-system/scripts/role_guard.sh || exit 0
#
# Funktionsweise:
#   - Liest .role-Datei im Repo-Root
#   - Wenn Rolle = "failover" → return 1 (→ exit 0 im Aufrufer)
#   - Wenn Rolle = "primary"  → return 0 (Script läuft weiter)
#   - Wenn .role fehlt         → return 0 (Default = primary, sicher)
#
# Die .role-Datei ist gitignored — jeder Host hat seine eigene.
# Siehe doc/DUAL_HOST_ARCHITECTURE.md für Details.
# =============================================================

# Auto-detect: Script-Verzeichnis → Repo-Root (user-agnostisch)
_ROLE_GUARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
_ROLE_FILE="${ROLE_FILE:-${_ROLE_GUARD_DIR}/.role}"

get_role() {
    if [ -f "$_ROLE_FILE" ]; then
        head -1 "$_ROLE_FILE" | tr -d '[:space:]'
    else
        echo "primary"
    fi
}

PV_ROLE="$(get_role)"

# Guard: Wenn failover → return 1 (Aufrufer sieht Fehler → exit 0)
if [ "$PV_ROLE" = "failover" ]; then
    return 1 2>/dev/null || exit 0
fi
