# Fritz!DECT API — Performance & Safety Analysis

**Stand:** 2026-03-18  
**Ziel:** Sichere Polling-Frequenz für HP + Klima-SD Echtzeiterfassung

---

## 1. Fritz!DECT Hardware-Limits

### Fritz!Box AHA-HTTP API Constraints

| Parameter | Wert | Quelle |
|-----------|------|--------|
| **Max Requests/sec** | 5–10 | Empirisch (stabilster Betrieb: 2-3 req/s) |
| **HTTP-Timeout** | 10s | Fronius Smart Meter: 10s timeout |
| **Session-ID TTL** | ~20 Min | Fritz!Box Standard, wir cachen 15 Min |
| **Empfohlenes Min-Interval** | ≥500ms | Zwischen zwei Requests auf SELBE AIN |
| **getdevicelistinfos()** | SINGLE QUERY | Holt **ALLE** Geräte auf einmal (optimal!) |

### Netzwerk-Performance System

- **Host:** Raspberry Pi 4 (Gigabit-LAN zu Fritz!Box)
- **Latenz:** ~1–3ms (LAN, local)
- **Bandbreite:** Nicht limitierend (AHA-Requests <1KB)

---

## 2. Aktueller Polling-Status im DataCollector

| Collector | Interval | Zugriff | Bottleneck |
|-----------|----------|---------|-----------|
| PV/Netz/Batt (Fronius) | **10s** (collector.py) | Modbus TCP/IP | stabil |
| Fronius HTTP-API (SOC-Config) | 30s | HTTP (cached SID) | minimal |
| Modbus Steuerregister | 30s | Direct M124 | minimal |
| Wattpilot | 30s (wattpilot_collector.py) | WebSocket | Single-Client-Limited |
| **Heizpatrone (HP)** | **60s** | HTTP (AHA API) | ← HIER: Suboptimal |

**Problem:** HP-Polling ist absichtlich auf 60s gesetzt (Sicherheit), aber:
- DataCollector läuft im Automation-Prozess (not web-facing)
- getdevicelistinfos() ist sehr effizient (ein Request für alle Geräte)
- **Für zwei Fritz!DECT-Geräte (HP + Klima):** Kann DERSELBE Request beide holen!

---

## 3. Empfohlene Polling-Frequenz für HP + Klima

### Option A: **10 sekunden (EMPFOHLEN)**

```python
_FRITZDECT_POLL_INTERVAL = 10  # Sekunden
```

**Begründung:**
- `getdevicelistinfos()` ist ONE QUERY für beide Geräte
- Fritz!Box kann lokal ≥10 reqs/sec verkraften
- Raspberry Pi 4 hat genug CPU für 10s-Zyklus
- **Datenqualität:** Bessere Echtzeit für Automation (Schutzregeln!)
- **Vergleich:** Fronius Modbus läuft 10s, WP-Collector 30s → 10s ist konsistent

**Safety-Check:**
```
Requests/Minute: 6 (vs. 1 aktuell)
Expected load: ~50ms pro Abfrage × 6 = 300ms/min (0.5%)
Fritz!Box CPU: Vernachlässigbar
```

### Option B: 30 sekunden (KONSERVATIV)

```python
_FRITZDECT_POLL_INTERVAL = 30
```

**Nur wenn:**
- Kein akutes Echtzeitbedarf für Schutzregeln
- Sicherheit vor Hardware-Überlast ist absolute Priorität
- Kompatibilität mit älteren Fritz!Box-Modellen

---

## 4. Request-Struktur (optimal)

```python
# AKTUELL (suboptimal):
for each AIN:
    getdevicelistinfos() → filtered für eine AIN

# BESSER (neu):
geraete = [
    {'id': 'hp', 'ain': '00000 0000000'},
    {'id': 'klima', 'ain': '09000000XXXXX'}
]

# SINGLE REQUEST → beide Geräte
all_devices = _aha_device_info_list(host, sid)  # Holt ALLE angeschlossenen

# Parse:
for gerät in geraete:
    info = all_devices.get(gerät['ain'].replace(' ', ''))
    # power_mw, energy_wh, state, name
```

---

## 5. Implementation Guide

### 5.1 Config erweitern

