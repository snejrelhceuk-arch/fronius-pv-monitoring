# Batterie-Energiezähler: Entdeckung & Implementierungsplan

**Datum:** 11.02.2026 (Analyse), Implementierung: 12.02.2026  
**Anlass:** K5 aus AGGREGATION_AUDIT — Batterie-Energie bisher rein P×t-basiert  
**Ergebnis:** ✅ Hardware-Energiezähler in Fronius interner API gefunden!

---

## 1. Ausgangslage

Die Batterie-Energie wurde bisher in der gesamten Pipeline per P×t berechnet:
```
p_batt = P_DC_Inv - (P_MPPT1 + P_MPPT2)     # Differenz = Batterie
w_batt = abs(p_batt) × dt_hours               # Integration über Zeit
```

**Probleme:**
- Genauigkeit ~90-95% (Zeitvarianz 3-57s, Leistungsspitzen zwischen Polls)
- Solarweb nutzt dieselbe berechnete Methode → ebenfalls ungenau
- Kein Modbus-Register mit Batterie-Wh-Zähler im SunSpec Model 124

---

## 2. Entdeckung: Fronius Interne Component-API

### 2.1 API-Endpunkte

| Endpunkt | Inhalt | Auth |
|----------|--------|------|
| `/components/readable` | ALLE Komponenten + Channels | Nein |
| `/components/BatteryManagementSystem/readable` | Nur BMS-Daten | Nein |

**⚠️ Warnung:** Header enthält `"Note: this internal API may be changed any time"`.  
→ Graceful Fallback auf P×t bei Fehler erforderlich.

### 2.2 BYD BMS Component (ID: 16580608)

**Attribute:**
```
device-class:     Storage
manufacturer:     BYD
model:            BYD Battery-Box Premium HV
serial:           P030T020Z2104140191
sw_version:       3.26
hw_version:       5.0
capacity_wh:      10240
addr:             21 (Modbus RTU /dev/rtu0)
createTS:         1767477422 (2026-01-03 22:57:02)
max_power_charge: 10240 W
max_power_dischg: 10240 W
peak_power:       13312 W (10s)
min_soc:          5%
max_soc:          100%
max_udc:          467.2 V
min_udc:          320.0 V
```

**Energiezähler (in Wattsekunden / Ws):**
```
BAT_ENERGYACTIVE_LIFETIME_CHARGED_F64       = 41.098.914.000 Ws = 11.416,4 kWh
BAT_ENERGYACTIVE_LIFETIME_DISCHARGED_F64    = 36.888.843.600 Ws = 10.246,9 kWh
BAT_ENERGYACTIVE_MAX_CAPACITY_F64           =     33.912.000 Ws =  9.420,0 Wh  (= 10.240 × 92% SoH)
BAT_ENERGYACTIVE_ESTIMATION_MAX_CAPACITY_F64=      8.409.600 Ws =  2.336,0 Wh  (= SOC × MAX_CAPACITY)
```

**Batterie-Zustand:**
```
BAT_VALUE_STATE_OF_CHARGE_RELATIVE_U16      = 24,8%  (SOC)
BAT_VALUE_STATE_OF_HEALTH_RELATIVE_U16      = 92,0%  (SoH) ← NEU! Permanent anzeigen!
BAT_MODE_HYBRID_OPERATING_STATE_U16         = 5      (Operating State)
BAT_TEMPERATURE_CELL_F64                    = 16,5°C (Durchschnitt)
BAT_TEMPERATURE_CELL_MAX_F64                = 18,0°C
BAT_TEMPERATURE_CELL_MIN_F64                = 15,0°C
BAT_VOLTAGE_DC_INTERNAL_F64                 = 419,3 V
BAT_CURRENT_DC_F64                          = 0,0 A
BAT_CURRENT_DC_INTERNAL_F64                 = 0,0 A
BAT_MODE_WAKE_ENABLE_STATUS_U16             = 1
BAT_VALUE_WARNING_CODE_U16                  = 46
DCLINK_POWERACTIVE_LIMIT_DISCHARGE_F64      = 10.734 W
DCLINK_POWERACTIVE_MAX_F32                  = 10.810 W
```

---

## 3. Fronius Gen24 Inverter Component (ID: 0)

**109 Channels — Auswahl energierelevant:**

### 3.1 Batterie-Counter (WR-seitig, am DC-Bus)
```
BAT_ENERGYACTIVE_ACTIVECHARGE_SUM_01_U64    = 17.630.010.528 Ws = 4.897,2 kWh
BAT_ENERGYACTIVE_ACTIVEDISCHARGE_SUM_01_U64 = 16.682.443.151 Ws = 4.634,0 kWh
BAT_POWERACTIVE_MEAN_F32                    = 0,0 W (aktuell)
```

