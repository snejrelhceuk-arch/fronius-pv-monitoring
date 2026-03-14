# Beobachtungskonzept — PV-Anlage Erlau

**Erstellt:** 2026-02-20  
**Standort:** Erlau 51.01 °N 12.95 °O, ca. 270 m NN  
**System:** 37.59 kWp / 3 WR / 2× BYD HVS 20.48 kWh / RPi5-Collector

---

## 1. Zweck

Dieses Dokument beschreibt, welche Messgrößen das System aktuell beobachtet,
mit welchem Protokoll und Polling-Intervall, und welche Größen **noch fehlen**
(Hardware vorhanden, aber noch nicht integriert).

Grundlage für die Automation ist immer eine vollständige Beobachtung aller
relevanten Größen — erst dann können deterministische oder fuzzy Regeln sicher
greifen, ohne auf Heuristiken oder Annahmen angewiesen zu sein.

**Compliance-Hinweis:**
Dieses Dokument beschreibt ausschließlich legitime Integrationsnutzung mit eigenen
Berechtigungen. Es enthält keine Anleitung zur Umgehung von Hersteller- oder
Plattform-Schutzmechanismen. Maßgeblich ist die Veröffentlichungsregel in
`doc/VEROEFFENTLICHUNGSRICHTLINIE.md`.

---

## 2. Aktive Datenkanäle

### 2.1 Fronius Modbus TCP (SunSpec)

| Modul | Datenpunkt | Register | Intervall | Quelle |
|---|---|---|---|---|
| Common (M1) | Seriennummer, SW-Version | 40004+ | einmalig | modbus_v3.py |
| Inverter (M103) | AC-Leistung, Frequenz, DC-Leistung, Status | 40072+ | 5 s | modbus_v3.py |
| Storage (M124) | StorCtl_Mod, MinRsvPct, ChaState (SOC), InWRte, OutWRte | 40348+ | 5 s | battery_control.py |
| MPPT (M160) | String-Leistung per MPPT | 40273+ | 5 s | modbus_v3.py |
| F2 (Heizhaus) | wie F1 ohne Batterie | — | 5 s | modbus_v3.py |
| F3 (Fassade) | wie F1 ohne Batterie | — | 5 s | modbus_v3.py |

**Status:** ✅ Aktiv, stabil. Latenz ~50 ms.

### 2.2 Fronius HTTP-Schnittstelle (lokaler Zugriff)

| Datenpunkt | Endpunkt | Intervall | Quelle |
|---|---|---|---|
| SOC_MODE, SOC_MIN, SOC_MAX | `/config/batteries` | 15 min (Scheduler) | fronius_api.py |
| SOC detailliert, SOH | `/status/powerflow` | 30 s | collector.py |
| Tages-Energie (PV/Netz/Batt) | `/GetPowerFlowRealtimeData` | 30 s | collector.py |
| Wechselrichter-Temperaturen | `/status/devices` | 60 s | fronius_api.py |
| BMS-Daten (Zellspannung, Temp) | `/status/powersupply` | 60 s | fronius_api.py |

**Status:** ✅ Aktiv. Authentifizierung gemäß legitimen Zugangsdaten und
Hersteller-/Produktvorgaben. Latenz ~200 ms.

### 2.3 SolarWeb (Fronius Cloud)

| Datenpunkt | Kanal | Intervall | Quelle |
|---|---|---|---|
| 5-min-Aggregat PV/Verbrauch/Netz | CSV Export | täglich (Cron) | imports/solarweb/ |
| Historische kWh-Daten | SolarWeb API | bei Bedarf | scripts/import_solarweb_daily.py |

**Status:** ✅ Import aktiv. Nur für Retrospektive/Kalibrierung, nicht für Echtzeit-Steuerung.

**Hinweis zur Veröffentlichung:**
Bei externer Veröffentlichung nur eigene Formulierungen verwenden und auf
öffentliche Herstellerquellen verlinken (statt Inhalte zu kopieren).

### 2.4 Solar-Prognose (intern)

| Datenpunkt | Methode | Intervall | Quelle |
|---|---|---|---|
| String-Prognose (kWh/h) | Geometrie + Wolken | 15 min | solar_forecast.py |
| Wolkenbedeckung % | Open-Meteo API | 15 min | solar_forecast.py |
| Strahlungsintensität | Open-Meteo (DNI/GHI) | 15 min | solar_forecast.py |
| Sonnenauf-/untergang | solar_geometry.py | täglich | solar_geometry.py |

