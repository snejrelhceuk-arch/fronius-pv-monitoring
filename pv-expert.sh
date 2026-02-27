#!/bin/bash
# pv-expert.sh — Schnellzugriff auf den PV-System-Experten (Ollama)
# Nutzung:
#   ./pv-expert.sh "Wie prüfe ich ob der Collector läuft?"
#   ./pv-expert.sh    (interaktiver Modus)

OLLAMA_HOST="ollama-server"  # SSH-Alias (192.168.2.116)
MODEL="pv-system-expert"

if [ -n "$1" ]; then
    # Einzelfrage-Modus
    PROMPT="$*"
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  PV-System-Experte (Qwen2.5-Coder 7B)                      ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Frage: $PROMPT"
    echo "────────────────────────────────────────────────────────"
    ssh -o ConnectTimeout=10 -o ServerAliveInterval=30 "$OLLAMA_HOST" \
        "curl -s --max-time 300 http://localhost:11434/api/generate \
         -d '{\"model\":\"$MODEL\",\"prompt\":\"$PROMPT\",\"stream\":false}'" \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','Keine Antwort'))" 2>/dev/null
else
    # Interaktiver Modus
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  PV-System-Experte — Interaktiver Modus                     ║"
    echo "║  Beenden: Ctrl+D oder 'exit'                                ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    while true; do
        read -p "🔧 Frage: " -r PROMPT
        [ -z "$PROMPT" ] && continue
        [ "$PROMPT" = "exit" ] && break
        echo "────────────────────────────────────────────────────────"
        ssh -o ConnectTimeout=10 -o ServerAliveInterval=30 "$OLLAMA_HOST" \
            "curl -s --max-time 300 http://localhost:11434/api/generate \
             -d '{\"model\":\"$MODEL\",\"prompt\":\"$PROMPT\",\"stream\":false}'" \
            | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','Keine Antwort'))" 2>/dev/null
        echo ""
    done
fi