### 3.2 PV-String-Counter (DC-seitig)
```
PV_ENERGYACTIVE_ACTIVE_SUM_01_U64           = 44.637.744.510 Ws = 12.399,4 kWh  (String 1)
PV_ENERGYACTIVE_ACTIVE_SUM_02_U64           = 18.548.640.506 Ws =  5.152,4 kWh  (String 2)
PV_POWERACTIVE_MEAN_01_F32                  = 0,0 W (String 1, nachts)
PV_POWERACTIVE_MEAN_02_F32                  = 0,0 W (String 2, nachts)
```

### 3.3 AC-Bridge (Wechselrichter-Ausgang)
```
ACBRIDGE_ENERGYACTIVE_ACTIVECONSUMED_SUM_01_U64  (Phase 1 Import)
ACBRIDGE_ENERGYACTIVE_ACTIVEPRODUCED_SUM_01_U64  (Phase 1 Export)
ACBRIDGE_ENERGYACTIVE_ACTIVECONSUMED_SUM_02_U64  (Phase 2 Import)
ACBRIDGE_ENERGYACTIVE_ACTIVEPRODUCED_SUM_02_U64  (Phase 2 Export)
ACBRIDGE_ENERGYACTIVE_ACTIVECONSUMED_SUM_03_U64  (Phase 3 Import)
ACBRIDGE_ENERGYACTIVE_ACTIVEPRODUCED_SUM_03_U64  (Phase 3 Export)
ACBRIDGE_CURRENT_ACTIVE_MEAN_01_F32              (Phase 1 Strom)
ACBRIDGE_CURRENT_ACTIVE_MEAN_02/03_F32
ACBRIDGE_VOLTAGE_MEAN_01/02/03_F32
ACBRIDGE_POWERACTIVE_MEAN_SUM_F32
```

---

## 4. Smart Meter Components (4 Stück)

### SM Netz (Component 16252928 / 16253176)
```
SMARTMETER_ENERGYACTIVE_CONSUMED_SUM_F64    = 16.264.640 Wh  (Bezug Lifetime)
SMARTMETER_ENERGYACTIVE_PRODUCED_SUM_F64    =    719.605 Wh  (Einspeisung Lifetime)
SMARTMETER_POWERACTIVE_MEAN_SUM_F64         =    480,9 W     (aktuell)
+ je 3 Phasen: POWERACTIVE, POWERAPPARENT, POWERREACTIVE, FACTOR_POWER
```
Note: Component 16252928 und 16253176 zeigen identische Werte — vermutlich Alias/Mirror.

### SM F2 (Component 16711684)
```
SMARTMETER_ENERGYACTIVE_CONSUMED_SUM_F64    = 6.145.289 Wh   (Bezug F2)
SMARTMETER_ENERGYACTIVE_PRODUCED_SUM_F64    =   851.213 Wh   (Erzeugung F2)
```

### SM F3 (Component 16711681)
```
SMARTMETER_ENERGYACTIVE_CONSUMED_SUM_F64    =    33.652 Wh   (Bezug F3)
SMARTMETER_ENERGYACTIVE_PRODUCED_SUM_F64    = 3.067.584 Wh   (Erzeugung F3)
```

### SM Wärmepumpe (Component 16253184 / 16711683)
```
SMARTMETER_ENERGYACTIVE_CONSUMED_SUM_F64    = 1.755.834 Wh   (Verbrauch Wärmepumpe)
SMARTMETER_ENERGYACTIVE_PRODUCED_SUM_F64    =         0 Wh   (kein Export)
Nur Phase 2 aktiv (einphasige WP-Anbindung)
```

**WICHTIG:** WP = Wärmepumpe (Heat Pump), NICHT Wattpilot!
Wattpilot ist eine separate Fronius Wallbox mit eigener WebSocket-API.

---

## 5. Drei Quellen im Vergleich (Batterie)

| Quelle | Laden (kWh) | Entladen (kWh) | Effizienz | Messpunkt |
|--------|-------------|-----------------|-----------|-----------|
| **Solarweb** | 12.050 | 11.230 | 93,2% | P_Akku berechnet (Cloud-P×t) |
| **BMS LIFETIME** | 11.416 | 10.247 | 89,8% | BYD Zell-Terminal (Hardware) |
| **WR ACTIVESUM** | 4.897 | 4.634 | 94,6% | DC-Bus Gen24 (Hardware, resettiert!) |

### 5.1 Diskrepanz-Analyse

**WR ACTIVESUM << Solarweb/BMS:** Der `createTS: 2026-01-03 22:57` zeigt, dass die
BMS-Komponente am 3. Januar 2026 neu registriert wurde (vermutlich Firmware-Update).
Dabei wurden die WR-seitigen Counter resettiert. Solarweb behält seine Cloud-Summe.

**BMS LIFETIME < Solarweb:**
```
Laden:    Solarweb 12.050 → BMS 11.416  (BMS 5,3% weniger)
Entladen: BMS 10.247 → Solarweb 11.230  (Solarweb 9,6% MEHR)
```

**Physikalische Unmöglichkeit bei Entladung:** Aus 10.247 kWh Zellenergie können
nicht 11.230 kWh am DC-Bus ankommen. Energie kann nur verloren gehen, nicht entstehen!

