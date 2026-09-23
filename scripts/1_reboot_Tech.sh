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

# ── NQ-Datenrettung: die ohnehin vorgesehene Verarbeitung VOR dem Reboot vorziehen ──
# Tech hält die PAC4200-NQ-Aggregate RAM-first (tmpfs, kein SD-Persist). Der
# reguläre Pull läuft nur alle 4h → ohne Flush gängen bis zu 4h 5min-Aggregate
# beim Reboot verloren. pv_nq_flush.sh zieht sie jetzt sofort auf Primary-SD.
_nq_latest_5min() {
    python3 - "$REPO_ROOT" <<'PY' 2>/dev/null || echo 0
import sqlite3, glob, os, sys
dbs = sorted(glob.glob(os.path.join(sys.argv[1], 'nq', 'db', 'nq_*.db')))
if not dbs:
    print(0); raise SystemExit
try:
    c = sqlite3.connect(f'file:{dbs[-1]}?mode=ro', uri=True, timeout=5)
    print(int(c.execute('SELECT COALESCE(MAX(ts),0) FROM nq_5min').fetchone()[0]))
except Exception:
    print(0)
PY
}
before="$(_nq_latest_5min)"
echo "→ NQ-Flush (Tech→Primary) vor dem Reboot — sichert die tmpfs-5min-Aggregate…"
bash "$SCRIPT_DIR/pv_nq_flush.sh" 12
after="$(_nq_latest_5min)"
if [ "${after:-0}" -gt "${before:-0}" ] 2>/dev/null; then
    echo "  ✓ NQ-5min-Aggregate gesichert bis $(date -d "@$after" '+%F %T' 2>/dev/null)"
else
    echo "  ℹ NQ-5min-Stand unverändert — nichts Neues zu transferieren."
fi

reboot_remote_host "Tech" "$TECH" \
    pv-nq-poller.service pv-nq-energy.service pv-wp-bridge.service
exit $?
