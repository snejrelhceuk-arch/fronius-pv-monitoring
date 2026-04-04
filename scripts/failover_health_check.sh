#!/bin/bash
set -euo pipefail

_SCRIPT_BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "${_SCRIPT_BASE}/scripts/load_infra_env.sh"

# Auf dem Primary-Host prüft dieses Script seine eigene Erreichbarkeit –
# die Mirror-Sync-Prüfung ist nur auf dem Failover sinnvoll.
# Primary: nur Ping+API prüfen, Mirror-Age ignorieren.
ROLE_FILE="${_SCRIPT_BASE}/.role"
IS_PRIMARY=true
if [ -f "$ROLE_FILE" ]; then
  ROLE_CONTENT=$(head -1 "$ROLE_FILE" | tr '[:upper:]' '[:lower:]')
  [ "$ROLE_CONTENT" = "failover" ] && IS_PRIMARY=false
fi

PRIMARY_IP="${PRIMARY_IP:-${PV_PRIMARY_IP:-192.0.2.181}}"
PRIMARY_WEB_PORT="${PRIMARY_WEB_PORT:-8000}"
MAX_SYNC_AGE_SEC="${MAX_SYNC_AGE_SEC:-660}"  # 660s > 10-Min-Sync-Intervall, verhindert Knappheits-WARNs
STATE_DIR="${STATE_DIR:-${_SCRIPT_BASE}/.state}"
LOG_FILE="/tmp/pv_failover_health.log"
RECOMMEND_FILE="${STATE_DIR}/failover_recommendation"
SYNC_MARKER_FILE="${STATE_DIR}/last_mirror_sync.ok"
ALARM_SENT_FILE="${STATE_DIR}/failover_alarm_sent"

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

  # Mail-Alarm nur vom Failover, dedupliziert 1× pro Tag
  if [ "$IS_PRIMARY" = false ]; then
    TODAY=$(date '+%Y-%m-%d')
    LAST_SENT=""
    [ -f "$ALARM_SENT_FILE" ] && LAST_SENT=$(cat "$ALARM_SENT_FILE" 2>/dev/null)

    if [ "$LAST_SENT" != "$TODAY" ]; then
      python3 - "$reason" "${PV_NOTIFICATION_EMAIL:-}" "${PV_NOTIFICATION_SMTP_HOST:-}" \
        "${PV_NOTIFICATION_SMTP_USER:-}" "${_SCRIPT_BASE}" <<'PYMAIL'
import sys, smtplib, socket, os
from email.mime.text import MIMEText
from datetime import datetime

reason, to_addr, smtp_host, smtp_user, base_dir = sys.argv[1:6]
if not to_addr or not smtp_host:
    print("SMTP nicht konfiguriert, keine Mail", file=sys.stderr)
    sys.exit(0)

# Passwort aus credential_store (gleicher Pfad wie Primary)
smtp_pass = None
for p in ['/etc/pv-system/smtp_pass.key', os.path.join(base_dir, '.credentials', 'smtp_pass.key')]:
    if os.path.isfile(p):
        smtp_pass = open(p).read().strip()
        break
if not smtp_pass:
    print("SMTP-Passwort nicht gefunden", file=sys.stderr)
    sys.exit(1)

hostname = socket.gethostname()
now_str = datetime.now().strftime('%d.%m.%Y %H:%M')
body = (
    f"FAILOVER-ALARM von {hostname}\n"
    f"Zeitpunkt: {now_str}\n\n"
    f"Primary-System NICHT erreichbar!\n"
    f"Grund: {reason}\n\n"
    f"Empfehlung: System prüfen, ggf. Failover aktivieren.\n"
    f"\nDiese Meldung wird 1x pro Tag gesendet.\n"
)

msg = MIMEText(body, 'plain', 'utf-8')
msg['Subject'] = f'[PV-System ALARM] Primary nicht erreichbar — {reason}'
msg['From'] = smtp_user
msg['To'] = to_addr

try:
    smtp = smtplib.SMTP_SSL(smtp_host, 465, timeout=15)
    smtp.login(smtp_user, smtp_pass)
    smtp.sendmail(smtp_user, [to_addr], msg.as_string())
    smtp.quit()
    print(f"Failover-Alarm gesendet → {to_addr}")
except Exception as e:
    print(f"Mail-Versand fehlgeschlagen: {e}", file=sys.stderr)
    sys.exit(1)
PYMAIL

      if [ $? -eq 0 ]; then
        echo "$TODAY" > "$ALARM_SENT_FILE"
        log "ALARM Mail gesendet: ${reason}"
      fi
    else
      log "ALARM bereits heute gesendet, unterdrückt"
    fi
  fi

  exit 1
fi

# Alles OK → Alarm-Sperre aufheben (damit morgen erneut gemeldet wird)
rm -f "$RECOMMEND_FILE" "$ALARM_SENT_FILE"
log "OK primär erreichbar, mirror aktuell (${sync_age}s)"
exit 0
