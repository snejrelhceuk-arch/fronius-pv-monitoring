#!/bin/bash
# ============================================================
# PV-System: NQ-Modul (Rolle N) — Systemd-Units installieren
# ------------------------------------------------------------
# Rollen-bewusst (.role):
#   tech     -> pv-nq-poller.service, pv-nq-energy.service (Dauerläufer)
#   primary  -> pv-nq-agg-transfer / pv-nq-aggregate / pv-nq-energy-rollup /
#               pv-nq-energy-rollup-month / pv-nq-energy-rollup-year /
#               pv-nq-event-transfer / pv-nq-analysis / pv-nq-primary-cap  (Timer)
#
# Idempotent: install -m 0644 + daemon-reload + enable --now.
# Aufruf:  scripts/install_nq_services.sh
# Doku:    doc/netzqualitaet/NQ_MODUL.md, doc/netzqualitaet/NQ_TESTS_UND_DB.md
# ============================================================
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$BASE/config/systemd"
DST="/etc/systemd/system"

ROLE="$(cat "$BASE/.role" 2>/dev/null || echo primary)"
echo "=== NQ-Services installieren (Rolle: $ROLE) ==="

install_unit() {
    local unit="$1"
    if [ ! -f "$SRC/$unit" ]; then
        echo "  ✗ $unit fehlt in $SRC — übersprungen"
        return 1
    fi
    sudo install -m 0644 "$SRC/$unit" "$DST/$unit"
    echo "  ✓ $unit installiert"
}

TIMERS=()
SERVICES=()

case "$ROLE" in
  tech)
    for u in pv-nq-poller.service pv-nq-energy.service; do
        install_unit "$u" && SERVICES+=("$u")
    done
    ;;
  primary)
    for u in \
        pv-nq-agg-transfer.service pv-nq-agg-transfer.timer \
        pv-nq-aggregate.service    pv-nq-aggregate.timer \
        pv-nq-energy-rollup.service pv-nq-energy-rollup.timer \
        pv-nq-energy-rollup-month.service pv-nq-energy-rollup-month.timer \
        pv-nq-energy-rollup-year.service  pv-nq-energy-rollup-year.timer \
        pv-nq-event-transfer.service pv-nq-event-transfer.timer \
        pv-nq-analysis.service     pv-nq-analysis.timer \
        pv-nq-primary-cap.service  pv-nq-primary-cap.timer; do
        install_unit "$u" || true
        [[ "$u" == *.timer ]] && TIMERS+=("$u")
    done
    ;;
  *)
    echo "Rolle '$ROLE' hat keine NQ-Units (nur tech/primary). Nichts zu tun."
    exit 0
    ;;
esac

sudo systemctl daemon-reload

for s in "${SERVICES[@]:-}"; do
    [ -n "$s" ] || continue
    sudo systemctl enable --now "$s"
    echo "  ▶ $s enabled+started"
done

for t in "${TIMERS[@]:-}"; do
    [ -n "$t" ] || continue
    sudo systemctl enable --now "$t"
    echo "  ▶ $t enabled+started"
done

echo "=== fertig. Status prüfen mit: systemctl list-timers 'pv-nq-*' ==="
