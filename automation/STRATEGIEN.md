# Betriebsstrategien — PV-Eigenverbrauchsmaximierung

> Stand: 2026-02-14

---

## 1. Übersicht Energieprioritäten

### Grundprinzip: Eigenverbrauch maximieren (Nulleinspeiser!)

```
                    PV-Erzeugung (37,59 kWp, max. 26,5 kW AC)
                           │
                           ▼
                ┌─────────────────────┐
                │   Hausverbrauch     │  ← Immer Priorität 1
                │   (Grundlast ~3kW) │
                └─────────┬───────────┘
                          │ Überschuss
                          ▼
              ┌───────────────────────┐
              │  Batterie (10,24 kWh) │  ← Priorität 2 (Winter: hoch)
              └───────────┬───────────┘
                          │ Überschuss
                          ▼
        ┌─────────────────────────────────┐
        │  E-Auto (Wattpilot, max. 22 kW) │  ← Priorität 3 (wenn verfügbar)
        └─────────────────┬───────────────┘
                          │ Überschuss
                          ▼
        ┌─────────────────────────────────┐
        │  Heizpatrone (2 kW)             │  ← Priorität 4 (Speicher <80°C)
        │  Klimaanlage (1,3 kW)           │  ← Priorität 4 (parallel möglich)
        └─────────────────┬───────────────┘
                          │ Überschuss
                          ▼
                    ┌─────────────┐
                    │ Einspeisung │  ← 0 (Nulleinspeiser!)
                    │ = Verlust!  │
                    └─────────────┘
```

> **Leistungsbilanz:** Heizpatrone (2kW) + Klima (1,3kW) = 3,3 kW
> Bei 37,59 kWp Anlage (max. 26,5 kW AC) bleibt massiv Kapazität für E-Autos.
> Verbrauch 2025 lt. PV-Referenz: Heizpatrone 2.614 kWh, Klima geschätzt ~500 kWh.

---

## 2. Detailstrategien nach Jahreszeit

### 2.1 Winternahe Übergangszeit (Problem: Wenig PV, aber schon wärmer)

**Situation:**
- PV liefert etwas, aber nicht genug für Heizpatrone allein
- WP wird noch für Heizung gebraucht
- E-Auto-Batterie oft leer (tägliches Pendeln)
- Heizpatrone wäre zu ineffizient bei < 2 kW Überschuss

**Strategie:**
```
WENN PV_Überschuss > 0 UND E-Auto angesteckt UND E-Auto SOC < 80%:
    → E-Auto laden (Wattpilot PV-Modus)
    → Bypass EIN (WP macht nur oberen Speicherteil warm)

WENN PV_Überschuss > 0 UND KEIN E-Auto:
    → Bypass EIN
    → Batterie laden
    → Heizpatrone? Nur wenn Überschuss > 2kW UND Speicher_oben < 50°C

IMMER: WP macht Heizung + Warmwasser (Grundbetrieb)
```

### 2.2 Übergangszeit (März–April, September–Oktober)

**Situation:**
- PV liefert zunehmend/abnehmend gut
- Heizung kaum noch nötig
- Heizpatrone wird sinnvoll

**Strategie:**
```
WENN Speicher_oben < 55°C UND PV_Überschuss > 2 kW:
    → Heizpatrone EIN
    → Bypass AUS (ganzer Speicher)

WENN Speicher_oben > 65°C ODER PV_Überschuss < 1 kW:
    → Heizpatrone AUS

WENN WP heute noch nicht gelaufen:
    → WP über Modbus RTU in "Verstärkten Betrieb" setzen
      (Smart Grid = grün: Coil 3=1, Coil 4=0)
    → ODER Betriebsmodus Register 5015 auf "Auto" (Wert 1)

ÜBERSTEUERUNG: Speicher_oben > 78°C → Heizpatrone SOFORT AUS
ÜBERSTEUERUNG: WW-Isttemperatur via Modbus (Register 3) > 80°C → ALLES AUS
```

