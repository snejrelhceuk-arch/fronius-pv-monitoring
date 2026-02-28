# Betriebsstrategien — PV-Eigenverbrauchsmaximierung

> Stand: 2026-02-28

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

### 2.6 Heizpatrone (HP) — Prognosegesteuerte Burst-Strategie (via Fritz!DECT)

> Stand: 2026-03-01 — **Produktiv** seit 2026-02-28 (`RegelHeizpatrone` + `AktorFritzDECT`)

**Abkürzungen:** HP = Heizpatrone (2 kW, Fritz!DECT-Steckdose), WP = Wärmepumpe
(Dimplex SIK 11 TES), Wattpilot = EV-Ladestation (go-eCharger).

**Hardware:** Fritz!DECT-Steckdose → 24V-Relais → Heizpatrone 2 kW.
Steuerung via Fritz!Box AHA-HTTP-API (`setswitchon`/`setswitchoff`).

**Kernproblem:** Die HP verbraucht 2 kW. Nachmittags/abends darf sie auf
keinen Fall die Batterie entladen. Gleichzeitig soll PV-Überschuss nicht
verworfen werden, wenn kein anderer Verbraucher aktiv ist.

**Warum P_PV kein guter Indikator ist:**
Die Nulleinspeiser-Anlage (37,59 kWp, max. 26,5 kW AC) regelt ab, sobald
kein Verbraucher den Strom abnimmt. Die gemessene PV-Leistung zeigt daher
**nicht** die verfügbare Kapazität, sondern nur den aktuellen Verbrauch.
Ein "geringer Überschuss" kann bedeuten, dass die Anlage massiv abgeregelt
oder dass tatsächlich kaum Sonne scheint — ununterscheidbar am P_PV allein.

**Warum SOC kein guter Trigger ist:**
Der SOC_MAX liegt aus Batterieschonung oft bei 75% (nicht 100%). Der SOC
pendelt typischerweise um 75% ± einige Prozent. Ein starrer Schwellwert
"SOC ≥ 90%" würde nie erreicht oder wäre mit der Schonstrategie inkompatibel.

**Die richtigen Indikatoren:**
1. **Batterie-Ladeleistung P_Batt** — Wenn die Batterie mit >5 kW lädt,
   ist offensichtlich genug PV-Kapazität für zusätzliche 2 kW HP vorhanden
2. **Prognose (rest_kwh, rest_h)** — Die Forecast-Engine weiß, wieviel
   Ertrag noch kommt. Das ist der einzige zuverlässige Voraus-Indikator
3. **Wattpilot-Status** — Ob EVs laden und wann sie voraussichtlich voll sind

**Leitprinzip: Forecast-gesteuerter Burst**

Die HP läuft nicht kontinuierlich, sondern in kurzen Bursts (15–30 Min),
gesteuert durch die Prognose-Engine. Die Laufzeit richtet sich nach dem
verbleibenden PV-Ertrag — genug Energie muss übrig bleiben, um die
Batterie bis Sonnenuntergang auf SOC_MAX zu füllen.

#### Entscheidungslogik `RegelHeizpatrone.bewerte()`