**Erklärung:** Solarweb akkumuliert `P_Akku` aus `GetPowerFlowRealtimeData`:
```
P_Akku = P_DC_total − P_MPPT1 − P_MPPT2
```
Drei Sensoren mit je ±1-2% Toleranz → systematischer Bias auf P_Akku.
Bei ~1% MPPT-Bias und ~5h Lade/Entlade pro Tag über ~1.280 Zyklen ≈ 400-800 kWh Drift.

### 5.2 Fazit

| | BMS LIFETIME | WR ACTIVESUM | Solarweb |
|--|-------------|-------------|----------|
| **Genauigkeit** | ★★★ Hardware-Zähler an Zellen | ★★★ Hardware-Zähler am DC-Bus | ★★ Berechnete P×t-Integration |
| **Stabilität** | ✅ Kein Reset (LIFETIME) | ⚠️ Reset bei FW-Update | ✅ Cloud-seitig persistent |
| **Messpunkt** | DC Batterie-Klemmen | DC-Bus WR | Rechenwert |

**→ BMS LIFETIME = genaueste und stabilste Quelle. Verwenden wir!**

---

## 6. Offene Fragen (zu klären am 12.02.2026)

### 6.1 Counter-Aktualisierungsrate

Die BMS-Counter sind LIFETIME-Werte in Ws (Wattsekunden). Noch unklar:
- Wie oft aktualisiert das BMS den Zählerstand? (Sekündlich? Alle 5s? Bei Zustandswechsel?)
- Reicht die Granularität für 15min-Aggregation (MIN/MAX Delta)?

**Test:** Morgen bei Last/PV mehrere Abfragen im Sekundentakt → Schrittweite beobachten.

### 6.2 Implementierungsschritte

1. **`fetch_battery_counters()`** — Neue Funktion in `modbus_v3.py`
   - HTTP GET `/components/BatteryManagementSystem/readable`
   - Parse: LIFETIME_CHARGED/DISCHARGED (Ws→Wh), SOH, Zelltemps
   - Timeout: 2s, Graceful Fallback bei Fehler

2. **4 neue Spalten in `raw_data`:**
   - `W_Batt_Charge_BMS` — BMS Lade-Zähler (kumulativ, Wh)
   - `W_Batt_Discharge_BMS` — BMS Entlade-Zähler (kumulativ, Wh)
   - `SOH_Batt` — State of Health (%)
   - `T_Batt_Cell` — Zelltemperatur (°C)

3. **Polling-Strategie:**
   - Alle 60s (im flush_buffer_to_db Zyklus) — kein Overhead auf 3s-Loop
   - Oder: Alle 3s parallel zur Modbus-Abfrage (HTTP, nicht Modbus → kein Bus-Konflikt)

4. **Aggregation (Pipeline B):**
   - `aggregate.py` (15min): `MAX(W_Batt_Charge_BMS) - MIN(W_Batt_Charge_BMS)` → Delta
   - Gleiche bewährte Counter-Delta-Methode wie W_DC1, W_DC2, W_Exp_Netz

5. **SOH permanent anzeigen:**
   - In `web_api.py` → Status-Endpoint / Dashboard-Header
   - Neben SOC, Batterie-Status, Temperatur

### 6.3 Weitere nutzbare Daten aus der API

| Channel | Nutzen | Priorität |
|---------|--------|-----------|
| `BAT_VALUE_STATE_OF_HEALTH_RELATIVE_U16` | SoH-Tracking über Lebensdauer | ★★★ |
| `BAT_TEMPERATURE_CELL_MIN/MAX_F64` | Batterie-Thermomanagement | ★★ |
| `BAT_VALUE_WARNING_CODE_U16` | Fehlerfrüherkennung | ★★ |
| `BAT_MODE_HYBRID_OPERATING_STATE_U16` | Betriebszustand | ★★ |
| `DCLINK_POWERACTIVE_MAX_F32` | Maximale Entladeleistung | ★ |
| `PV_ENERGYACTIVE_ACTIVE_SUM_01/02_U64` | PV-String-Counter (Crosscheck) | ★ |
| `ACBRIDGE_ENERGYACTIVE_*` | AC-Phase-Counter | ★ |

---

## 7. Zusammenfassung

Die Fronius Gen24 interne Component-API `/components/BatteryManagementSystem/readable`
liefert echte **BYD BMS Hardware-Energiezähler** in Wattsekunden:
- **Genauer** als Solarweb (Hardware vs. berechnete P×t)
- **Resettfrei** (LIFETIME-Zähler, nicht WR-seitig)
- **Zusätzlich:** SoH, Zelltemperaturen, Warnungen — alles bisher nicht verfügbar

Das bisherige P×t-Verfahren (K5 im Audit) kann damit durch echte Counter-Deltas
ersetzt werden — gleiche Methode wie für alle anderen Energieflüsse.

**Erwartete Verbesserung:** Batterie-Genauigkeit von ~90% (P×t) auf ~99% (Counter).

---

*Nächster Schritt: 12.02.2026 — Counter-Aktualisierungsrate testen + Implementierung*
