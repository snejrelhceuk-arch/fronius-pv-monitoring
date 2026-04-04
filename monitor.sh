#!/bin/bash
# ⚠️ VERALTET — Ersetzt durch scripts/monitor_health.sh + diagnos/health.py
# Dieses Script bleibt als Schnelltest erhalten, ist aber nicht mehr
# die primäre Monitoring-Lösung.
#
# Monitoring-Script für Fronius PV-System
# Prüft Prozess-Status, Logs und System-Health

echo "=== Fronius PV Monitoring - Health Check ==="
echo "Zeitpunkt: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 1. Prozess-Check
echo "📊 Prozess-Status:"
if ps aux | grep -v grep | grep "modbus_v3.py" > /dev/null; then
    PID=$(ps aux | grep -v grep | grep "modbus_v3.py" | awk '{print $2}')
    MEM=$(ps aux | grep -v grep | grep "modbus_v3.py" | awk '{print $6}')
    CPU=$(ps aux | grep -v grep | grep "modbus_v3.py" | awk '{print $3}')
    echo "  ✅ modbus_v3.py läuft (PID: $PID, MEM: ${MEM}KB, CPU: ${CPU}%)"
else
    echo "  ❌ modbus_v3.py läuft NICHT!"
fi
echo ""

# 2. Port-Check
echo "🌐 Port-Status:"
if lsof -i :8000 > /dev/null 2>&1; then
    echo "  ✅ Port 8000 offen (Flask UI erreichbar)"
else
    echo "  ❌ Port 8000 NICHT offen!"
fi
echo ""

# 3. Datenbank-Check
echo "💾 Datenbank-Status:"
if [ -f "data.db" ]; then
    DB_SIZE=$(ls -lh data.db | awk '{print $5}')
    RAW_COUNT=$(sqlite3 data.db "SELECT COUNT(*) FROM raw_data;" 2>/dev/null)
    AGG15_COUNT=$(sqlite3 data.db "SELECT COUNT(*) FROM data_15min;" 2>/dev/null)
    HOURLY_COUNT=$(sqlite3 data.db "SELECT COUNT(*) FROM hourly_data;" 2>/dev/null)
    
    echo "  📊 Größe: $DB_SIZE"
    echo "  📈 raw_data: $RAW_COUNT Zeilen"
    echo "  📈 data_15min: $AGG15_COUNT Zeilen"
    echo "  📈 hourly_data: $HOURLY_COUNT Zeilen"
    
    # Warne bei zu vielen raw_data (>60.000 = >4 Tage bei 5s-Polling)
    if [ "$RAW_COUNT" -gt 60000 ]; then
        echo "  ⚠️  WARNUNG: Sehr viele raw_data Zeilen (Cleanup prüfen!)"
    fi
else
    echo "  ❌ data.db nicht gefunden!"
fi
echo ""

# 4. Log-Check (letzte 5 Zeilen)
echo "📝 Logs (letzte 5 Zeilen):"
if [ -f "/tmp/modbus_v3.log" ]; then
    tail -5 /tmp/modbus_v3.log
else
    echo "  ℹ️  Keine Logs gefunden"
fi
echo ""

# 5. Cron-Check
echo "⏰ Cron-Jobs:"
if crontab -l 2>/dev/null | grep aggregate.py > /dev/null; then
    echo "  ✅ Aggregation-Cron aktiv"
else
    echo "  ❌ Aggregation-Cron NICHT gefunden!"
fi
echo ""

# 6. API-Check
echo "🔌 API-Verfügbarkeit:"
if curl -s --max-time 2 http://localhost:8000/api/dashboard > /dev/null 2>&1; then
    FREQ=$(curl -s http://localhost:8000/api/dashboard 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('grid_freq', 'N/A'))" 2>/dev/null)
    SOC=$(curl -s http://localhost:8000/api/dashboard 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('SOC_Batt', 'N/A'))" 2>/dev/null)
    
    echo "  ✅ API erreichbar"
    echo "  📊 Netz-Frequenz: ${FREQ} Hz"
    echo "  🔋 Batterie-SOC: ${SOC}%"
    
    # Frequenz-Warnung
    if command -v bc > /dev/null && [ "$FREQ" != "N/A" ]; then
        if (( $(echo "$FREQ < 49.8" | bc -l) )) || (( $(echo "$FREQ > 50.2" | bc -l) )); then
            echo "  ⚠️  WARNUNG: Netz-Frequenz außerhalb Toleranz (49.8-50.2 Hz)!"
        fi
    fi
else
    echo "  ❌ API NICHT erreichbar!"
fi
echo ""

echo "=== Health Check abgeschlossen ==="
