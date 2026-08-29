#!/usr/bin/env bash
set -euo pipefail
# Upgrade-Skript für alle Pi-Hosts (Primary von Primary aus ausführen)

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_FILE="${PV_INFRA_FILE:-${BASE_DIR}/.infra.local}"

DRY_RUN=0
FORCE=0
for a in "$@"; do
  case "$a" in
    --dry-run|-n) DRY_RUN=1 ;;
    --force|-f) FORCE=1 ;;
    --help|-h) echo "Usage: $0 [--dry-run] [--force]"; exit 0 ;;
    *) ;;
  esac
done

if [ -f "$INFRA_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$INFRA_FILE"
  set +a
fi

# Role guard: only run from Primary
ROLE="primary"
[ -f "$BASE_DIR/.role" ] && ROLE="$(head -n1 "$BASE_DIR/.role" | tr -d '[:space:]')"
if [ "$ROLE" != "primary" ]; then
  echo "❌  Dieses Skript nur vom PRIMARY-Host ausfuehren (Rolle: $ROLE)."
  exit 1
fi

declare -a HOSTS

# Add PV_SYNC_HOSTS entries (space separated user@host)
if [ -n "${PV_SYNC_HOSTS:-}" ]; then
  for h in $PV_SYNC_HOSTS; do
    HOSTS+=("$h")
  done
fi

# helper to add unique hosts
add_host() {
  local candidate="$1"
  [ -z "$candidate" ] && return
  for e in "${HOSTS[@]:-}"; do
    [ "$e" = "$candidate" ] && return
  done
  HOSTS+=("$candidate")
}

add_host "${PV_PRIMARY_HOST:-}"
add_host "${PV_FAILOVER_HOST:-}"
add_host "${PV_PI5_BACKUP_HOST:-}"
add_host "${PV_KUECHE_HOST:-}"
add_host "${PV_WATTPILOT_HOST:-}"

TECH_USER="${PV_TECH_USER:-admin}"
TECH_IP="${PV_TECH_IP:-${PV_TECH_HOST:-192.0.2.181}}"
add_host "${TECH_USER}@${TECH_IP}"

# Ensure Primary is included as local entry if not present
PRIMARY_LOCAL_CMD=0
if [ -n "${PV_PRIMARY_HOST:-}" ]; then
  :
else
  PRIMARY_LOCAL_CMD=1
fi

if [ ${#HOSTS[@]} -eq 0 ]; then
  # Fallback: documented Pi IPs (Doku, bitte anpassen in .infra.local)
  HOSTS=("admin@192.0.2.204" "admin@192.0.2.195" "admin@192.0.2.105" "admin@192.0.2.181")
fi

echo "Hosts zur Abarbeitung: ${HOSTS[*]}"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "Dry-run: keine Aktionen werden ausgefuehrt."; exit 0
fi

if [ "$FORCE" -ne 1 ]; then
  read -r -p "Upgrade jetzt aufgelisteter Hosts ausfuehren? (j/N) " ans
  [ "$ans" = "j" ] || [ "$ans" = "J" ] || { echo "Abgebrochen."; exit 0; }
fi

# Log-Verzeichnis im Workspace (Override mit PV_UPGRADE_LOGDIR möglich)
LOGDIR="${PV_UPGRADE_LOGDIR:-${BASE_DIR}/logs}"
if ! mkdir -p "$LOGDIR" 2>/dev/null; then
  echo "Warnung: Konnte $LOGDIR nicht anlegen, Fallback auf /tmp." >&2
  LOGDIR="/tmp"
fi

LOGFILE="$LOGDIR/pv_upgrade_$(date -u +%Y%m%dT%H%M%SZ).log"
echo "Log: $LOGFILE"
exec > >(tee -a "$LOGFILE") 2>&1

# gather local IPs/hostnames for local detection
LOCAL_HOSTNAMES=("$(hostname -s)" "$(hostname -f)" "localhost" "127.0.0.1")
read -r -a LOCAL_IPS <<< "$(hostname -I 2>/dev/null || true)"

for H in "${HOSTS[@]}"; do
  echo "================================================================"
  echo "Bearbeite: $H"
  if [[ "$H" == *"@"* ]]; then
    remote_user="${H%@*}"
    remote_host="${H#*@}"
  else
    remote_user=""
    remote_host="$H"
  fi

  is_local=0
  for hn in "${LOCAL_HOSTNAMES[@]}"; do
    [ "$remote_host" = "$hn" ] && is_local=1
  done
  for ip in "${LOCAL_IPS[@]}"; do
    [ -z "$ip" ] && continue
    [[ "$remote_host" == *"$ip"* ]] && is_local=1
  done

  if [ "$is_local" -eq 1 ]; then
    echo "-> Lokales System erkannt. Führe apt update/upgrade lokal aus..."
    set +e
    sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get -y --with-new-pkgs upgrade
    sudo apt-get -y autoremove && sudo apt-get -y clean
    rc=$?
    set -e
    echo "Lokales Upgrade fertig (exit=$rc)"
    continue
  fi

  echo "-> Prüfe SSH auf $H"
  if ! ssh -o BatchMode=yes -o ConnectTimeout=8 "$H" "echo ok" >/dev/null 2>&1; then
    echo "⚠️  SSH nicht erreichbar oder Schlüssel fehlt: $H — übersprungen."
    continue
  fi

  echo "-> Starte apt update/upgrade auf $H"
  # Try non-interactive sudo first
  if ssh -o BatchMode=yes "$H" "sudo -n apt-get update && sudo -n DEBIAN_FRONTEND=noninteractive apt-get -y --with-new-pkgs upgrade && sudo -n apt-get -y autoremove && sudo -n apt-get -y clean"; then
    echo "✅  $H: Upgrade abgeschlossen."
  else
    echo "⚠️  $H: Automat. sudo fehlgeschlagen — versuche interaktive sudo (Passwort kann erforderlich sein)."
    if ssh "$H" "sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get -y --with-new-pkgs upgrade && sudo apt-get -y autoremove && sudo apt-get -y clean"; then
      echo "✅  $H: Upgrade abgeschlossen (interaktiv)."
    else
      echo "❌  $H: Upgrade fehlgeschlagen."
    fi
  fi
done

echo "Alle Host-Durchläufe abgeschlossen. Log: $LOGFILE"
