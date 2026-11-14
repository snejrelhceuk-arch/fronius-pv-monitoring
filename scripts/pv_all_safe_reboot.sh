#!/bin/bash
# ============================================================
# scripts/pv_all_safe_reboot.sh — Koordinierter sicherer Reboot aller PV-Pis
#
# Reihenfolge: Tech → Küche → FB → Primary (immer zuletzt).
# Pro Host: maximale Datensicherung VOR dem Reboot, Verifikation nach dem Boot.
#
# Datenerhaltungs-Massnahmen:
#   Tech   : NQ-Flush (tmpfs-Aggregate → Primary-SD) vor dem Reboot.
#            Rohdaten 200ms/1s sind bewusst flüchtig (bauartbedingt).
#   Küche  : Nur Kiosk + Langzeit-Archiv-Empfaenger; kein laufender Datenschreiber.
#   FB     : Frischer Mirror-Sync (FB zieht Primary-data.db) VOR dem Reboot,
#            damit data.db auf FB-NVMe auf aktuellem Stand ist. Danach: auf
#            Mirror-Wiederherstellung warten (Failover-Bereitschaft).
#   Primary: 1) tmpfs-DB → SD (db_init._persist_tmpfs_to_sd + sqlite3-Fallback).
#            2) Dienste sauber stoppen (Schreib-Rollen zuerst: Automation, Wattpilot,
#               Collector, Web, Steuerbox). 3) PID-Files aufräumen. 4) Reboot.
#
# Post-Reboot-Pruefung (nach Wiederverbindung):
#   .venv/bin/python scripts/pv_post_reboot_check.py
#
# Nutzung:
#   bash scripts/pv_all_safe_reboot.sh [--dry-run] [--skip <host>] [--force]
#   --dry-run   Plan anzeigen, nichts tun (kein Reboot, kein Flush).
#   --skip <id> Host(s) ueberspringen: tech|kueche|fb|primary (Mehrfach erlaubt).
#   --force     Kein 15s-Abbruchfenster vor Primary-Reboot.
#
# Nur von Primary ausfuehren (role-guarded).
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/role_guard.sh" 2>/dev/null || { echo "Nur auf role=primary erlaubt" >&2; exit 1; }
source "$SCRIPT_DIR/load_infra_env.sh"
source "$SCRIPT_DIR/_reboot_remote_host.sh"

DRY=""; FORCE=""; SKIP=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY=1 ;;
    --force|-f)   FORCE=1 ;;
    --skip)       shift; SKIP+=("${1:-}") ;;
    *) echo "Unbekannter Parameter: $1" >&2; exit 2 ;;
  esac; shift
done

TMPFS_DB="/dev/shm/fronius_data.db"
PERSIST_DB="${REPO_ROOT}/data.db"
SSH_OPT="-o BatchMode=yes -o ConnectTimeout=10"
SSH="ssh $SSH_OPT"
PY="${REPO_ROOT}/.venv/bin/python"

skip() { local h="$1"; local s; for s in "${SKIP[@]:-}"; do [ "$s" = "$h" ] && return 0; done; return 1; }

log() { echo "$(date '+%F %T') | $*"; }
header() { echo ""; echo "══════════════════════════════════════════════════════"; echo "  $*"; echo "══════════════════════════════════════════════════════"; }

header "PV All-Safe-Reboot — $(date '+%F %T')"
[ -n "$DRY" ] && echo "MODUS: DRY-RUN (kein Reboot, kein Flush)"
echo "Reihenfolge: Tech → Küche → FB → Primary (zuletzt)"
echo "Überspringen: ${SKIP[*]:-keine}"

# ════════════════════════════════════════════════════════════
# 1. TECH (Pi4-Tech: WP-Bridge + NQ-Collector)
# ════════════════════════════════════════════════════════════
header "1/4 — Tech (${PV_TECH_USER:-admin}@${PV_TECH_IP})"
if skip tech; then
  log "→ Tech: übersprungen (--skip)."
