#!/bin/bash
# =============================================================
# Hook-Installer — richtet Git-Hooks auf JEDEM Host ein
# =============================================================
#
# Nutzung (auf jedem Host, einmalig nach git clone/pull):
#   ./scripts/install_hooks.sh
#
# Was passiert:
#   - Kopiert scripts/pre-commit → .git/hooks/pre-commit
#   - Setzt Ausführungsrechte
#   - Zeigt aktuelle Host-Rolle an
#
# Auf Primary (181): Hook existiert, prüft Rolle → erlaubt Commit
# Auf Failover:      Hook existiert, prüft Rolle → blockt Commit
#
# Siehe doc/DUAL_HOST_ARCHITECTURE.md Abschnitt 9.
# =============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/.git/hooks"

# --- Pre-Commit Hook installieren ---
SOURCE="$SCRIPT_DIR/pre-commit"
TARGET="$HOOKS_DIR/pre-commit"

if [ ! -f "$SOURCE" ]; then
    echo "FEHLER: $SOURCE nicht gefunden."
    exit 1
fi

cp "$SOURCE" "$TARGET"
chmod +x "$TARGET"
echo "✅  pre-commit Hook installiert: $TARGET"

# --- Rolle anzeigen ---
ROLE="primary"
ROLE_FILE="$REPO_ROOT/.role"
if [ -f "$ROLE_FILE" ]; then
    ROLE="$(head -1 "$ROLE_FILE" | tr -d '[:space:]')"
fi

echo ""
echo "Aktuelle Rolle: $ROLE"
if [ "$ROLE" = "primary" ]; then
    echo "→ Commits sind ERLAUBT auf diesem Host."
else
    echo "→ Commits sind BLOCKIERT auf diesem Host."
    echo "  (Override: GIT_ALLOW_COMMIT=1 git commit ...)"
fi