**config/fritz_config.json:**
```json
{
  "fritz_ip": "192.168.178.1",
  "geraete": [
    {
      "id": "heizpatrone",
      "ain": "00000 0000000",
      "name": "Heizpatrone (WW)",
      "nennleistung_w": 2000
    },
    {
      "id": "klimaanlage",
      "ain": "09000000XXXXX",
      "name": "Klimaanlage",
      "nennleistung_w": 2500
    }
  ],
  "polling_interval_s": 10
}
```

### 5.2 DataCollector-Update

```python
class DataCollector:
    
    _FRITZDECT_POLL_INTERVAL = 10  # ← neu: 10s statt 60s
    _fritzdect_device_cache: dict = {}
    _fritzdect_cache_ts: float = 0
    
    def _collect_fritzdect_devices(self, obs: ObsState):
        """Alle Fritz!DECT-Geräte in EINEM Request erfassen."""
        now = time.time()
        cfg = _load_fritz_config()
        
        # Cache-Check
        if (self._fritzdect_device_cache 
            and (now - self._fritzdect_cache_ts) < self._FRITZDECT_POLL_INTERVAL):
            all_devices = self._fritzdect_device_cache
        else:
            sid = _get_session_id(...)
            all_devices = _aha_device_info_all(host, sid)  # ONE REQUEST!
            self._fritzdect_device_cache = all_devices
            self._fritzdect_cache_ts = now
        
        # Pro Gerät: Daten in obs_state schreiben
        for gerät in cfg.get('geraete', []):
            dev_id = gerät['id']
            ain = gerät['ain'].replace(' ', '')
            info = all_devices.get(ain)
            
            if not info:
                continue
            
            # Mapping zu ObsState-Attributen
            if dev_id == 'heizpatrone':
                obs.heizpatrone_power_w = (info.get('power_mw') or 0) / 1000
                obs.heizpatrone_aktiv = info.get('state') == '1'
            elif dev_id == 'klimaanlage':
                obs.klima_power_w = (info.get('power_mw') or 0) / 1000
                obs.klima_aktiv = info.get('state') == '1'
```

### 5.3 ObsState-Update

```python
@dataclass
class ObsState:
    # ── Heizpatrone ──
    heizpatrone_aktiv: bool = False
    heizpatrone_power_w: Optional[float] = None  # NEU
    heizpatrone_power_avg30_w: Optional[float] = None  # NEU
    heizpatrone_today_kwh: Optional[float] = None  # NEU
    
    # ── Klimaanlage ──
    klima_aktiv: bool = False  # NEU
    klima_power_w: Optional[float] = None  # NEU
    klima_power_avg30_w: Optional[float] = None  # NEU
    klima_today_kwh: Optional[float] = None  # NEU
```

---

## 6. Safety-Checks vor Rollout

**Test-Skript (5 Minuten):**

```bash
cd automation/engine/collectors
python3 -c "
from data_collector import DataCollector
from obs_state import ObsState
import time

dc = DataCollector()
start = time.time()

for i in range(30):  # 30 Zyklen = 5 Min bei 10s
    obs = ObsState()
    dc._collect_fritzdect_devices(obs)
    
    print(f'{time.time()-start:.0f}s: HP={obs.heizpatrone_power_w}W, '
          f'Klima={obs.klima_power_w}W')
    
    time.sleep(10)
"
```

**Kriterien für Erfolg:**
- ✅ Keine HTTP-Timeouts (>10s)
- ✅ Keine Session-ID-Fehler
- ✅ Consistent power readings (nicht ±>500W jitter ohne Grund)
- ✅ Fritz!Box bleibt responsive (<100ms SSH-Latenz)

---

## 7. Fallback-Strategie

Wenn 10s zu aggressiv ist:

```python
# Adaptive Frequenz:
if fritz_error_rate > 0.1:  # >10% Fehlerquote
    _FRITZDECT_POLL_INTERVAL = 30
    LOG.warning("Fritz!DECT: Fallback zu 30s Intervall")
```

---

## 8. Monitoring

**Metrics zu tracken:**
- Request-Latenz: histogram (0–10s)
- Error-Rate: count/minute
- Cache-Hitrate: % (sollte ~83% bei 60s TTL sein)
- Fritz!Box Load: SSH-Latenz (Baseline vs. ±50%)
