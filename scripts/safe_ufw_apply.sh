#!/bin/bash
# ──────────────────────────────────────────────────────────────────
# safe_ufw_apply.sh — UFW-Firewall idempotent einrichten
#
# Sicherheit:  Auto-Rollback-Timer (3 Min).  Wird UFW aktiviert,
#              läuft im Hintergrund ein Watchdog, der UFW nach
#              ROLLBACK_SEC wieder deaktiviert — es sei denn, der
#              Benutzer bestätigt vorher mit ENTER.
#
# Nutzung:     sudo bash scripts/safe_ufw_apply.sh
#              (danach SSH-Gegenprobe aus zweiter Shell!)
#
# Idempotent:  Mehrfachaufruf sicher — UFW wird zurückgesetzt und
#              Regeln werden frisch angelegt.
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Projekt-Konventionen ─────────────────────────────────────────
_SCRIPT_BASE="$(cd "$(dirname "$0")/.." && pwd)"
source "${_SCRIPT_BASE}/scripts/load_infra_env.sh"

# ── Konfigurierbare Parameter (aus .infra.local oder Defaults) ───
[[ -n "${PV_LAN_CIDR:-}" ]] || die "PV_LAN_CIDR nicht gesetzt (in .infra.local definieren)"
LAN_CIDR="${PV_LAN_CIDR}"
VPN_CIDR="${PV_VPN_CIDR:-}"            # leer = kein VPN-Regel
WEB_PORT="${PV_WEB_PORT:-8000}"
SSH_PORT="${PV_SSH_PORT:-22}"
ROLLBACK_SEC="${PV_UFW_ROLLBACK_SEC:-180}"

LOG_FILE="/tmp/pv_ufw_apply.log"

# ── Hilfs-Funktionen ─────────────────────────────────────────────
log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
  echo "$msg" | tee -a "$LOG_FILE"
}

die() { log "FEHLER: $1"; exit 1; }

# ── Voraussetzungen ──────────────────────────────────────────────
[[ $EUID -eq 0 ]] || die "Bitte mit sudo ausführen."

if ! command -v ufw &>/dev/null; then
  log "ufw nicht installiert — installiere …"
  apt-get update -qq && apt-get install -y -qq ufw
fi

log "═══ UFW-Setup Start ═══"
log "LAN_CIDR  = $LAN_CIDR"
log "VPN_CIDR  = ${VPN_CIDR:-<nicht gesetzt>}"
log "WEB_PORT  = $WEB_PORT"
log "SSH_PORT  = $SSH_PORT"
log "Rollback  = ${ROLLBACK_SEC}s"

# ── Schritt 1: Sauberer Zustand ─────────────────────────────────
log "→ Setze UFW zurück (reset) …"
ufw --force reset >> "$LOG_FILE" 2>&1

# ── Schritt 2: Defaults ─────────────────────────────────────────
ufw default deny incoming  >> "$LOG_FILE" 2>&1
ufw default allow outgoing >> "$LOG_FILE" 2>&1
log "→ Defaults: deny incoming, allow outgoing"

# ── Schritt 3: SSH zuerst (wichtigste Regel!) ───────────────────
ufw allow from "$LAN_CIDR" to any port "$SSH_PORT" proto tcp comment "SSH LAN" >> "$LOG_FILE" 2>&1
log "→ SSH erlaubt von $LAN_CIDR"

if [[ -n "$VPN_CIDR" ]]; then
  ufw allow from "$VPN_CIDR" to any port "$SSH_PORT" proto tcp comment "SSH VPN" >> "$LOG_FILE" 2>&1
  log "→ SSH erlaubt von $VPN_CIDR (VPN)"
fi

# ── Schritt 4: Web-API ──────────────────────────────────────────
ufw allow from "$LAN_CIDR" to any port "$WEB_PORT" proto tcp comment "Web-API LAN" >> "$LOG_FILE" 2>&1
log "→ Web-API ($WEB_PORT) erlaubt von $LAN_CIDR"

if [[ -n "$VPN_CIDR" ]]; then
  ufw allow from "$VPN_CIDR" to any port "$WEB_PORT" proto tcp comment "Web-API VPN" >> "$LOG_FILE" 2>&1
  log "→ Web-API ($WEB_PORT) erlaubt von $VPN_CIDR (VPN)"
fi

# ── Schritt 5: Rollback-Timer starten ───────────────────────────
ROLLBACK_PID_FILE="/tmp/pv_ufw_rollback.pid"

# Alten Rollback-Prozess beenden (falls vorhanden)
if [[ -f "$ROLLBACK_PID_FILE" ]]; then
  old_pid=$(cat "$ROLLBACK_PID_FILE" 2>/dev/null || true)
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" 2>/dev/null || true
    log "→ Alten Rollback-Timer (PID $old_pid) beendet"
  fi
  rm -f "$ROLLBACK_PID_FILE"
fi

# Neuen Rollback-Timer im Hintergrund starten
(
  sleep "$ROLLBACK_SEC"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠ ROLLBACK: ${ROLLBACK_SEC}s ohne Bestätigung — deaktiviere UFW" >> "$LOG_FILE"
  ufw --force disable >> "$LOG_FILE" 2>&1
  rm -f "$ROLLBACK_PID_FILE"
) &
ROLLBACK_PID=$!
echo "$ROLLBACK_PID" > "$ROLLBACK_PID_FILE"
log "→ Rollback-Timer gestartet (PID $ROLLBACK_PID, ${ROLLBACK_SEC}s)"

# ── Schritt 6: UFW aktivieren ───────────────────────────────────
log "→ Aktiviere UFW …"
ufw --force enable >> "$LOG_FILE" 2>&1
log "→ UFW AKTIV"

# ── Schritt 7: Status anzeigen ──────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
ufw status verbose
echo "════════════════════════════════════════════════════════════"
echo ""
log "→ Status angezeigt"

# ── Schritt 8: Benutzer-Bestätigung ─────────────────────────────
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║  JETZT: Aus einer ZWEITEN SSH-Shell testen, ob du       ║"
echo "║  dich noch verbinden kannst!                             ║"
echo "║                                                          ║"
echo "║  Danach ENTER drücken → Rollback-Timer wird gestoppt.   ║"
echo "║                                                          ║"
echo "║  Keine Eingabe in ${ROLLBACK_SEC}s → UFW wird automatisch     ║"
echo "║  deaktiviert (Rollback).                                 ║"
echo "╚═══════════════════════════════════════════════════════════╝"

if read -r -t "$ROLLBACK_SEC" _unused 2>/dev/null; then
  # Benutzer hat bestätigt → Timer stoppen
  if kill -0 "$ROLLBACK_PID" 2>/dev/null; then
    kill "$ROLLBACK_PID" 2>/dev/null || true
    wait "$ROLLBACK_PID" 2>/dev/null || true
  fi
  rm -f "$ROLLBACK_PID_FILE"
  log "✔ Benutzer hat bestätigt — UFW bleibt AKTIV"
  echo ""
  echo "✔ UFW bleibt aktiv. Rollback-Timer gestoppt."
  echo "  Log: $LOG_FILE"
else
  # Timeout — Rollback-Prozess hat UFW bereits deaktiviert
  log "⚠ Timeout — Rollback wurde ausgelöst"
  echo ""
  echo "⚠ Keine Bestätigung — UFW wurde automatisch deaktiviert."
  echo "  Log: $LOG_FILE"
  exit 1
fi

log "═══ UFW-Setup abgeschlossen ═══"
