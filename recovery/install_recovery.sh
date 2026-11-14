#!/bin/bash
# ============================================================
# recovery/install_recovery.sh — Rolle-R-Timer installieren (nur Primary)
#   pv-auto-update.{service,timer}        taeglich  — 72h-Gate + Multi-Host-Rollout
#                                                     (Update/Upgrade-Strategie)
#   pv-recovery-selfcheck.{service,timer} woechentl. — Paket/USB-Aktualitaet (Major)
#   pv-offsite-reminder.{service,timer}   monatlich — Off-site-Datensicherungs-Mahnung
#
# Idempotent (install -m 0644 + daemon-reload + enable --now), Konvention wie
# scripts/install_nq_services.sh. Alle Timer Persistent=true (neustart-fest).
# Baut zudem beim ersten Lauf ein Recovery-Paket, falls noch keins existiert.
#
# Aufruf: bash recovery/install_recovery.sh
# ============================================================
set -euo pipefail
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE="$(cd "$SELF_DIR/.." && pwd)"
SRC="$BASE/config/systemd"
DST="/etc/systemd/system"

PV_ROLE_GUARD_AUTO=0 source "${BASE}/scripts/role_guard.sh"
ROLE="$PV_ROLE"
echo "=== Rolle-R-Timer installieren (Rolle: $ROLE) ==="
if [ "$ROLE" != "primary" ]; then
  echo "Nur auf Primary vorgesehen. Nichts zu tun."
  exit 0
fi

_BASE_REAL="$(readlink -f "$BASE")"
validate_working_directory() {
  local unit="$1" wd
  wd="$(awk -F= '/^WorkingDirectory=/ {print $2; exit}' "$SRC/$unit")"
  [ -z "$wd" ] && return 0
  wd="${wd//%h/$HOME}"
  [ -d "$wd" ] || { echo "  ✗ $unit: WorkingDirectory fehlt: $wd" >&2; return 1; }
  [ "$(readlink -f "$wd")" = "$_BASE_REAL" ] || {
    echo "  ✗ $unit: WorkingDirectory != Workspace: $wd" >&2; return 1; }
}
install_unit() {
  local unit="$1"
  [ -f "$SRC/$unit" ] || { echo "  ✗ $unit fehlt in $SRC"; return 1; }
  validate_working_directory "$unit"
  sudo install -m 0644 "$SRC/$unit" "$DST/$unit"
  echo "  ✓ $unit installiert"
}

TIMERS=()
for u in \
  pv-auto-update.service        pv-auto-update.timer \
  pv-recovery-selfcheck.service pv-recovery-selfcheck.timer \
  pv-offsite-reminder.service   pv-offsite-reminder.timer; do
  install_unit "$u" || true
  [[ "$u" == *.timer ]] && TIMERS+=("$u")
done

sudo systemctl daemon-reload
for t in "${TIMERS[@]}"; do
  sudo systemctl enable --now "$t"
  echo "  ▶ $t enabled+started"
done

# Erst-Paket bauen, falls keins vorhanden (Aktualitaet herstellen).
if [ ! -f "$BASE/backup/recovery/LATEST_RECOVERY" ]; then
  echo "→ Kein Recovery-Paket vorhanden — baue Erst-Paket..."
  bash "$SELF_DIR/build_recovery_bundle.sh" || echo "  (Paketbau meldete Fehler — spaeter via Selfcheck)"
fi

echo ""
echo "=== Status ==="
systemctl list-timers 'pv-auto-update*' 'pv-recovery-selfcheck*' 'pv-offsite-reminder*' --no-pager || true
echo ""
"$BASE/.venv/bin/python" "$SELF_DIR/recovery_selfcheck.py" --status || true
echo "=== fertig ==="