```
# ── Eingangsdaten ──────────────────────────────────────────
P_Batt        = Batterie-Ladeleistung (W, >0 = Ladung, <0 = Entladung)
P_Wattpilot   = aktuelle Wattpilot-Ladeleistung (W)
P_Netz        = Netzbezug/-einspeisung (W, >0 = Bezug)
SOC           = Batterie-SOC (%)
SOC_MAX       = aktueller SOC_MAX aus battery_control (z.B. 75% oder 100%)
HP_aktiv      = Fritz!DECT-Status (ein/aus, via getswitchstate)
HP_letzte_aus = Zeitpunkt letztes Ausschalten
rest_kwh      = get_remaining_pv_surplus_kwh()  # Prognose Restertrag
rest_h        = Stunden bis Sonnenuntergang (aus solar_geometry)
batt_rest_kwh = (SOC_MAX - SOC) * 10.24 / 100  # kWh bis Batterie voll

# ── Phase 1: Vormittags (gute Prognose → HP darf EV+Batt verzögern) ──
# Bei guter Prognose kann die HP morgens laufen, auch wenn
# Batterie und EV noch nicht voll sind — die werden später gefüllt.
WENN rest_kwh > 20:                              # sehr guter Tag erwartet
    UND P_Batt > 3000:                           # Batterie lädt mit >3 kW
    UND rest_h > 5:                              # noch >5h Sonne
    → HP EIN (Burst: 30 Min)
    → Begründung: genug Ertrag erwartet, EV+Batt werden bis Abend voll

WENN rest_kwh > 12:                              # guter Tag
    UND P_Batt > 5000:                           # Batterie lädt kräftig (>5 kW)
    → HP EIN (Burst: 15–30 Min, je nach rest_kwh)
    → Begründung: hohe Ladeleistung = Anlage hat Kapazität für 2 kW extra

# ── Phase 2: Mittags/Nachmittags (HP wenn Batterie "satt") ──────────
# Batterie lädt stark → Anlage hat offensichtlich Kapazität übrig
WENN P_Batt > 5000:                              # Batt lädt mit >5 kW
    UND rest_kwh > batt_rest_kwh + 2:            # Prognose deckt Batt + HP-Burst
    UND P_Wattpilot < 500:                       # EV lädt nicht (oder fast fertig)
    → HP EIN (Burst: 15–30 Min)
    → Timer starten: nach Ablauf → HP AUS
    → Danach: Batterie holt die 1 kWh wieder auf

# ── Phase 3: Nachmittags spät (nur bei deutlichem Überschuss) ────
# Nach dem Clear-Sky-Peak: Batterie für die Nacht füllen = oberste Prio
WENN rest_h > 2.0:                               # noch >2h PV erwartet
    UND rest_kwh > batt_rest_kwh + 3:            # genug für Batt-voll + HP
    UND P_Batt > 5000:                           # Batt LÄDT stark
    UND HP_aktiv == False:                       # HP ist aus
    → HP EIN (Burst: max 15 Min, konservativ)
    → Begründung: Batterie schafft es trotzdem noch auf SOC_MAX

# ── Phase 4: Abend/Nacht (HARD BLOCK) ────────────────────────────
# Oberste Priorität: volle Batterie für die Nacht
WENN rest_h < 2.0 ODER P_Batt < 1000:
    → HP AUS (kein Burst, keine Ausnahme)
    → Begründung: jedes Watt geht in die Batterie

# ── Sicherheitsregeln (immer aktiv, auch bei aktiv=False) ────────
HYSTERESE:       Mindestpause 5 Min zwischen Ein/Aus
ÜBERTEMPERATUR:  Speicher_oben ≥ 78°C → HP SOFORT AUS
NETZBEZUG:       P_Netz > 200 W (Bezug statt Einspeisung) → HP SOFORT AUS
ENTLADESCHUTZ:   SOC-abhängig (siehe unten)
```

#### SOC-abhängiger Entladeschutz (Notaus)

Der HP-Notaus ist **immer aktiv**, auch wenn der Regelkreis `heizpatrone`
auf `aktiv: false` steht. Dies schützt vor manuell eingeschalteter HP,
die unbemerkt die Batterie entlädt.

**Architektur-Entscheidung:** Der Notaus läuft im **Engine fast-cycle (60 s)**
(Tier-2), nicht im Observer (Tier-1). Begründung: 1–5 Minuten Reaktionszeit
sind für HP akzeptabel, Tier-1 (10 s) wäre übertrieben für einen thermischen
Verbraucher.

```
# ── SOC-abhängige Schwellen ──────────────────────────────────────
notaus_soc_schwelle_pct  = 90   # konfigurierbar (50–100%)
notaus_entladung_hochsoc_w = -1000  # konfigurierbar (-2000–0 W)

WENN HP_aktiv == True UND P_Batt < 0 (Batterie entlädt):
  WENN SOC >= notaus_soc_schwelle_pct:
    # Hochladen-Phase: toleriere bis zu -1000 W Entladung
    WENN P_Batt < notaus_entladung_hochsoc_w:
      → HP SOFORT AUS ("HP-Notaus: Batterie entlädt {P_Batt}W < {Schwelle}W")
  SONST:
    # SOC < 90%: Jede Entladung → sofort AUS
    → HP SOFORT AUS ("HP-Notaus: SOC {soc}% < {Schwelle}%, Entladung {P_Batt}W")
```