### 2.2.1 Nacht-Strategie Übergangszeit (Heizung sperren, WW beibehalten)

**Ziel:** Nachts keine Raumheizung (→ bevorzugt tagsüber bei PV-Überschuss),
aber Warmwasser muss **immer** verfügbar bleiben.

**Umsetzung via Modbus Betriebsmodus (Register 5015):**

```
ABENDS (20:00, Übergangszeit Okt–März):
    → Modbus Register 5015 = 0 ("Sommer")
    → Effekt: Raumheizung komplett AUS, WW bleibt aktiv!
    → Optional: WW-Solltemp auf 55°C setzen (Nacht-Sparwert)

MORGENS (bei PV-Überschuss ODER 08:00 als Fallback):
    → Modbus Register 5015 = 1 ("Auto")
    → Smart Grid "grün" setzen (Coil 3=1, Coil 4=0)
    → Effekt: WP heizt verstärkt mit PV-Überschuss
    → WW-Solltemp auf 65°C hochsetzen

BEI MASSIVEM PV-ÜBERSCHUSS:
    → Smart Grid "dunkelgrün" (Coil 3=1, Coil 4=1)
    → Effekt: WP + Flanschheizung (E9) auf Maximum!
    → WPM steuert Heizpatrone selbständig mit!
```

**Warum NICHT Smart Grid "rot" für Nachtsperrung?**
- "Rot" = abgesenkter Betrieb, aber Heizung läuft TROTZDEM (nur reduziert)
- "Rot" senkt auch WW-Solltemp auf Minimum → unerwünscht!
- Betriebsmodus "Sommer" ist die saubere Lösung: Heizung AUS, WW normal

**Sicherheit:**
- Frostschutz bleibt im WPM immer aktiv (unabhängig vom Modus)
- Bei Kommunikationsverlust Modbus: WPM fällt auf letzten Zustand zurück
- Watchdog: Wenn kein Modbus-Schreibzugriff > 30 Min → Register 5015 = 1 (Auto)

### 2.3 Sommer (Mai–August)

**Situation:**
- PV liefert massiv (37,59 kWp!)
- Heizung AUS
- Heizpatrone = alleinige Warmwasserbereitung
- WP-Monitoring via Modbus: Sole-Temp., Betriebsstatus, Störungen

**Strategie:**
```
MORGENS (Sonnenaufgang + 2h):
    → Prüfe WW-Temperatur via Modbus (Register 3), WW-Solltemp = 65°C
    → Prüfe Speicher_oben (MEGA-BAS Thermistor). Wenn < 45°C UND Prognose > 20 kWh:
       → Heizpatrone EIN sobald PV_Überschuss > 2 kW

TAGSÜBER (PV-Überschuss > 3 kW):
    → Heizpatrone regelt auf Zieltemperatur (60–70°C)
    → Klimaanlage bei Überschuss >3 kW UND Außentemp >25°C
    → Bei massivem Überschuss: WP auf Smart Grid "dunkelgrün" setzen
      (Coil 3=1, Coil 4=1 → WP Maximalleistung, E9 nicht relevant)
    → Heizpatrone separat steuern (Fritz!DECT API oder MEGA-BAS TRIAC→24V-Relais)
    → WW-Solltemp via Modbus auf 70°C hochsetzen (Register 5047)
    → E-Auto laden mit Restüberschuss
    → Batterie für Nacht-Eigenverbrauch laden

WP-PFLICHTLAUF:
    → 1× täglich, z.B. 12:00 (bei maximaler PV)
    → Via Modbus SG-Ready "grün" setzen (Coil 3=1, Coil 4=0)
    → Dauer: Mindestens 10–15 Min (Kompressor-Schmierung)

ABENDS:
    → Heizpatrone AUS wenn Speicher_oben > 60°C
    → Batterie übernimmt Nacht-Hausverbrauch
    → Betriebsmodus Register 5015 = 0 ("Sommer") → Heizung AUS, WW bleibt!

ÜBERSTEUERUNG: Speicher_oben > 78°C → Heizpatrone SOFORT AUS
```
    → Dauer: Minimum laut Hersteller (10–15 Min?)

