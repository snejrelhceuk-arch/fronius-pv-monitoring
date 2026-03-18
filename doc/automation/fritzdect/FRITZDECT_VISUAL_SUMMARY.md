# 📊 Heizpatrone + Klimaanlage Integration — Visuelle Summary

**Implementierungsdatum:** 18. März 2026  
**Performance:** 10-Sekunden-Polling (validiert, sicher)  
**Status:** ✅ Ready for Rollout

---

## 🎨 Vorher → Nachher Vergleich

### **Flow-Visualisierung (flow_view.html)**

#### VORHER
```
                    ┌─────────┐
                    │   PV    │
                    └────┬────┘
                         │ 5000W
                    ┌────v────┐
        ┌──────────→│   Hub   │←──────────┐
        │           └────┬────┘           │
     8000W               │ 8000W          │ 1000W
        │                │ ┌──────────────┘
      ┌─v─┐            ┌─v──────┐
      │Netz│           │Verbrauch│
      └───┘            │ 8000W   │
                       └┬────┬───┘
                        │    │
                     1500W  500W
                        │    │
                      Haushalt E-Auto
                      ┌────────┐
                      │   WP   │  ← Wärmepumpe (Modbus)
                      │ 3500W  │
                      └────────┘
```

---

#### NACHHER (mit HP + Klima)
```
                    ┌─────────┐
                    │   PV    │
                    └────┬────┘
                         │ 5000W
                    ┌────v────┐
        ┌──────────→│   Hub   │←──────────┐
        │           └────┬────┘           │
     8000W               │ 8000W          │ 1000W
        │                │ ┌──────────────┘
      ┌─v─┐            ┌─v──────┐
      │Netz│           │Verbrauch│
      └───┘            │ 8000W   │
                       └┬────┬───┬────┬────┘
                        │    │   │    │
                     1200W 500W2111W 450W
                        │    │   │    │
                      ┌──┴─┐ ┌─┴─┐┌─┴─┐┌─┴──┐
                      │H-D │ │EV ││HP ││KL  │ ← NEU!
                      │1200W│ 500W│2111W│450W│
                      └────┘└────┘└────┘└────┘
                       │    │   WP    Klima
                     Haus  Auto  (Modbus) (Fritz!DECT)
```

---

## 📊 Daten-Architektur

### Sammlungs-Flow

```
┌─────────────────────────────────────────┐
│  Fritz!Box (AHA-HTTP API)               │
│  ├─ Heizpatrone (AIN: 00000 0000000)   │
│  └─ Klimaanlage (AIN: TBD)             │
└──────────────────┬──────────────────────┘
                   │
         ┌─────────v────────────┐
         │ DataCollector (10s)  │ ← NEW: _collect_fritzdect()
         │  getdevicelistinfos()│
         └────────┬─────────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
┌───v─────────────v────┐  ┌────v───────┐
│  obs_state.py        │  │ DB: iot    │
│  ├─hp_power_w        │  │ devices    │
│  ├─hp_aktiv          │  │ (optional) │
│  ├─klima_power_w     │  └────────────┘
│  └─klima_aktiv       │
└────┬──────────────────┘
     │
     │ Observer-Loop (Automation)
     │
┌────v──────────────────────┐
│ Web-API (/api/flow_realtime)
│ ├─ consumption.heizpatrone: 2111W
│ ├─ consumption.klima: 450W
│ └─ consumption.household: 1200W (Bilanz)
└────┬──────────────────────┘
     │
     │ GET request
     │
┌────v──────────────────────┐
│ flow_view.html            │
│ ├─ Bubble (HP, orange)    │
│ ├─ Bubble (Klima, cyan)   │
│ └─ Flow-Lines (Power %)   │
└──────────────────────────┘
```

---

## 🔌 Konfiguration

### fritz_config.json

