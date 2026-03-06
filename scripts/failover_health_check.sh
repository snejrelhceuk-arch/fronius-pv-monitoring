#!/bin/bash
set -euo pipefail

_SCRIPT_BASE="$(cd "$(dirname "$0")/.." && pwd)"

# Auf dem Primary-Host prüft dieses Script seine eigene Erreichbarkeit –
# die Mirror-Sync-Prüfung ist nur auf dem Failover sinnvoll.
# Primary: nur Ping+API prüfen, Mirror-Age ignorieren.
ROLE_FILE="${_SCRIPT_BASE}/.role"
IS_PRIMARY=true
if [ -f "$ROLE_FILE" ]; then
  ROLE_CONTENT=$(head -1 "$ROLE_FILE" | tr '[:upper:]' '[:lower:]')
  [ "$ROLE_CONTENT" = "failover" ] && IS_PRIMARY=false
fi

PRIMARY_IP="${PRIMARY_IP:-192.168.2.181}"
PRIMARY_WEB_PORT="${PRIMARY_WEB_PORT:-8000}"
MAX_SYNC_AGE_SEC="${MAX_SYNC_AGE_SEC:-660}"  # 660s > 10-Min-Sync-Intervall, verhindert Knappheits-WARNs
STATE_DIR="${STATE_DIR:-${_SCRIPT_BASE}/.state}"
LOG_FILE="/tmp/pv_failover_health.log"
RECOMMEND_FILE="${STATE_DIR}/failover_recommendation"
SYNC_MARKER_FILE="${STATE_DIR}/last_mirror_sync.ok"

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

sync_ok=0

# Mirror-Age nur auf dem Failover prüfen — Primary hat keinen Mirror-Sync
if [ "$IS_PRIMARY" = true ]; then
  sync_ok=1
  sync_age=0
else
  sync_age=$(python3 - "$SYNC_MARKER_FILE" "${_SCRIPT_BASE}/data.db" <<'PY'
import os, sys, time
marker = sys.argv[1]
db = sys.argv[2]
if os.path.exists(marker):
  print(int(time.time()-os.path.getmtime(marker)))
elif os.path.exists(db):
  print(int(time.time()-os.path.getmtime(db)))
else:
    print(999999)
PY
)

  if [ "$sync_age" -le "$MAX_SYNC_AGE_SEC" ]; then
    sync_ok=1
  fi
fi

if [ "$ping_ok" -eq 0 ] && [ "$api_ok" -eq 0 ]; then
  reason="primär nicht erreichbar (ping+api)"
elif [ "$api_ok" -eq 0 ]; then
  reason="primär-api nicht erreichbar"
elif [ "$sync_ok" -eq 0 ]; then
  reason="lokaler mirror veraltet (${sync_age}s)"
fi

if [ -n "$reason" ]; then
  msg="FAILOVER-EMPFEHLUNG: ${reason}. Prüfen und ggf. aktivieren: ${_SCRIPT_BASE}/scripts/failover_activate.sh"
  echo "$msg" > "$RECOMMEND_FILE"
  log "WARN $msg"
  exit 1
fi

rm -f "$RECOMMEND_FILE"
log "OK primär erreichbar, mirror aktuell (${sync_age}s)"
exit 0