**Status:** ✅ Aktiv. Genauigkeit: ±15–25 % (typisch), bessere Kalibrierung ausstehend.

### 2.5 Wattpilot (E-Auto-Ladung)

| Datenpunkt | Kanal | Intervall | Quelle |
|---|---|---|---|
| Status (laden/warten/bereit) | WebSocket JSON | 10 s | wattpilot_collector.py |
| Ist-Leistung (W), Energie (kWh) | WebSocket | 10 s | wattpilot_collector.py |
| Phasenströme (A) | WebSocket | 10 s | wattpilot_collector.py |
| Ladefreigabe setzen | WebSocket CMD | bei Bedarf | wattpilot_api.py |
| E-Auto SOC | **fehlt** — E-Autos haben keine Schnittstelle | — | — |

**Status:** ✅ Collector aktiv. E-Auto-SOC nicht verfügbar (Renault Zoe + Citroën haben kein OBD-Interface das aktiv abrufbar ist).

---

## 3. Fehlende / nicht integrierte Datenkanäle

### 3.1 Dimplex SIK 11 TES Wärmepumpe — LWPM 410 Modbus RTU

| Eigenschaft | Wert |
|---|---|
| Protokoll | Modbus RTU (RS485, 9600 Bd, 8N1) |
| Interface | MEGA-BAS HAT RS485 (vorhanden, nicht verdrahtet) |
| Adresse | noch unbekannt (Inbetriebnahme ausstehend) |
| SG-Ready | 2 Binäreingänge (Smart Grid) |
| Geplante Datenpunkte | Betriebsmodus, Ist-Leistung, Vorlauf-T, Rücklauf-T, WW-T, Kompressor-Hz |

**Status:** ⚠️ LWPM 410 Modul bestellt, nicht eingebaut. Keine Software-Integration.
**Priorität:** Hoch — WP ist mit 2–4.3 kW der größte flexibel steuerbare Verbraucher.

### 3.2 MEGA-BAS HAT — Multikanal-Sensor (I2C 0x48)

| Kanal | Geplante Nutzung | Status |
|---|---|---|
| Thermistor × 4 | Warmwasserspeicher-Temperatur, Raum-T | Hardware da, keine SW |
| 0–10 V Eingang × 2 | Pufferspeicher-Temperaturfühler | Hardware da, keine SW |
| RS485 | WP Modbus RTU | Kabel fehlt |

**Status:** ⚠️ Hardware vorhanden (Pi4 HAT), Software noch nicht aktiviert.

### 3.3 E-Auto SOC

| Auto | Möglichkeit | Status |
|---|---|---|
| Renault Zoe 1 (50 kWh) | OBD2 über CAN — nur wenn Fahrzeug verbunden und entsperrt | Nicht implementiert |
| Renault Zoe 2 (50 kWh) | idem | Nicht implementiert |
| Citroën e-C4 | idem | Nicht implementiert |

**Workaround:** SOC-Schätzung aus Ladeenergie (bekannte Fahrzeugkapazität − geladene kWh) — ungenau aber brauchbar für Urgency-Score.

### 3.4 Netz-Qualität (Frequenz, Spannung)

Verfügbar über Modbus M103 `PhVphA`, `Hz` — wird gesammelt aber nicht für Automation ausgewertet.  
Interessant für: Frequenz-Regelung, Über-/Unterspannungsschutz.

### 3.5 Fritz!DECT Steckdosen

✅ **Integriert seit 2026-02-28.** `AktorFritzDECT` steuert die Heizpatrone (2 kW)
über Fritz!Box AHA-HTTP-API (`setswitchon`/`setswitchoff`).
Konfiguration: `config/fritz_config.json` (IP, AIN), Credentials via `.secrets`.
Regelkreis: `RegelHeizpatrone` in `automation/engine/engine.py`.

Weitere Fritz!DECT-Steckdosen könnten zusätzliche Verbraucher steuern (Klimaanlage etc.).

---

## 4. Beobachtungsqualität und Zuverlässigkeit

