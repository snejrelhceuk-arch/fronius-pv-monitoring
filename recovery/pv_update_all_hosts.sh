#!/bin/bash
# ============================================================
# recovery/pv_update_all_hosts.sh
# Koordinierter Voll-Upgrade-Rollout ueber ALLE erreichbaren PV-Hosts.
#
# Fuehrt auf jedem Host `scripts/pv_maintenance_upgrade.sh --yes` aus (persistiert
# zuerst die tmpfs-DB, dann `apt full-upgrade`, pip NUR Report, KEIN Auto-Reboot).
# Lokaler Host (Primary) direkt; Peers via SSH + `sudo -n`.
#
# Nutzung:
#   sudo bash recovery/pv_update_all_hosts.sh            # alle Hosts live
#   sudo bash recovery/pv_update_all_hosts.sh --dry-run  # nur anzeigen, nichts tun
#   sudo bash recovery/pv_update_all_hosts.sh --hosts "primary fb"   # Teilmenge
#
# Nur auf Primary sinnvoll (Quelle der Wahrheit). Reboot-Hinweise werden je Host
# gemeldet, NIE automatisch ausgefuehrt. Exit 0 auch bei Teilfehlern — die
# Zusammenfassung (STDOUT) nennt pro Host OK/FEHLER/REBOOT. Maschinenlesbare
# Statuszeilen beginnen mit "RESULT ".
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1090
[ -f "$BASE/.infra.local" ] && { set -a; . "$BASE/.infra.local"; set +a; }

DRY=""
HOST_FILTER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY="1" ;;
    --hosts) shift; HOST_FILTER="${1:-}" ;;
    *) echo "Unbekannter Parameter: $1" >&2; exit 2 ;;
  esac
  shift
done

REMOTE_REPO="${PV_SYNC_REMOTE_PATH:-$BASE}"
UPGRADE_REL="scripts/pv_maintenance_upgrade.sh"

want() { [ -z "$HOST_FILTER" ] || echo " $HOST_FILTER " | grep -q " $1 "; }

# host-spec: name|user@ip  (leer = lokal)
HOSTS=()
want primary && HOSTS+=("primary|")
if want fb && [ -n "${PV_FAILOVER_IP:-}" ]; then HOSTS+=("fb|${PV_FAILOVER_USER:-admin}@${PV_FAILOVER_IP}"); fi
if want tech && [ -n "${PV_TECH_IP:-}" ]; then HOSTS+=("tech|${PV_TECH_USER:-admin}@${PV_TECH_IP}"); fi
if want kueche && [ -n "${PV_KUECHE_IP:-}" ]; then HOSTS+=("kueche|${PV_KUECHE_USER:-jk}@${PV_KUECHE_IP}"); fi

echo "=== PV Multi-Host Upgrade-Rollout $(date '+%F %T') ==="
[ -n "$DRY" ] && echo "(DRY-RUN — es wird nichts veraendert)"

OVERALL_FAIL=0

run_host() {
  local name="$1" target="$2" out rc reboot
  echo ""
  echo "----- Host: $name ${target:+($target)} -----"
  if [ -n "$DRY" ]; then
    if [ -z "$target" ]; then
      echo "  wuerde ausfuehren: $BASE/$UPGRADE_REL --yes"
    else
      echo "  wuerde ausfuehren (ssh): sudo -n bash $REMOTE_REPO/$UPGRADE_REL --yes"
    fi
    echo "RESULT $name DRYRUN"
    return 0
  fi
  if [ -z "$target" ]; then
    # Lokal (Primary) — braucht root
    if [ "$EUID" -ne 0 ]; then
      out="$(sudo -n bash "$BASE/$UPGRADE_REL" --yes 2>&1)"; rc=$?
    else
      out="$(bash "$BASE/$UPGRADE_REL" --yes 2>&1)"; rc=$?
    fi
    reboot="$( [ -f /var/run/reboot-required ] && echo yes || echo no )"
  else
    out="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "$target" \
            "sudo -n bash '$REMOTE_REPO/$UPGRADE_REL' --yes 2>&1; \
             [ -f /var/run/reboot-required ] && echo __REBOOT_REQUIRED__" 2>&1)"; rc=$?
    reboot="$(echo "$out" | grep -q __REBOOT_REQUIRED__ && echo yes || echo no)"
  fi
  echo "$out" | tail -n 12 | sed 's/^/  | /'
  if [ "$rc" -ne 0 ]; then
    OVERALL_FAIL=1
    echo "RESULT $name FEHLER rc=$rc reboot=$reboot"
  elif [ "$reboot" = "yes" ]; then
    echo "RESULT $name OK-REBOOT-NOETIG"
  else
    echo "RESULT $name OK"
  fi
}

for spec in "${HOSTS[@]}"; do
  run_host "${spec%%|*}" "${spec#*|}"
done

echo ""
echo "=== Rollout abgeschlossen (Sammel-Status: $([ $OVERALL_FAIL -eq 0 ] && echo OK || echo 'mit Fehlern')) ==="
exit 0
