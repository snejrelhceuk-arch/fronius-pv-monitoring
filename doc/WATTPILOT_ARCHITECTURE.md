# Wattpilot Integration Architektur

## Übersicht
Der Fronius Wattpilot (Wallbox) kommuniziert über **WebSocket API** (nicht Modbus/SmartMeter).

**WebSocket-Endpoint:** `ws://192.0.2.197/ws`

---

## ⚠️ KRITISCHE EINSCHRÄNKUNG: Single-Client-WebSocket

### Problem
Die Wattpilot WebSocket-API erlaubt nur **EINE** gleichzeitige Verbindung:
- Zweiter Client wird automatisch getrennt
- Keine parallelen Zugriffe möglich (anders als HTTP REST APIs)
- Wichtig für Monitoring, Debugging, Live-Daten

### Lösung: Database-Intermediary Pattern
```
┌─────────────────┐
│  Wattpilot WS   │  ws://192.0.2.197/ws
└────────┬────────┘
         │ EINZIGE Verbindung
         ↓
┌─────────────────────────┐
│ wattpilot_collector.py  │  Daemon mit PID-File-Schutz
│ (Single Instance)       │  Polling: 10s
└────────┬────────────────┘
         │
         ↓ INSERT
┌─────────────────────────┐
│    SQLite Database      │
│  wattpilot_readings     │
│  wattpilot_daily        │
└────────┬────────────────┘
         │
         ↓ SELECT (parallel möglich!)
┌─────────────────────────┐
│   Mehrere Leser:        │
│  • web_api.py           │
│  • Flow-Chart Frontend  │
│  • Statistik-Tools      │
└─────────────────────────┘
```

---

## Single-Instance-Protection

### PID-File Mechanismus
**Datei:** `wattpilot_collector.pid`

```python
def create_pid_file():
    if PID_FILE.exists():
        old_pid = int(open(PID_FILE).read())
        # Prüfe ob Prozess läuft
        try:
            os.kill(old_pid, 0)
            # Prozess existiert → FEHLER
            logger.error(f"Collector läuft bereits (PID {old_pid})")
            sys.exit(1)
        except OSError:
            # Prozess tot → entferne verwaistes PID-File
            PID_FILE.unlink()
    
    # Schreibe aktuellen PID
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))
```

### Manueller Start-Versuch bei laufendem Collector
```bash
$ python3 wattpilot_collector.py
2026-02-12 12:45:03,163 - ERROR - Wattpilot-Collector läuft bereits (PID 1061974)
2026-02-12 12:45:03,163 - ERROR -    Stoppen Sie den Prozess mit: kill 1061974
2026-02-12 12:45:03,163 - ERROR -    Oder erzwingen: rm wattpilot_collector.pid
```

---

## Datenfluss

### 1. Collector → Database
**Intervall:** 10 Sekunden (konfigurierbar via `config.WATTPILOT_POLL_INTERVAL`)

**Gespeicherte Daten:**
```sql
CREATE TABLE wattpilot_readings (
    ts INTEGER PRIMARY KEY,
    energy_total_wh REAL,
    power_w REAL,
    car_state INTEGER,
    session_wh REAL,
    temperature_c REAL,
    phase_mode INTEGER
);
```

### 2. Web-API → Database
**Endpoint:** `/api/flow_realtime`

```python
# Lese aktuellste Wattpilot-Daten (max 60s alt)
c.execute("""
    SELECT power_w FROM wattpilot_readings 
    WHERE ts > ?
    ORDER BY ts DESC LIMIT 1
""", (now - 60,))

wattpilot_power = max(0, c.fetchone()[0] or 0)
```

**⚠️ Wichtig:** Negative Werte werden verhindert (`max(0, ...)`)

### 3. Frontend → Web-API
**Polling:** 10 Sekunden (synchron mit Collector)

```javascript
// Flow-Chart ruft jede 10s ab
setInterval(async () => {
    const data = await fetch('/api/flow_realtime').then(r => r.json());
    updateFlows(data.consumption.wattpilot);
}, 10000);
```

---

## Konfiguration

### config.py
```python
WATTPILOT_IP = '192.0.2.197'
WATTPILOT_TIMEOUT = 10  # WebSocket-Verbindungstimeout
WATTPILOT_POLL_INTERVAL = 10  # Polling-Intervall in Sekunden
WATTPILOT_READINGS_RETENTION_DAYS = 90  # Datenaufbewahrung
```

### Empfohlene Intervalle
- **10s**: Standard - gute Balance (Flow-Chart Visualisierung)
- **5s**: High-frequency (mehr DB-Load)
- **15s+**: Low-frequency (weniger Daten, gröbere Auflösung)

**Wichtig:** Flow-Chart Frontend-Polling sollte mit `WATTPILOT_POLL_INTERVAL` synchronisiert sein.

---

## WP/Wattpilot Namenskonvention

### ⚠️ SYSTEMWEITE REGEL
```
WP, P_WP, W_Imp_WP      →  Wärmepumpe (Heat Pump)
                           SmartMeter Unit 4 (Modbus)

Wattpilot               →  Fronius Wallbox (EV Charger)
                           WebSocket API (192.0.2.197)
```

**Hintergrund:** Frühere Verwirrung führte zu falschen Daten im Flow-Chart.

### Code-Kommentare
Alle relevanten Stellen enthalten explizite Kommentare:
```python
# KRITISCH: P_WP = Wärmepumpe (SmartMeter Unit 4), NICHT Wattpilot!
waermepumpe = max(0, round(p_wp, 0))

# Wattpilot (aus DB gelesen)
wattpilot = max(0, wattpilot_power)
```

