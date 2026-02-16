#!/bin/bash
# Prüft ob nur eine collector.py Instanz läuft
# Für systemd ExecStartPre und Monitoring

# Nur collector.py zählen, NICHT wattpilot_collector.py
PROCESS_COUNT=$(pgrep -fc "python3 collector.py|python3 .*/collector.py")

if [ "$PROCESS_COUNT" -gt 1 ]; then
    echo "⚠️  WARNUNG: $PROCESS_COUNT collector.py Prozesse gefunden!"
    echo "Prozesse:"
    ps aux | grep "[p]ython3.*collector.py"
    
    if [ "$1" == "--kill-duplicates" ]; then
        echo ""
        echo "Stoppe alle und lasse systemd neu starten..."
        pkill -9 -f "python3 collector.py|python3 .*/collector.py"
        sleep 1
        exit 0
    fi
    
    exit 1
elif [ "$PROCESS_COUNT" -eq 0 ]; then
    echo "ℹ️  Kein collector.py Prozess läuft"
    exit 0
else
    echo "✓ Einzelner collector.py Prozess läuft"
    ps aux | grep "[p]ython3.*collector.py" | head -1
    exit 0
fi
