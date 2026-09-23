#!/bin/bash
# ============================================================
# 3_reboot_FB.sh — Pi5-FB (Failover, read-only Web + Ticker + Backup-Empfang)
# kontrolliert neu starten und selbstprüfend verifizieren.
# Von Primary ausführen. Reihenfolge: 1) Tech 2) Küche 3) FB 4) Primary.
#
# Zusatzprüfung: nach dem Boot muss der tmpfs-DB-Mirror
# (/dev/shm/fronius_data.db) über den Mirror-Sync-Timer (OnBootSec) wieder
# entstehen — sonst ist der Failover nicht übernahmebereit.
# ============================================================
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load_infra_env.sh"
source "$SCRIPT_DIR/_reboot_remote_host.sh"

FB="${PV_FAILOVER_HOST:?PV_FAILOVER_HOST nicht gesetzt (.infra.local)}"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=8"

reboot_remote_host "FB" "$FB" \
    pv-web.service pv-ticker.service pv-failover-init.service pv-mirror-sync.timer
rc=$?

# --- Failover-Übernahmebereitschaft: tmpfs-Mirror wieder da? ---
echo "  → prüfe tmpfs-Mirror (/dev/shm/fronius_data.db) …"
mirror_ok=0
for _ in $(seq 1 12); do   # bis ~120s: OnBootSec-Timer + erster Sync
    if $SSH "$FB" "test -f /dev/shm/fronius_data.db" 2>/dev/null; then
        age=$($SSH "$FB" "echo \$(( (\$(date +%s) - \$(stat -c %Y /dev/shm/fronius_data.db)) / 60 ))" 2>/dev/null)
        echo "  ✓ tmpfs-Mirror vorhanden (Alter ${age} min) — Failover übernahmebereit"
        mirror_ok=1; break
    fi
    sleep 10
done
if [ "$mirror_ok" -ne 1 ]; then
    echo "  ✗ tmpfs-Mirror kam nicht zurück — Failover NICHT übernahmebereit!"
    echo "    Prüfen: $SSH $FB 'systemctl status pv-mirror-sync.timer; journalctl -u pv-mirror-sync -n 20'"
    rc=1
fi
exit $rc
