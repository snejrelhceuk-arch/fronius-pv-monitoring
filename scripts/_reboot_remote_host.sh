#!/bin/bash
# ============================================================
# _reboot_remote_host.sh — Gemeinsame Logik: entfernten Host
# kontrolliert neu starten + selbstprüfend verifizieren.
#
# NICHT direkt aufrufen — wird von 1_reboot_Tech.sh / 2_reboot_K.sh /
# 3_reboot_FB.sh gesourct und über reboot_remote_host() genutzt.
#
# Ablauf pro Host:
#   1. Role-Guard: nur von Primary aus
#   2. Pre-Check: SSH erreichbar, boot_id/uptime/kernel/reboot-required
#   3. Reboot auslösen (sudo -n systemctl reboot)
#   4. Warten bis Host weg und mit NEUER boot_id zurück (bounded)
#   5. Post-Check: reboot-required gelöscht + alle Pflicht-Units aktiv
# ============================================================

reboot_remote_host() {
    local LABEL="$1"; shift
    local HOST="$1"; shift
    local UNITS=("$@")   # zu prüfende systemd-Units nach dem Boot

    local WAIT_MAX=240   # s — Obergrenze fürs Wiederkommen
    local SSH="ssh -o BatchMode=yes -o ConnectTimeout=8"

    echo "================================================================"
    echo "Reboot $LABEL  ($HOST)"
    echo "================================================================"

    # --- Role-Guard: nur Primary ---
    local ROLE="primary"
    [ -f "$REPO_ROOT/.role" ] && ROLE="$(head -n1 "$REPO_ROOT/.role" | tr -d '[:space:]')"
    if [ "$ROLE" != "primary" ]; then
        echo "❌  Nur vom PRIMARY-Host ausführen (Rolle hier: $ROLE)."; return 1
    fi

    # --- Pre-Check ---
    if ! $SSH "$HOST" "echo ok" >/dev/null 2>&1; then
        echo "❌  SSH nicht erreichbar: $HOST — abgebrochen."; return 1
    fi
    local OLD_BOOT KERN REBOOT_REQ UP
    OLD_BOOT="$($SSH "$HOST" "cat /proc/sys/kernel/random/boot_id" 2>/dev/null)"
    KERN="$($SSH "$HOST" "uname -r" 2>/dev/null)"
    REBOOT_REQ="$($SSH "$HOST" "[ -f /var/run/reboot-required ] && echo JA || echo nein" 2>/dev/null)"
    UP="$($SSH "$HOST" "uptime -p" 2>/dev/null)"
    echo "  vorher:  kernel=$KERN  reboot-required=$REBOOT_REQ  ($UP)"
    echo "  boot_id: ${OLD_BOOT:0:12}…"

    # --- Reboot auslösen (Verbindungsabbruch ist erwartet) ---
    echo "  → sende Reboot-Befehl …"
    $SSH "$HOST" "sudo -n systemctl reboot" >/dev/null 2>&1 || true

    # --- Warten aufs Wiederkommen mit NEUER boot_id ---
    echo -n "  warte auf Wiederanlauf "
    local waited=0 NEW_BOOT="" back=0
    sleep 10; waited=10   # kurze Grace bis der Host wirklich runterfährt
    while [ "$waited" -lt "$WAIT_MAX" ]; do
        NEW_BOOT="$($SSH "$HOST" "cat /proc/sys/kernel/random/boot_id" 2>/dev/null || true)"
        if [ -n "$NEW_BOOT" ] && [ "$NEW_BOOT" != "$OLD_BOOT" ]; then back=1; break; fi
        echo -n "."; sleep 8; waited=$((waited + 8))
    done
    echo ""
    if [ "$back" -ne 1 ]; then
        echo "❌  $LABEL kam nicht innerhalb ${WAIT_MAX}s mit neuer boot_id zurück!"
        echo "    Manuell prüfen: $SSH $HOST 'uptime; systemctl --failed'"
        return 1
    fi
    echo "  ✓ zurück nach ~${waited}s (neue boot_id ${NEW_BOOT:0:12}…)"

    # --- Post-Check ---
    local rc=0
    local NEW_UP NEW_RR
    NEW_UP="$($SSH "$HOST" "uptime -p" 2>/dev/null)"
    NEW_RR="$($SSH "$HOST" "[ -f /var/run/reboot-required ] && echo JA || echo nein" 2>/dev/null)"
    echo "  nachher: reboot-required=$NEW_RR  ($NEW_UP)"
    [ "$NEW_RR" = "JA" ] && { echo "  ⚠  reboot-required weiterhin gesetzt (weitere Updates?)"; }

    # Dienste hochgekommen? (bis zu ~30s Nachlauf tolerieren)
    local u tries state
    for u in "${UNITS[@]}"; do
        state="inactive"; tries=0
        while [ "$tries" -lt 5 ]; do
            state="$($SSH "$HOST" "systemctl is-active $u" 2>/dev/null || echo inactive)"
            [ "$state" = "active" ] && break
            sleep 5; tries=$((tries + 1))
        done
        if [ "$state" = "active" ]; then
            echo "  ✓ $u aktiv"
        else
            echo "  ✗ $u NICHT aktiv (Status: $state)"; rc=1
        fi
    done

    # Failed-Units generell melden
    local failed
    failed="$($SSH "$HOST" "systemctl --failed --no-legend --plain 2>/dev/null | wc -l" 2>/dev/null || echo 0)"
    if [ "${failed:-0}" -gt 0 ]; then
        echo "  ⚠  $failed failed-Unit(s) auf $LABEL:"
        $SSH "$HOST" "systemctl --failed --no-legend --plain" | sed 's/^/       /'
        rc=1
    fi

    if [ "$rc" -eq 0 ]; then
        echo "✓✓  $LABEL sauber neu gestartet und verifiziert."
    else
        echo "⚠⚠  $LABEL neu gestartet, aber Prüfungen unvollständig — bitte ansehen."
    fi
    return $rc
}
