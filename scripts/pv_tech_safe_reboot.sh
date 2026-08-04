#!/bin/bash
# ============================================================
# scripts/pv_tech_safe_reboot.sh — sicherer Reboot von Pi4-Tech (Rolle N).
#
# Tech haelt die PAC4200-NQ-DB RAM-first (tmpfs, KEIN SD-Persist wie Primary).
# Vor dem Reboot wird der Transfer Tech->Primary erzwungen, damit die 5min-
# Aggregate + Events dauerhaft auf Primary-SD liegen (Rohdaten 200ms/1s sind
# bauartbedingt fluechtig und gehen bewusst verloren).
#
# VON PRIMARY ausfuehren. Analog zum tmpfs-Persist auf Primary, aber fuer das
# Pull-Transfermodell der Rolle N.
#
#   sudo bash scripts/pv_tech_safe_reboot.sh          # Flush + Reboot
#   bash scripts/pv_tech_safe_reboot.sh --flush-only  # nur Flush, kein Reboot
# ============================================================
set -uo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
set -a; . "${BASE}/.infra.local" 2>/dev/null; set +a
TECH_IP="${PV_TECH_IP:-192.0.2.181}"
TECH_USER="${PV_TECH_USER:-admin}"
TECH="${TECH_USER}@${TECH_IP}"

FLUSH_ONLY=0
for a in "$@"; do [[ "$a" == "--flush-only" ]] && FLUSH_ONLY=1; done

echo "=== Sicherer Tech-Reboot ($TECH) ==="
echo "1) NQ-Flush (Primary zieht alle anhaengigen Daten von Tech)…"
bash "${BASE}/scripts/pv_nq_flush.sh" 12

if [[ "$FLUSH_ONLY" -eq 1 ]]; then
  echo "2) --flush-only gesetzt -> KEIN Reboot."
  exit 0
fi

echo "2) Reboot Tech…"
if ssh -o BatchMode=yes -o ConnectTimeout=8 "$TECH" "sudo -n systemctl reboot" 2>/dev/null; then
  echo "   Reboot ausgeloest. Tech ist ~1-2 min offline; Poller startet per systemd wieder."
else
  echo "   FEHLER: Reboot-Trigger fehlgeschlagen. Tech manuell pruefen."
  exit 1
fi
