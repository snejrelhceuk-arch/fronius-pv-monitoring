#!/bin/bash
# Prüft ob nur eine collector.py Instanz läuft
# Für systemd ExecStartPre und Monitoring

# Nur collector.py zählen, NICHT wattpilot_collector.py
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COLLECTOR_PATTERN="${BASE_DIR}/collector\.py"
PROCESS_COUNT=$(pgrep -fc "$COLLECTOR_PATTERN" || true)

if [ "$PROCESS_COUNT" -gt 1 ]; then
    echo "⚠️  WARNUNG: $PROCESS_COUNT collector.py Prozesse gefunden!"
    echo "Prozesse:"
    pgrep -af "$COLLECTOR_PATTERN"
    
    if [ "$1" == "--kill-duplicates" ]; then
        echo ""
        echo "Stoppe alle und lasse systemd neu starten..."
        pkill -9 -f "$COLLECTOR_PATTERN" || true
        sleep 1
        exit 0
    fi
    
    exit 1
elif [ "$PROCESS_COUNT" -eq 0 ]; then
    echo "ℹ️  Kein collector.py Prozess läuft"
    exit 0
else
    echo "✓ Einzelner collector.py Prozess läuft"
    pgrep -af "$COLLECTOR_PATTERN" | head -1
    exit 0
fi