---

## Operational Best Practices

### Collector-Management
```bash
# Status prüfen
ps aux | grep wattpilot_collector
cat wattpilot_collector.pid

# Stoppen
kill $(cat wattpilot_collector.pid)
# oder
pkill -f wattpilot_collector

# Starten
cd /srv/pv-system
nohup python3 wattpilot_collector.py > /tmp/wattpilot_collector.log 2>&1 &

# Logs prüfen
tail -f /tmp/wattpilot_collector.log
```

### Troubleshooting

#### "Wattpilot-Collector läuft bereits"
**Ursache:** PID-File existiert, Prozess läuft

**Lösung:**
```bash
# Prozess tatsächlich beenden
kill $(cat wattpilot_collector.pid)

# Oder erzwingen (nur wenn Prozess tot ist!)
rm wattpilot_collector.pid
```

#### "Keine Wattpilot-Daten im Flow-Chart"
1. Prüfen ob Collector läuft: `ps aux | grep wattpilot`
2. Logs prüfen: `tail /tmp/wattpilot_collector.log`
3. DB-Daten prüfen:
   ```bash
   sqlite3 /dev/shm/fronius_data.db "SELECT * FROM wattpilot_readings ORDER BY ts DESC LIMIT 5;"
   ```
4. Flask-Server neu starten:
   ```bash
   pkill -f web_api
   cd /srv/pv-system
   nohup python3 web_api.py > /tmp/web_api.log 2>&1 &
   ```

#### WebSocket-Verbindungsfehler
**Typische Fehlermeldungen:**
- `asyncio.exceptions.TimeoutError`
- `websockets.exceptions.ConnectionClosed`

**Mögliche Ursachen:**
- Wattpilot offline/nicht erreichbar
- Netzwerkprobleme
- Anderer Client verbindet sich (z.B. manuelle cURL-Tests)

**Diagnose:**
```bash
# Ping-Test
ping -c 3 192.0.2.197

# Manuelle WebSocket-Verbindung (VORSICHT: unterbricht Collector!)
# NUR ZU TESTZWECKEN!
python3 -c "
import asyncio
import websockets

async def test():
    async with websockets.connect('ws://192.0.2.197/ws', open_timeout=5) as ws:
        print('✓ Verbunden')
        msg = await ws.recv()
        print(f'Empfangen: {msg[:100]}...')

asyncio.run(test())
"
```

---

## Monitoring

### Datenqualität prüfen
```bash
# Aktuelle Leistung
sqlite3 /dev/shm/fronius_data.db \
  "SELECT datetime(ts, 'unixepoch', 'localtime') AS zeit, 
          power_w, energy_total_wh 
   FROM wattpilot_readings 
   ORDER BY ts DESC LIMIT 10;"

# Tagesstatistik
sqlite3 /dev/shm/fronius_data.db \
  "SELECT * FROM wattpilot_daily ORDER BY date DESC LIMIT 5;"
```

### Polling-Intervall prüfen
```bash
# Zeitdifferenzen zwischen Readings
sqlite3 /dev/shm/fronius_data.db \
  "SELECT 
     datetime(ts, 'unixepoch', 'localtime') AS zeit,
     ts - LAG(ts) OVER (ORDER BY ts) AS delta_sekunden
   FROM wattpilot_readings 
   ORDER BY ts DESC LIMIT 20;"
```

**Erwartete Ausgabe:** ~10s Deltas (bei POLL_INTERVAL=10)

---

## Historische Daten

### Solarweb Referenz (2021-2025)
Alle Monate zeigen `wattpilot_kwh: 0.0` - **KORREKT**, da Wattpilot erst 2026 installiert wurde.

**Quelle:** `backup/solarweb_referenz.json`

### Erste Daten
**Start:** 2026-02-12 12:39:24
**Intervall:** 10-12 Sekunden
**Initiale Messung:** 11913.8 kWh Gesamtzähler, 10306W Ladepower

---

## Flow-Chart Integration

### Negative-Werte-Schutz
**Backend (web_api.py):**
```python
wattpilot = max(0, wattpilot_power)
waermepumpe = max(0, round(p_wp, 0))
haushalt = max(0, round(verbrauch_gesamt - wattpilot - waermepumpe, 0))
```

**Frontend (flow_view.html):**
```javascript
{ id:'c_wallbox', path:[N.consumption, N.wattpilot],  
  get: d => Math.max(0, d.consumption.wattpilot||0) },

{ id:'c_hp', path:[N.consumption, N.heatpump],   
  get: d => Math.max(0, d.consumption.heatpump||0) },
```

**Grund:** SmartMeter können bei Messfehlern/Rückspeisung negative Werte liefern. UI soll immer ≥ 0W anzeigen.

---

## Zusammenfassung

| Aspekt | Wert |
|--------|------|
| **API-Typ** | WebSocket (NICHT HTTP REST) |
| **Max. Clients** | **1** (Single Connection Only) |
| **Polling-Intervall** | 10s (konfigurierbar) |
| **Single-Instance** | PID-File-Protection |
| **DB-Tabellen** | wattpilot_readings, wattpilot_daily |
| **Datenaufbewahrung** | 90 Tage (tmpfs + NVMe Backup) |
| **Namenskonvention** | "Wattpilot" (Wallbox), "WP/Wärmepumpe" (Heat Pump) |

---

**Letzte Aktualisierung:** 2026-02-12  
**Version:** 1.0  
**Autor:** System Documentation
