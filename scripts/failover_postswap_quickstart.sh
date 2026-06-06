#!/bin/bash
# Quickstart provisioning for a freshly installed 64bit failover host.
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
TARGET_HOSTNAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hostname)
      TARGET_HOSTNAME="${2:-}"
      shift 2
      ;;
    *)
      echo "Usage: $0 [--hostname <name>]" >&2
      exit 1
      ;;
  esac
done

if [[ -n "$TARGET_HOSTNAME" ]]; then
  echo "Setting hostname to $TARGET_HOSTNAME"
  sudo hostnamectl set-hostname "$TARGET_HOSTNAME"
fi

echo "Installing base packages for failover operation"
sudo apt update
sudo apt install -y git rsync sqlite3 python3 python3-venv python3-pip curl wget jq ripgrep tmux tree

echo "Setting host role to failover"
echo "failover" > "$BASE/.role"

if [[ ! -f "$BASE/.infra.local" ]]; then
  echo "Creating local infra skeleton (.infra.local)"
  cp "$BASE/.infra.local.example" "$BASE/.infra.local"
  echo "NOTE: Fill local values in .infra.local before production use."
fi

echo "Installing failover services and timers"
bash "$BASE/scripts/install_failover_services.sh"

echo "Forcing passive failover mode"
bash "$BASE/scripts/failover_passive.sh"

echo "Running network capability check"
bash "$BASE/scripts/check_network_capabilities.sh"

echo "Done. Verify with:"
echo "  systemctl status pv-mirror-sync.timer --no-pager"
echo "  systemctl status pv-failover-health.timer --no-pager"
echo "  systemctl status pv-web.service --no-pager"
