#!/bin/bash
# ============================================================
# 4_reboot_Prim.sh — Pi5-Primary (Produktion A–E) sicher neu starten.
# Abgeleitet von secure_shutdown.sh: RAM-DB persistieren → Dienste sauber
# stoppen → REBOOT (statt Shutdown). ZULETZT ausführen (nach 1–3).
#
# Achtung: Der Reboot trennt die aktive Sitzung. Selbstprüfung des
# Wiederanlaufs ist danach lokal nicht möglich — Checkliste am Ende beachten.
#
#   ./scripts/4_reboot_Prim.sh            # Persist + Stop + Reboot (10s Abbruch-Fenster)
#   ./scripts/4_reboot_Prim.sh --no-reboot # nur Persist + Stop (Test, kein Reboot)
#   ./scripts/4_reboot_Prim.sh --force     # ohne Abbruch-Fenster
# ============================================================
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TMPFS_DB="/dev/shm/fronius_data.db"
PERSIST_DB="${REPO_ROOT}/data.db"

NO_REBOOT=0; FORCE=0
for a in "$@"; do
    case "$a" in
        --no-reboot) NO_REBOOT=1 ;;
        --force|-f)  FORCE=1 ;;
        --help|-h)   grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    esac
done

# --- Role-Guard: nur Primary ---
ROLE="primary"
[ -f "$REPO_ROOT/.role" ] && ROLE="$(head -n1 "$REPO_ROOT/.role" | tr -d '[:space:]')"
if [ "$ROLE" != "primary" ]; then
    echo "❌  Dieses Skript ist für den PRIMARY-Host (Rolle hier: $ROLE)."; exit 1
fi

echo "=== 4_reboot_Prim: Primary sicher neu starten ==="

# --- 1. RAM-DB → SD persistieren ---
echo "1. Persistiere RAM-DB (tmpfs → SD)…"
if [ -f "$TMPFS_DB" ]; then
    SIZE=$(stat -c%s "$TMPFS_DB" 2>/dev/null || echo 0)
    if [ "$SIZE" -gt 100000 ]; then
        if python3 -c "
import sys; sys.path.insert(0, '${REPO_ROOT}')
import config, db_init
sys.exit(0 if db_init._persist_tmpfs_to_sd(config.DB_PATH, config.DB_PERSIST_PATH) else 1)
"; then
            echo "  ✓ persistiert ($(( $(stat -c%s "$PERSIST_DB" 2>/dev/null||echo 0) / 1048576 )) MB)"
        else
            echo "  ⚠ Persist-Helfer fehlgeschlagen — Fallback sqlite3 .backup"
            sqlite3 "$TMPFS_DB" ".backup '${PERSIST_DB}'" && echo "  ✓ Fallback-Backup ok"
        fi
    else
        echo "  ⚠ tmpfs-DB zu klein ($SIZE B) — übersprungen"
    fi
else
    echo "  ⚠ keine tmpfs-DB vorhanden — übersprungen"
fi

# --- 2. Dienste sauber stoppen ---
echo "2. Stoppe PV-Dienste (Schreib-Rollen zuerst)…"
for svc in pv-automation pv-observer pv-wattpilot pv-steuerbox pv-collector pv-web; do
    if systemctl is-active --quiet "$svc.service" 2>/dev/null; then
        sudo -n systemctl stop "$svc.service" && echo "  ✓ $svc gestoppt" || echo "  ✗ $svc Stop fehlgeschlagen"
    fi
done
for pf in "$REPO_ROOT/collector.pid" "$REPO_ROOT/wattpilot_collector.pid" "$REPO_ROOT/automation_daemon.pid"; do
    [ -f "$pf" ] && rm -f "$pf" && echo "  ✓ $(basename "$pf") entfernt"
done

if [ "$NO_REBOOT" -eq 1 ]; then
    echo "3. --no-reboot gesetzt → KEIN Reboot. Persist+Stop abgeschlossen."
    exit 0
fi

# --- 3. Reboot (mit Abbruch-Fenster) ---
if [ "$FORCE" -ne 1 ]; then
    echo "3. Reboot in 10s — Abbruch mit Strg-C …"
    for i in $(seq 10 -1 1); do echo -n "$i "; sleep 1; done; echo ""
fi
echo "→ Reboot jetzt. Nach dem Wiederanlauf prüfen:"
echo "   systemctl is-active pv-web pv-automation pv-collector pv-steuerbox pv-wattpilot"
echo "   systemctl --failed ; [ -f /var/run/reboot-required ] && echo 'noch reboot-required' || echo 'Kernel aktiv'"
sudo -n systemctl reboot
