#!/bin/bash
# =================================================================
# terminal_safe_run.sh — robuster Wrapper fuer VS Code / LLM Terminal
#
# Ziel:
#   - Prompt-Paste-Fehler frueh erkennen
#   - interaktive Kommandos standardmaessig blocken
#   - optionale Timeouts erzwingen
#   - parallele Ausfuehrungen verhindern (flock)
#
# Nutzung:
#   ./scripts/terminal_safe_run.sh -- git status
#   ./scripts/terminal_safe_run.sh --timeout 180 -- ./scripts/publish_audit.sh
#   ./scripts/terminal_safe_run.sh --interactive -- ./pv-config.py
# =================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TIMEOUT_SEC="${TERMINAL_SAFE_TIMEOUT_SEC:-120}"
WORKDIR="$REPO_ROOT"
ALLOW_INTERACTIVE=0
NO_TIMEOUT=0
DRY_RUN=0
LOCK_FILE="/tmp/pv_terminal_safe_run.lock"

usage() {
    cat <<'EOF'
Nutzung:
  ./scripts/terminal_safe_run.sh [optionen] -- <kommando>

Optionen:
  --cwd <pfad>        Arbeitsverzeichnis (Default: Repo-Root)
  --timeout <sek>     Timeout in Sekunden (Default: 120)
  --no-timeout        Kein Timeout verwenden
  --interactive       Interaktive Kommandos erlauben
  --dry-run, -n       Kommando nur anzeigen
  --help, -h          Hilfe anzeigen

Beispiele:
  ./scripts/terminal_safe_run.sh -- git status
  ./scripts/terminal_safe_run.sh --timeout 300 -- ./scripts/sync_code_to_peer.sh --dry-run
  ./scripts/terminal_safe_run.sh --interactive -- ./pv-config.py
EOF
}

die() {
    echo "FEHLER: $*" >&2
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cwd)
            shift
            [[ $# -gt 0 ]] || die "--cwd erwartet einen Pfad"
            WORKDIR="$1"
            ;;
        --timeout)
            shift
            [[ $# -gt 0 ]] || die "--timeout erwartet eine Zahl"
            TIMEOUT_SEC="$1"
            ;;
        --no-timeout)
            NO_TIMEOUT=1
            ;;
        --interactive)
            ALLOW_INTERACTIVE=1
            ;;
        --dry-run|-n)
            DRY_RUN=1
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
    shift
done

[[ $# -gt 0 ]] || die "Kein Kommando uebergeben. Siehe --help."
[[ -d "$WORKDIR" ]] || die "Arbeitsverzeichnis nicht gefunden: $WORKDIR"

CMD="$*"

# Guard 1: Prompt-Fragmente aus Copy/Paste erkennen.
# Beispiel: '(.venv) user@host:~/pfad' oder ') user@host:~/pfad $ ^C'
if printf '%s\n' "$CMD" | grep -Eq '^[[:space:]]*\)?[[:space:]]*(\([^)]+\)[[:space:]]*)?[[:alnum:]_.-]+@[[:alnum:]_.-]+:~?/'; then
    die "Kommando enthaelt Prompt-Fragmente. Bitte nur den reinen Befehl ohne Prompt einfuellen."
fi

# Guard 2: Steuerzeichen-Fragmente erkennen.
if printf '%s' "$CMD" | grep -Eq '\^C|\^D'; then
    die "Kommando enthaelt Steuerzeichen-Fragmente (^C/^D). Bitte Bereinigung vor Ausfuehrung."
fi

# Guard 3: Interaktive Kommandos standardmaessig blocken.
if [[ "$ALLOW_INTERACTIVE" -eq 0 ]] && printf '%s' "$CMD" | grep -Eiq '(^|[;&|[:space:]])(read|select|whiptail|dialog|fzf|top|htop|less|more|vim|nano)([;&|[:space:]]|$)'; then
    die "Interaktives Kommando erkannt. Mit --interactive explizit freigeben."
fi

if [[ "$NO_TIMEOUT" -eq 0 ]] && [[ ! "$TIMEOUT_SEC" =~ ^[0-9]+$ ]]; then
    die "--timeout muss eine ganze Zahl sein"
fi

# Guard 4: Keine parallelen Ausfuehrungen.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    die "Ein anderer terminal_safe_run-Prozess laeuft bereits (Lock: $LOCK_FILE)."
fi

RUN_TS="$(date '+%Y-%m-%d %H:%M:%S')"
echo "[$RUN_TS] terminal_safe_run: cwd=$WORKDIR timeout=${TIMEOUT_SEC}s interactive=$ALLOW_INTERACTIVE"
echo "[$RUN_TS] command: $CMD"

if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "Dry-run: nichts ausgefuehrt."
    exit 0
fi

set +e
if [[ "$NO_TIMEOUT" -eq 1 || "$TIMEOUT_SEC" -eq 0 ]]; then
    bash -lc "cd \"$WORKDIR\" && export DEBIAN_FRONTEND=noninteractive CI=1 && set -euo pipefail; $CMD"
    RC=$?
else
    if command -v timeout >/dev/null 2>&1; then
        timeout --foreground "${TIMEOUT_SEC}s" bash -lc "cd \"$WORKDIR\" && export DEBIAN_FRONTEND=noninteractive CI=1 && set -euo pipefail; $CMD"
        RC=$?
        if [[ "$RC" -eq 124 ]]; then
            echo "FEHLER: Timeout nach ${TIMEOUT_SEC}s" >&2
        fi
    else
        bash -lc "cd \"$WORKDIR\" && export DEBIAN_FRONTEND=noninteractive CI=1 && set -euo pipefail; $CMD"
        RC=$?
    fi
fi
set -e

exit "$RC"