else
  if [ -n "$DRY" ]; then
    log "[dry-run] NQ-Flush, dann sudo systemctl reboot auf Tech."
  else
    log "1a) NQ-Flush (Tech→Primary): 5min-Aggregate + Events + Kaskade…"
    bash "$SCRIPT_DIR/pv_nq_flush.sh" 12 || log "⚠ NQ-Flush meldete Fehler — Reboot trotzdem fortsetzen."

    log "1b) Reboot Tech…"
    TECH="${PV_TECH_USER:-admin}@${PV_TECH_IP}"
    reboot_remote_host "Tech" "$TECH" \
      pv-nq-poller.service pv-nq-energy.service pv-wp-bridge.service
    log "Tech-Reboot abgeschlossen."
  fi
fi

# ════════════════════════════════════════════════════════════
# 2. KÜCHE (Kiosk + Longterm-Backup-Empfaenger)
# ════════════════════════════════════════════════════════════
header "2/4 — Küche (${PV_KUECHE_HOST:-?})"
if skip kueche; then
  log "→ Küche: übersprungen (--skip)."
else
  if [ -n "$DRY" ]; then
    log "[dry-run] sudo systemctl reboot auf Küche."
  else
    KUECHE="${PV_KUECHE_HOST:?PV_KUECHE_HOST nicht gesetzt (.infra.local)}"
    reboot_remote_host "Küche" "$KUECHE" \
      pv-failover-init.service
    log "Küche: Kiosk-Anzeige nach Reboot bitte visuell prüfen."
  fi
fi

# ════════════════════════════════════════════════════════════
# 3. FB (Pi5-FB: Mirror + Backup + Failover + Ticker)
# ════════════════════════════════════════════════════════════
header "3/4 — FB (${PV_FAILOVER_HOST:-?})"
if skip fb; then
  log "→ FB: übersprungen (--skip)."
else
  FB="${PV_FAILOVER_HOST:?PV_FAILOVER_HOST nicht gesetzt (.infra.local)}"
  if [ -n "$DRY" ]; then
    log "[dry-run] Mirror-Sync erzwingen, dann sudo systemctl reboot auf FB."
  else
    # 3a. Frischen Mirror-Sync VOR dem FB-Reboot erzwingen:
    # Primary persisitiert zuerst, dann zieht FB.
    log "3a) Primary RAM-DB → SD persistieren (damit FB aktuellen Stand spiegelt)…"
    if [ -f "$TMPFS_DB" ]; then
      SIZE=$(stat -c%s "$TMPFS_DB" 2>/dev/null || echo 0)
      if [ "$SIZE" -gt 100000 ]; then
        "$PY" -c "
import sys; sys.path.insert(0,'${REPO_ROOT}')
import config, db_init
sys.exit(0 if db_init._persist_tmpfs_to_sd(config.DB_PATH, config.DB_PERSIST_PATH) else 1)
" && log "  ✓ RAM-DB persistiert ($(($(stat -c%s "$PERSIST_DB" 2>/dev/null||echo 0)/1048576)) MB)" \
      || { log "  ⚠ Persist-Helfer: Fallback sqlite3 .backup"; sqlite3 "$TMPFS_DB" ".backup '${PERSIST_DB}'"; log "  ✓ Fallback-Backup ok"; }
      else
        log "  ⚠ tmpfs-DB zu klein ($SIZE B) — übersprungen"
      fi
    else
      log "  ⚠ keine tmpfs-DB vorhanden"
    fi

    log "3b) FB: frischen Mirror-Sync auslösen (FB zieht aktuellen Stand von Primary)…"
    if $SSH "$FB" "sudo -n systemctl start pv-mirror-sync.service" 2>/dev/null; then
      # Kurz warten bis Mirror-Sync durch ist
      sleep 15
      MIRROR_AGE=$($SSH "$FB" "echo \$(( (\$(date +%s) - \$(stat -c %Y /dev/shm/fronius_data.db 2>/dev/null || date +%s)) / 60 ))" 2>/dev/null || echo "?")
      log "  ✓ Mirror-Sync ausgelöst (Alter jetzt: ${MIRROR_AGE} min)"
    else
      log "  ⚠ Mirror-Sync-Trigger fehlgeschlagen — mit vorhandenem Stand fortfahren"
    fi

    log "3c) Reboot FB…"
    reboot_remote_host "FB" "$FB" \
      pv-web.service pv-ticker.service pv-failover-init.service pv-mirror-sync.timer

    # 3d. Failover-Bereitschaft: tmpfs-Mirror muss nach Boot wiedererscheinen
    log "3d) Prüfe tmpfs-Mirror-Wiederherstellung (bis 120s)…"
    mirror_ok=0
    for _ in $(seq 1 12); do
      if $SSH "$FB" "test -f /dev/shm/fronius_data.db" 2>/dev/null; then
        AGE=$($SSH "$FB" "echo \$(( (\$(date +%s) - \$(stat -c %Y /dev/shm/fronius_data.db)) / 60 ))" 2>/dev/null || echo "?")
        log "  ✓ tmpfs-Mirror vorhanden (Alter ${AGE} min) — Failover übernahmebereit"
        mirror_ok=1; break
      fi
      sleep 10
    done
    [ "$mirror_ok" -ne 1 ] && log "  ✗ tmpfs-Mirror kam nicht zurück — nach Primary-Reboot prüfen!"
    log "FB-Reboot abgeschlossen."
  fi
