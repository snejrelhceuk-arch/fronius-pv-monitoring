#!/bin/bash
# =============================================================
# Role Guard — zentrale Rollenprüfung für alle Shell-Scripts
# =============================================================
#
# Nutzung in Cron-Jobs und Monitor-Scripts:
#   source "$(dirname "$0")/scripts/role_guard.sh" || exit 0
#   require_primary || exit 0
#   # Ab hier: nur primary-Code
#
# Nur Funktionen laden (z. B. fuer Tech-Jobs):
#   PV_ROLE_GUARD_AUTO=0 source "$(dirname "$0")/scripts/role_guard.sh"
#   require_role tech || exit 0
#
# Oder mit explizitem Pfad:
#   source /srv/pv-system/scripts/role_guard.sh || exit 0
#
# Funktionsweise:
#   - Liest .role-Datei im Repo-Root
#   - bekannte Rollen: primary, failover, tech, kueche
#   - wenn .role fehlt: Default = primary
#   - vorhandene unbekannte .role: unknown, nie primary
#
# Die .role-Datei ist gitignored — jeder Host hat seine eigene.
# Siehe doc/DUAL_HOST_ARCHITECTURE.md für Details.
# =============================================================

# Auto-detect: Script-Verzeichnis → Repo-Root (user-agnostisch)
_ROLE_GUARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
_ROLE_FILE="${ROLE_FILE:-${_ROLE_GUARD_DIR}/.role}"

get_role() {
    if [ -f "$_ROLE_FILE" ]; then
        local role
        role="$(head -1 "$_ROLE_FILE" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
        case "$role" in
            primary|failover|tech|kueche) echo "$role" ;;
            *) echo "unknown" ;;
        esac
    else
        echo "primary"
    fi
}

PV_ROLE="$(get_role)"

require_role() {
    local wanted
    for wanted in "$@"; do
        if [ "$PV_ROLE" = "$wanted" ]; then
            return 0
        fi
    done
    echo "role=${PV_ROLE} -> required one of: $*" >&2
    return 1
}

require_primary() {
    require_role primary
}

# Kompatibilitaet: bestehende Aufrufer mit `source ... || exit 0` bleiben Primary-only.
if [ "${PV_ROLE_GUARD_AUTO:-1}" != "0" ]; then
    require_primary || return 1 2>/dev/null || exit 0
fi
