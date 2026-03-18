#!/bin/bash
# =============================================================
# publish_audit.sh — Vollständiger Sanitize-Check vor Push
# =============================================================
# Durchsucht ALLE getrackten Dateien (nicht nur staged) nach
# den Mustern aus .publish-guard.
#
# Aufruf:
#   ./scripts/publish_audit.sh          # Prüft Working-Tree
#   ./scripts/publish_audit.sh --history # Prüft gesamte Git-History
#
# Exit-Code:
#   0 = sauber
#   1 = Treffer gefunden
# =============================================================

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GUARD_FILE="${REPO_ROOT}/.publish-guard"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ ! -f "$GUARD_FILE" ]; then
    echo -e "${RED}✗ .publish-guard nicht gefunden${NC}"
    exit 1
fi

PATTERNS=$(grep -vE '^\s*(#|$)' "$GUARD_FILE" | paste -sd'|' -)
if [ -z "$PATTERNS" ]; then
    echo -e "${GREEN}✓ Keine Sperrmuster definiert${NC}"
    exit 0
fi

MODE="${1:-}"
FOUND=0

echo "══════════════════════════════════════════════════"
echo "  PV-System Publish-Audit"
echo "══════════════════════════════════════════════════"
echo ""

# --- Phase 1: Getrackte Dateien im Working-Tree ---
echo "▶ Phase 1: Getrackte Dateien prüfen..."
TRACKED=$(cd "$REPO_ROOT" && git ls-files -- \
    ':!*.pdf' ':!*.db' ':!*.gz' ':!*.png' ':!*.jpg' ':!*.ico' \
    ':!*.woff*' ':!*.ttf' ':!.infra.local*' ':!.publish-guard')

PHASE1_HITS=0
while IFS= read -r f; do
    [ -z "$f" ] && continue
    MATCHES=$(grep -nE "$PATTERNS" "$REPO_ROOT/$f" 2>/dev/null | head -5)
    if [ -n "$MATCHES" ]; then
        echo -e "  ${RED}✗${NC} $f:"
        echo "$MATCHES" | sed 's/^/      /'
        PHASE1_HITS=$((PHASE1_HITS + 1))
        FOUND=1
    fi
done <<< "$TRACKED"

if [ "$PHASE1_HITS" -eq 0 ]; then
    echo -e "  ${GREEN}✓ Keine Treffer in getrackten Dateien${NC}"
fi
echo ""

# --- Phase 2: .gitignore Plausibilität ---
echo "▶ Phase 2: Gitignore-Abdeckung prüfen..."
CRITICAL_IGNORED=(
    ".infra.local"
    "pv-automation.service"
    "pv-observer.service"
    "pv-wattpilot.service"
    "config/fritz_config.json"
)
PHASE2_OK=1
for f in "${CRITICAL_IGNORED[@]}"; do
    if cd "$REPO_ROOT" && git ls-files --error-unmatch "$f" &>/dev/null; then
        echo -e "  ${RED}✗${NC} $f wird noch getrackt (sollte in .gitignore sein)"
        PHASE2_OK=0
        FOUND=1
    fi
done
if [ "$PHASE2_OK" -eq 1 ]; then
    echo -e "  ${GREEN}✓ Kritische Dateien korrekt ignoriert${NC}"
fi
echo ""

# --- Phase 3 (optional): History-Scan ---
if [ "$MODE" = "--history" ]; then
    echo "▶ Phase 3: Git-History scannen (kann dauern)..."
    HIST_HITS=$(cd "$REPO_ROOT" && git log --all -p --format='%B' 2>/dev/null \
        | grep -ciE "$PATTERNS" || true)
    if [ "$HIST_HITS" -gt 0 ]; then
        echo -e "  ${RED}✗ $HIST_HITS Treffer in der Git-History!${NC}"
        echo "    → git filter-repo mit scripts/filter-expressions.txt ausführen"
        FOUND=1
    else
        echo -e "  ${GREEN}✓ Git-History sauber${NC}"
    fi
    echo ""
fi

# --- Ergebnis ---
echo "══════════════════════════════════════════════════"
if [ "$FOUND" -eq 1 ]; then
    echo -e "  ${RED}🚫 AUDIT FEHLGESCHLAGEN — Sensible Daten gefunden${NC}"
    echo "══════════════════════════════════════════════════"
    exit 1
else
    echo -e "  ${GREEN}✅ AUDIT BESTANDEN — Repo ist publish-ready${NC}"
    echo "══════════════════════════════════════════════════"
    exit 0
fi