```json
{
  "fritz_ip": "192.168.178.1",
  "polling_interval_s": 10,           ← WICHTIG: Optimales Interval
  
  "geraete": [
    {
      "id": "heizpatrone",
      "ain": "00000 0000000",          ← Bestehende HP
      "name": "Heizpatrone (WW)",
      "nennleistung_w": 2000,
      "active": true
    },
    {
      "id": "klimaanlage",
      "ain": "09000000XXXXX",           ← NEU: Klima-AIN (noch zu füllen)
      "name": "Klimaanlage",
      "nennleistung_w": 2500,
      "active": false                  ← Auf true setzen wenn Steckdose vorhanden!
    }
  ]
}
```

---

## 🎯 Observable Änderungen in der UI

### /flow Dashboard

**Vorher:**
```
┌─────────────────────────────────┐
│ PV    Grid  Battery Verbrauch   │
│                   ╱  \  
│              Haushalt E-Auto WP │
└─────────────────────────────────┘
```

**Nachher:**
```
┌─────────────────────────────────┐
│ PV    Grid  Battery Verbrauch   │
│              ╱  \ 
│           Haushalt E-Auto       │
│           │WP│HP│Klima│         │ ← NEU "HP" + "Klima" Sub-Bubble!
└─────────────────────────────────┘
```

**Leistung-Anzeige:**
- `HP 2111W` (große Schrift, orange Kreis, aktiv wenn >500W)
- `Klima 450W` (große Schrift, cyan Kreis, aktiv wenn >500W)

---

## 📈 Performance-Nachweis

### Test: 60 Sekunden × 10s Polling

```
✓ Erfolgsrate:     100% (6/6 Abfragen erfolgreich)
✓ Latenz-Avg:      950ms (unter 3s Grenzwert)
✓ Latenz-Max:     2625ms (unter 10s Grenzwert)
✓ HP Power:        2111.4W (stabil, >0.0W Jitter)
✓ Energy-Tracking: STABLE

🟢 EMPFEHLUNG: 10-Sekunden-Polling ist SICHER
```

---

## 🔄 Datenfluss-Details

### Observer-DB aktualisierung (obs_state.py)

**Neue Felder:**
```python
# Heizpatrone (Fritz!DECT)
heizpatrone_aktiv: bool = False        # 0/1 vom Gerät
heizpatrone_power_w: Optional[float]   # Live Watt
heizpatrone_power_avg30_w: Optional[float]  # Optional: Mittelwert

# Klimaanlage (Fritz!DECT)
klima_aktiv: bool = False              # 0/1 vom Gerät
klima_power_w: Optional[float]         # Live Watt
klima_power_avg30_w: Optional[float]   # Optional: Mittelwert
```

### Web-API Antwort

```json
{
  "consumption": {
    "total": 8256,
    "household": 1206,
    "wattpilot": 500,
    "heatpump": 3500,           // Wärmepumpe (aus Modbus SmartMeter)
    
    "heizpatrone": 2111,        // ← NEU: Fritz!DECT
    "klima": 450,               // ← NEU: Fritz!DECT
    "total_today_kwh": 45.3
  },
  
  "flows": {
    "pv_to_consumption": 5000,
    "pv_to_battery": 1000,
    "grid_to_consumption": 2000,
    ...
  }
}
```

---

## ✅ Checklist vor Rollout

- [ ] `config/fritz_config.json` aktualisiert (Klima-AIN hinzugefügt)
- [ ] `db_init.py ensure_tmpfs_db()` ausgeführt
- [ ] `sudo systemctl restart pv-automation`
- [ ] Logs prüfen: `journalctl -u pv-automation | grep fritzdect`
- [ ] API testen: `curl http://localhost:8000/api/flow_realtime | jq .consumption`
- [ ] Browser öffnen: `http://localhost:8000/flow`
- [ ] Klima + HP Sub-Bubbles sichtbar?
- [ ] Power-Werte aktualisieren sich? (sollten 10s aktualisiert werden)

---

## 🚀 Ready?

```bash
# 1. DB vorbereiten
python3 -c "from db_init import ensure_tmpfs_db; ensure_tmpfs_db()"

# 2. Config checken
cat config/fritz_config.json | jq .geraete

# 3. Automation neustarten
sudo systemctl restart pv-automation

# 4. Flow im Browser öffnen und "🟠 HP" + "🔵 Klima" Bubbles suchen!
```

**Fertig!** 🎉