ABENDS:
    → Heizpatrone AUS wenn Speicher_oben > 60°C
    → Batterie übernimmt Nacht-Hausverbrauch

ÜBERSTEUERUNG: Speicher_oben > 78°C → Heizpatrone SOFORT AUS
```

---

## 3. Sicherheitsregeln (IMMER aktiv, nicht overridebar)

| Regel | Bedingung | Aktion |
|-------|-----------|--------|
| **Übertemperaturschutz** | Speicher_oben ≥ 80°C | Heizpatrone AUS, Alarm |
| **Hysterese** | Speicher_oben ≥ 78°C | Heizpatrone AUS (Einschalten erst wieder < 70°C) |
| **Mindestpause** | Heizpatrone war < 5 Min aus | Nicht wieder einschalten |
| **Frostschutz** | Außentemp < -5°C | Lüftung auf Minimum, Brandschutzklappen ZU |
| **WP-Schmierung** | WP heute 0 Laufzeit | Pflichtlauf erzwingen |
| **Watchdog** | Software-Absturz | Hardware-WDT → TRIACs AUS (Fail-Safe) |

---

## 4. Temperatur-Schwellwerte (konfigurierbar)

```python
# config/automation_config.json
{
    "speicher": {
        "temp_max": 80,           # Absolute Grenze (°C)
        "temp_hysterese_aus": 78,  # Heizpatrone AUS
        "temp_hysterese_ein": 70,  # Heizpatrone darf wieder EIN
        "temp_ziel_sommer": 65,    # Zieltemperatur Sommer
        "temp_ziel_winter": 55,    # Zieltemperatur Winter
        "temp_min_warmwasser": 45  # Minimum für Legionellenschutz
    },
    "heizpatrone": {
        "min_ueberschuss_kw": 2.0,   # Mindest-PV-Überschuss zum Einschalten
        "min_pausenzeit_s": 300,      # 5 Min Mindestpause
        "min_laufzeit_s": 300         # 5 Min Mindestlaufzeit
    },
    "wp": {
        "pflichtlauf_dauer_min": 15,  # Minuten
        "pflichtlauf_zeit": "12:00",  # Bevorzugte Uhrzeit (PV-Maximum)
    },
    "lueftung": {
        "frostgrenze_c": -5,
        "grundlueftung_stufe": 1
    }
}
```

---

## 5. Entscheidungsbaum (vereinfacht)

```
Alle 30 Sekunden:
│
├── Temperaturen lesen (MEGA-BAS IN1–IN4)
├── PV-Daten holen (collector.py / Modbus)
├── Batterie-SOC holen
├── Wattpilot-Status holen
│
├── SICHERHEITSCHECK:
│   ├── Speicher_oben ≥ 80°C? → Heizpatrone SOFORT AUS, ALARM
│   ├── Außentemp < -5°C? → Frostschutz aktivieren
│   └── WP heute gelaufen? → Nein → Queue Pflichtlauf
│
├── ÜBERSCHUSS BERECHNEN:
│   │  PV_Überschuss = PV_Erzeugung - Hausverbrauch
│   │                  - Batterie_Ladung - Wallbox_Ladung
│   │
│   ├── Überschuss > min_ueberschuss_kw?
│   │   ├── Speicher kalt genug? → Heizpatrone EIN
│   │   ├── E-Auto da und SOC < 80%? → Wallbox erhöhen
│   │   └── Beides nicht möglich? → Batterie laden
│   │
│   └── Kein Überschuss:
│       └── Heizpatrone AUS (wenn Pausenzeit eingehalten)
│
└── Status loggen → DB + Dashboard
```