| Kanal | Verfügbarkeit | Ausfall-Risiko | Fallback |
|---|---|---|---|
| Modbus TCP (F1/F2/F3) | 99 % | Netz-Ausfall | Letzte bekannte Werte (< 2 min) |
| Fronius HTTP API | 97 % | WR-Neustart | State-File (Legacy) |
| Open-Meteo (Prognose) | 95 % | Internet-Ausfall | Letzter bekannter Forecast (< 6 h) |
| Wattpilot WebSocket | 90 % | WS-Verbindungsverlust | Auto-Reconnect (monitor_wattpilot.sh) |
| MEGA-BAS (geplant) | — | — | — |
| WP Modbus RTU (geplant) | — | — | — |

---

## 5. Beobachtungszustand — Definition

Für Automation-Entscheidungen wird ein **Beobachtungszustand-Objekt** (OZ) aus allen verfügbaren Kanälen zusammengesetzt:

```python
ObsState = {
    # Erzeuger
    'pv_total_w':      float,   # Summe F1+F2+F3 gesamt [W]
    'pv_f1_w':         float,
    'pv_f2_w':         float,
    'pv_f3_w':         float,
    'forecast_kwh':    float,   # Tagesprognose [kWh]
    'sunshine_hours':  float,   # Prognostizierte Sonnenstunden heute [h]
    'cloud_avg_pct':   float,   # Wolkenbedeckung [%]

    # Speicher
    'batt_soc_pct':    float,   # BYD SOC [0–100]
    'batt_soh_pct':    float,   # BYD SOH [0–100]
    'batt_power_w':    float,   # positiv=Laden, negativ=Entladen
    'batt_temp_c':     float,   # Zelltemperatur [°C]
    'soc_min':         int,     # Fronius SOC_MIN-Setting [%]
    'soc_max':         int,     # Fronius SOC_MAX-Setting [%]
    'soc_mode':        str,     # 'auto' | 'manual'

    # Netz
    'grid_power_w':    float,   # positiv=Bezug, negativ=Einspeisung
    'grid_freq_hz':    float,
    'grid_volt_v':     float,
    'i_l1_netz_a':     float,   # Phasenstrom L1 SmartMeter Netz [A]
    'i_l2_netz_a':     float,   # Phasenstrom L2 SmartMeter Netz [A]
    'i_l3_netz_a':     float,   # Phasenstrom L3 SmartMeter Netz [A]
    'i_max_netz_a':    float,   # max(L1,L2,L3) — für SLS-Schutz

    # Verbraucher
    'house_load_w':    float,   # Hausverbrauch [W] (inkl. WP, ohne Wattpilot)
    'wp_power_w':      float,   # WP elektrisch [W] — geplant
    'ev_power_w':      float,   # Wattpilot [W]
    'ev_state':        str,     # 'charging'|'waiting'|'ready'|'disconnected'
    'ev_soc_est_pct':  float,   # Schätzung aus Ladeenergie (wenn verfügbar)

    # Zeit / Geometrie
    'now':             datetime,
    'sunrise':         float,   # Uhrzeit als Dezimalstunde
    'sunset':          float,
    'sun_elev_deg':    float,
    'is_day':          bool,

    # Sensorik (geplant)
    'wp_vl_temp_c':    float,   # WP-Vorlauf [°C] — fehlt noch
    'ww_temp_c':       float,   # Warmwasserspeicher [°C] — fehlt noch
    'room_temp_c':     float,   # Raumtemperatur [°C] — fehlt noch
}
```

Fehlende Werte werden als `None` übergeben — Regeln müssen `None`-sicher sein.

---

## 6. Priorisierung fehlender Daten

| Priorität | Datenpunkt | Warum |
|---|---|---|
| 1 | WP Betriebsmodus + Ist-Leistung | Größter flexibler Verbraucher, 2–4.3 kW |
| 2 | WW-Speicher Temperatur | Notwendig für WP-Schutzregel (Überhitzung) |
| 3 | E-Auto SOC (Schätzung) | Urgency-Score für Ladepriorisierung |
| 4 | Raumtemperatur | Komfort-Daten für WP-Steuerung |
| ~~5~~ | ~~Netz Phasenströme F1/F2/F3~~ | ✅ Implementiert (2026-03-08): `i_l1/l2/l3_netz_a`, `i_max_netz_a` in ObsState. Genutzt von `RegelSlsSchutz` (35A/Phase). |

---

*Letzte Aktualisierung: 2026-03-08*  
*Verwandte Dokumente:* [PARAMETER_MATRIZEN.md](PARAMETER_MATRIZEN.md) · [SCHUTZREGELN.md](SCHUTZREGELN.md) · [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md)
