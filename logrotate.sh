#!/bin/bash
# Log-Rotation für Fronius PV-System
# Löscht alte Logs (>7 Tage) und komprimiert aktuelle

LOG_DIR="/tmp"
MAX_AGE_DAYS=7
MAX_SIZE_MB=50

echo "=== Log-Rotation Start: $(date) ==="

# 1. Alte Logs löschen
echo "Lösche Logs älter als $MAX_AGE_DAYS Tage..."
find $LOG_DIR -name "*.log" -type f -mtime +$MAX_AGE_DAYS -delete
DELETED=$?
if [ $DELETED -eq 0 ]; then
    echo "  ✓ Alte Logs gelöscht"
fi

# 2. Große Logs rotieren
for LOGFILE in modbus_v3.log aggregate.log; do
    FULL_PATH="$LOG_DIR/$LOGFILE"
    
    if [ -f "$FULL_PATH" ]; then
        SIZE_KB=$(du -k "$FULL_PATH" | cut -f1)
        SIZE_MB=$((SIZE_KB / 1024))
        
        if [ $SIZE_MB -gt $MAX_SIZE_MB ]; then
            echo "$LOGFILE ist ${SIZE_MB}MB groß - rotiere..."
            
            # Backup mit Timestamp
            BACKUP="$FULL_PATH.$(date +%Y%m%d_%H%M%S)"
            mv "$FULL_PATH" "$BACKUP"
            
            # Komprimiere altes Log
            gzip "$BACKUP"
            
            echo "  ✓ $LOGFILE rotiert nach $(basename $BACKUP).gz"
        fi
    fi
done

# 3. Aufräumen: Komprimierte Logs >30 Tage
echo "Lösche komprimierte Logs älter als 30 Tage..."
find $LOG_DIR -name "*.log.*.gz" -type f -mtime +30 -delete

echo "=== Log-Rotation abgeschlossen ===" 
echo ""
