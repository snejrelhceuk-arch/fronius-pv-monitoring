# Betriebsstrategien — PV-Eigenverbrauchsmaximierung

> Stand: 2026-03-08

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
              │  Batterie (20,48 kWh) │  ← Priorität 2 (Winter: hoch)
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

### 2.6 Heizpatrone (HP) — Prognosegesteuerte Burst-Strategie (via Fritz!DECT)

> Stand: 2026-03-08 — **Produktiv** seit 2026-02-28 (`RegelHeizpatrone` + `AktorFritzDECT`)
> Siehe: [STEUERUNGSPHILOSOPHIE.md](../doc/STEUERUNGSPHILOSOPHIE.md) für Designprinzipien

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
batt_rest_kwh = (SOC_MAX - SOC) * 20.48 / 100  # kWh bis Batterie voll
sunrise       = Sonnenaufgang (Dezimalstunde, aus solar_geometry)

# ── Phase 0: Morgen-Drain (ab sunrise−1h, prognosegetrieben) ───────
#   Batterie gezielt leeren BEVOR PV produziert. Sunrise-basiert,
#   NICHT P_Batt-abhängig (P_Batt > 0 bei erzwungener Netzladung!).
#   Drain-Notaus prüft PV < 500W und Netzbezug Ø > 200W.
WENN now_h >= (sunrise - 1h) UND now_h < 10:00:
    UND SOC > 20%:
    UND Verbraucher niedrig (Haus < 700W, WP < 500W, EV < 1000W):
    UND forecast_quality = gut|mittel:
    UND Forecast >= 4 kW in den kommenden Stunden:
    → HP EIN (Drain 45 Min) — Batterie gezielt leeren
    → Stop bei SOC ≤ 15% (drain_stop_soc)

# ── Phase 1: Vormittags (gute Prognose, Wiedereintritt-fähig) ──────
#   Bei Wiedereintritt nach Burst-Pause: Schwelle um HP_NENN_W reduziert,
#   da P_Batt nach HP-AUS erst wieder hochfahren muss.
WENN rest_h > 5 UND rest_kwh > 20:
    UND P_Batt > Schwelle (3000W initial, 1000W bei Wiedereintritt):
    → HP EIN (Burst: 30 Min)

# ── Phase 1b: Nulleinspeiser-Probe (SOC ≈ MAX, Batt idle) ─────────
#   Testpuls: HP 120s einschalten, dann auswerten.
#   Erfolgreich (ΔPV ≥ 500W, Grid ≤ 300W) → Burst verlängern 30 Min.
#   Gescheitert → HP AUS, Cooldown 600s.
WENN SOC ≥ SOC_MAX - 2% UND |P_Batt| < 500W UND |Grid| < 300W:
    UND Forecast_jetzt_w ≥ 2000W:
    UND rest_kwh > Reserve:
    UND Probe-Cooldown abgelaufen:
    → HP EIN (Probe 120s → Auswertung → Verlängern oder AUS)

# ── Phase 2: Mittags (Batterie lädt kräftig) ──────────────────────
WENN rest_h ≥ 2.0:
    UND P_Batt > min_lade (potenzialabhängig):
    UND rest_kwh > batt_rest_kwh + Reserve:
    → HP EIN (Burst: 30 Min)

# ── Phase 3: Nachmittags spät (konservativ) ──────────────────────
WENN rest_h ≥ 2.0 UND rest_h < 3.0:
    UND P_Batt > min_lade:
    UND rest_kwh > batt_rest_kwh + reserve_nachmittag:
    → HP EIN (Burst: 15 Min, konservativ)

# ── Phase 4: Abend-Nachladezyklus (rest_h < 2.0) ────────────────
#   KEIN Hard Block mehr! HP darf kurze Bursts fahren,
#   Zyklus: EIN → SOC sinkt → AUS (SOC < MAX-10%) →
#   Batt lädt → SOC ≈ MAX → EIN. Adaptiv zu SOC_MAX.
WENN rest_h < 2.0 UND rest_h > 0:
    UND SOC ≥ SOC_MAX - 2%:  (EIN-Schwelle)
    UND PV ≥ 1500W:
    UND P_Batt ≥ 0:          (Batterie lädt oder idle)
    → HP EIN (Burst kurz: 15 Min)
    → AUS wenn SOC < SOC_MAX - 10%:  (AUS-Schwelle)
    → AUS wenn PV < 1500W:
    → AUS wenn Entladung > 1000W:

# ── Sicherheitsregeln (immer aktiv, auch bei aktiv=False) ────────
ÜBERTEMPERATUR:  Speicher_oben ≥ 78°C → HP SOFORT AUS
SOC-SCHUTZ:      SOC ≤ 5% → HP SOFORT AUS (nicht 7%!)
NETZBEZUG:       P_Netz > 200 W (Ø5 Min) → HP SOFORT AUS
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
> Die Batterie (BYD HVS 2×10.24 kWh parallel, 20.48 kWh netto) kann mit max. ~5 kW laden.
> Wenn sie bereits mit >5 kW lädt, bedeutet das: Die PV-Anlage produziert
> deutlich mehr als Haus + Batterie brauchen. Die 2 kW HP passen problemlos
> dazu. Die Abregelung des Nulleinspeisers wird sogar reduziert.

#### Rechenbeispiel (8. März, wolkenlos, SOC_MAX=75%)

```
05:30 — Sunrise 06:30, drain_fruehstart = 1h → Fenster offen ab 05:30
  SOC=40%, Prognose 45 kWh ("gut"), Haus=350W, WP=0
  Phase 0: sunrise-1h ✓, SOC>20% ✓, Verbraucher niedrig ✓
  → HP EIN (Drain 45 Min) — Batterie gezielt leeren

09:30 — SOC=18%, P_Batt=+3.5kW, rest_kwh=38
  Phase 1: rest_h=8 > 5 ✓, rest_kwh=38 > 20 ✓, P_Batt>3kW ✓
  → HP EIN (Burst 30 Min)

10:00 — Burst-Timer → HP AUS
  _letzte_phase = 'phase1', _letzte_aus = jetzt

10:08 — P_Batt=2.5kW (erholt sich nach HP-AUS)
  Phase 1 Wiedereintritt: Schwelle = max(1000, 3000-2000) = 1000W
  P_Batt 2500 > 1000 ✓ → HP EIN (Burst 30 Min)

12:00 — SOC=73% (≈SOC_MAX 75%), P_Batt=+200W, Grid≈0
  Phase 1b: SOC nahe MAX ✓, Batt idle ✓, Forecast 8kW ✓
  → HP EIN (Probe 120s) — PV-Start=4500W, Grid-Start=50W

12:02 — Probe-Auswertung: PV jetzt=5200W (ΔPV=700W ≥ 500W), Grid=80W ≤ 300W
  Probe ERFOLGREICH → Burst verlängern um 30 Min
  (WR hatte gedrosselt, jetzt voll aufgeregelt)

14:00 — SOC=85%, SOC_MAX=100% (Nachmittag angehoben), P_Batt=−1.5kW
  Potenzial: "gut" → Entladung toleriert ✓
  HP bleibt an (laufender Burst)

15:30 — rest_h=1.8 < 2.0 → Phase 4 (Abend)
  SOC=96% ≈ SOC_MAX(100%)−2% → EIN-Schwelle erfüllt
  PV=2100W ≥ 1500W ✓, P_Batt=+300W ≥ 0 ✓
  → HP EIN (Burst kurz 15 Min)

15:45 — SOC sinkt auf 89% < SOC_MAX(100%)−10%
  Phase 4 AUS-Kriterium: SOC 89% < 90% → HP AUS
  Batterie lädt nach...

16:10 — SOC wieder auf 98% ≈ SOC_MAX(100%)−2%
  PV=1800W ≥ 1500W ✓ → HP EIN (neuer Zyklus)

16:30 — PV sinkt unter 1500W → HP AUS (endgültig, Sonnenuntergang naht)
```

#### Implementierungsplan

| Komponente | Datei | Status |
|---|---|---|
| `AktorFritzDECT` | `automation/engine/aktoren/aktor_fritzdect.py` (~365 Z.) | ✅ Produktiv |
| Fritz-Auth (SID-Cache 15 Min) | in `aktor_fritzdect.py` | ✅ Produktiv |
| `RegelHeizpatrone` | `automation/engine/regeln/geraete.py` (~840 Z.) | ✅ Produktiv |
| `RegelSlsSchutz` | `automation/engine/regeln/schutz.py` (~160 Z.) | ✅ Produktiv (2026-03-08) |
| SOC-abhängiger Notaus | in `geraete.py` (immer aktiv) | ✅ Produktiv |
| Probe-Logik (Nulleinspeiser) | in `geraete.py` Phase 1b | ✅ Produktiv (2026-03-08) |
| Abend-Nachladezyklus | in `geraete.py` Phase 4 | ✅ Produktiv (2026-03-08) |
| Phasenströme Pipeline | `data_collector.py → obs_state.py` | ✅ Produktiv (2026-03-08) |
| Parametermatrix (28+ Param.) | `config/soc_param_matrix.json` | ✅ Produktiv |
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

## 3. Sicherheitsregeln

> **Kanonische Quelle:** [SCHUTZREGELN.md](SCHUTZREGELN.md)
>
> Alle Schutzregeln (Batterie, SLS, Heizpatrone, WP) sind dort
> vollständig spezifiziert — inklusive Schwellwerte, Hysteresen,
> Implementierungsstatus und Datenflüsse. Hier nicht wiederholt,
> um Divergenz zu vermeiden.
