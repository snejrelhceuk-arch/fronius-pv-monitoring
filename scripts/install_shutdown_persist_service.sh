#!/bin/bash
# Installiert den Shutdown-Persist-Hook für die RAM-DB.

set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_SRC="${BASE_DIR}/config/systemd/pv-shutdown-persist.service"
UNIT_DST="/etc/systemd/system/pv-shutdown-persist.service"

if [[ ! -f "$UNIT_SRC" ]]; then
    echo "Unit-Datei fehlt: $UNIT_SRC" >&2
    exit 1
fi

echo "Installiere pv-shutdown-persist.service ..."
sudo cp "$UNIT_SRC" "$UNIT_DST"
sudo chmod 644 "$UNIT_DST"
sudo chmod +x "${BASE_DIR}/scripts/persist_on_shutdown.sh"

sudo systemctl daemon-reload
sudo systemctl enable pv-shutdown-persist.service

echo "Status:" 
systemctl is-enabled pv-shutdown-persist.service

echo "Fertig. Testlauf (ohne Reboot):"
echo "  /bin/bash ${BASE_DIR}/scripts/persist_on_shutdown.sh"
