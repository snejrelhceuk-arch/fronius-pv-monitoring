#!/bin/bash
set -euo pipefail

PRIMARY_IP="${PRIMARY_IP:-192.168.2.181}"
PRIMARY_WEB_PORT="${PRIMARY_WEB_PORT:-8000}"
MAX_SYNC_AGE_SEC="${MAX_SYNC_AGE_SEC:-600}"
STATE_DIR="/var/lib/pv-system"
LOG_FILE="/tmp/pv_failover_health.log"
RECOMMEND_FILE="${STATE_DIR}/failover_recommendation"

mkdir -p "$STATE_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

reason=""
ping_ok=0
api_ok=0
sync_ok=0

if ping -c 1 -W 2 "$PRIMARY_IP" >/dev/null 2>&1; then
  ping_ok=1
fi

if curl -fsS --max-time 3 "http://${PRIMARY_IP}:${PRIMARY_WEB_PORT}/api/system_info" >/dev/null 2>&1; then
  api_ok=1
fi

sync_age=$(python3 - <<'PY'
import os, time
p='/home/admin/Dokumente/PVAnlage/pv-system/data.db'
if os.path.exists(p):
    print(int(time.time()-os.path.getmtime(p)))
else:
    print(999999)
PY
)

if [ "$sync_age" -le "$MAX_SYNC_AGE_SEC" ]; then
  sync_ok=1
fi

if [ "$ping_ok" -eq 0 ] && [ "$api_ok" -eq 0 ]; then
  reason="primär nicht erreichbar (ping+api)"
elif [ "$api_ok" -eq 0 ]; then
  reason="primär-api nicht erreichbar"
elif [ "$sync_ok" -eq 0 ]; then
  reason="lokaler mirror veraltet (${sync_age}s)"
fi

if [ -n "$reason" ]; then
  msg="FAILOVER-EMPFEHLUNG: ${reason}. Prüfen und ggf. aktivieren: /home/admin/Dokumente/PVAnlage/pv-system/scripts/failover_activate.sh"
  echo "$msg" > "$RECOMMEND_FILE"
  log "WARN $msg"
  exit 1
fi

rm -f "$RECOMMEND_FILE"
log "OK primär erreichbar, mirror aktuell (${sync_age}s)"
exit 0