fi

# ════════════════════════════════════════════════════════════
# 4. PRIMARY (zuletzt — Verbindung bricht beim Reboot)
# ════════════════════════════════════════════════════════════
header "4/4 — Primary (lokal — LETZTE AKTION, Verbindung bricht)"
if skip primary; then
  log "→ Primary: übersprungen (--skip). Manuell: bash scripts/4_reboot_Prim.sh"
else
  if [ -n "$DRY" ]; then
    log "[dry-run] Persist RAM-DB, Dienste stoppen, dann sudo systemctl reboot."
    log "Alles OK — DRY-RUN abgeschlossen."
    exit 0
  fi

  # Abbruchfenster (ausser --force)
  if [ -z "$FORCE" ]; then
    echo ""
    echo "⚠  Primary-Reboot in 15 Sekunden — Strg-C zum Abbruch."
    for i in $(seq 15 -1 1); do echo -n "$i "; sleep 1; done; echo ""
  fi

  log "4a) Finale RAM-DB-Persistierung (tmpfs → SD)…"
  if [ -f "$TMPFS_DB" ]; then
    SIZE=$(stat -c%s "$TMPFS_DB" 2>/dev/null || echo 0)
    if [ "$SIZE" -gt 100000 ]; then
      "$PY" -c "
import sys; sys.path.insert(0,'${REPO_ROOT}')
import config, db_init
sys.exit(0 if db_init._persist_tmpfs_to_sd(config.DB_PATH, config.DB_PERSIST_PATH) else 1)
" && log "  ✓ DB persistiert ($(($(stat -c%s "$PERSIST_DB" 2>/dev/null||echo 0)/1048576)) MB)" \
      || { log "  ⚠ Fallback: sqlite3 .backup"; sqlite3 "$TMPFS_DB" ".backup '${PERSIST_DB}'"; log "  ✓ Fallback ok"; }
    else
      log "  ⚠ tmpfs-DB zu klein ($SIZE B) — übersprungen"
    fi
  else
    log "  ⚠ keine tmpfs-DB vorhanden"
  fi

  log "4b) PV-Dienste sauber stoppen (Schreib-Rollen zuerst)…"
  for svc in pv-automation pv-observer pv-wattpilot pv-steuerbox pv-collector pv-web; do
    if systemctl is-active --quiet "${svc}.service" 2>/dev/null; then
      sudo -n systemctl stop "${svc}.service" && log "  ✓ $svc gestoppt" \
                                               || log "  ✗ $svc Stop fehlgeschlagen"
    fi
  done
  for pf in "$REPO_ROOT/collector.pid" "$REPO_ROOT/wattpilot_collector.pid" \
            "$REPO_ROOT/automation_daemon.pid"; do
    [ -f "$pf" ] && rm -f "$pf" && log "  ✓ $(basename "$pf") entfernt"
  done

  log "4c) Nach Wiederanlauf prüfen mit:"
  log "   .venv/bin/python scripts/pv_post_reboot_check.py"
  log ""
  log "→ Reboot jetzt. Verbindung bricht. Wiedersehen nach dem Boot."
  sync
  sudo -n systemctl reboot
fi