**Warum SOC-abhängig?**
Bei SOC ≥ 90% (z.B. nach manueller SOC_MAX-Anhebung auf 100%) kann die
Anlage kurzzeitig in die Entladung rutschen, obwohl genug PV vorhanden ist —
die Regelung des Nulleinspeisers braucht bis zu 30 s zum Nachregeln.
-1000 W Toleranz bei hohem SOC vermeidet unnötige Abschaltungen.

> **Warum P_Batt > 5 kW als Schwelle?**
> Die Batterie (BYD HVS 10.24 kWh) kann mit max. ~5 kW laden.
> Wenn sie bereits mit >5 kW lädt, bedeutet das: Die PV-Anlage produziert
> deutlich mehr als Haus + Batterie brauchen. Die 2 kW HP passen problemlos
> dazu. Die Abregelung des Nulleinspeisers wird sogar reduziert.

#### Rechenbeispiel (28. Feb, wolkenlos, SOC_MAX=75%)

```
09:00 — P_Batt=4kW, rest_kwh=25, rest_h=8, SOC=35%, EV lädt mit 11kW
         Phase 1: rest_kwh>20 ✓, P_Batt>3kW ✓, rest_h>5 ✓
         → HP EIN 30 Min (HP verbraucht 1 kWh, Batt verzögert sich um ~12 Min)
         Begründung: genug Tag, EV bis 12 Uhr voll, Batt bis 15 Uhr voll

09:30 — Timer → HP AUS
         Batt weiter bei ~4 kW, SOC steigt

12:30 — P_Batt=6kW, rest_kwh=12, SOC=68%, EV fertig, kein Wattpilot
         Phase 2: P_Batt>5kW ✓, rest_kwh(12) > batt_rest_kwh(0.7)+2 ✓
         → HP EIN 30 Min

13:00 — Timer → HP AUS
         SOC ca. 70%, Batt lädt weiter mit ~5 kW

14:30 — P_Batt=5,5kW, rest_kwh=6, rest_h=2.5, SOC=74%
         Phase 3: rest_h>2 ✓, rest_kwh(6) > batt_rest_kwh(0.1)+3 ✓, P_Batt>5kW ✓
         → HP EIN 15 Min (konservativ)

14:45 — Timer → HP AUS

16:00 — rest_h=1.5, P_Batt=2kW, SOC=75% (=SOC_MAX)
         Phase 4: rest_h<2 → HARD BLOCK
         Batterie voll, Restproduktion deckt Hausverbrauch
```

#### Implementierungsplan

| Komponente | Datei | Status |
|---|---|---|
| `AktorFritzDECT` | `automation/engine/aktoren/aktor_fritzdect.py` (~365 Z.) | ✅ Produktiv |
| Fritz-Auth (SID-Cache 15 Min) | in `aktor_fritzdect.py` | ✅ Produktiv |
| `RegelHeizpatrone` | `automation/engine/engine.py` (~80 Z.) | ✅ Produktiv |
| SOC-abhängiger Notaus | in `engine.py` (immer aktiv) | ✅ Produktiv |
| Parametermatrix (17 Param.) | `config/soc_param_matrix.json` | ✅ Produktiv |
| Registrierung in `actuator.py` | 3 Aktoren: batterie, wattpilot, fritzdect | ✅ Produktiv |
| pv-config.py Menü 6 | HP-Status, Config, Test, manuell Ein/Aus | ✅ Produktiv |
| Config | `config/fritz_config.json` (IP, AIN), `.secrets` (Creds) | ✅ Produktiv |
| Fritz!Box-Optimierung | Bulk-Query (`getdevicelistinfos`), 60 s Poll | ✅ Produktiv |
| flow_view HP-Zeile | Live-Status (EIN/AUS + Leistung), 120 s Cache | ✅ Produktiv |

**ABC-Schichten-Zuordnung:**
- Schicht A (Collector): nicht betroffen (HP hat kein Modbus)
- Schicht B (Web-API): Status-Anzeige in flow_view (Fritz-Schaltzustand)
- Schicht C (Automation): `RegelHeizpatrone` + `AktorFritzDECT`

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
