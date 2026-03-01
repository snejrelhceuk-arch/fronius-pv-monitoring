# Home Automation — PV-gesteuertes Energiemanagement

> **Stand:** 2026-02-14
> **Hardware:** Sequent Microsystems MEGA-BAS REV-3.3 auf Raspberry Pi 4
> **Ziel:** Eigenverbrauchsmaximierung durch automatische Steuerung von
> Heizpatrone, Klimaanlage, Wärmepumpen-Bypass, Lüftungsanlage und Brandschutzklappen.
>
> **Referenz:** [doc/PV_REFERENZSYSTEM_DOKUMENTATION.md](../doc/PV_REFERENZSYSTEM_DOKUMENTATION.md)
> — 37,59 kWp Nulleinspeiser, Eigenverbrauch 98,6% (2022–2025)

---

## 1. Hardware-Übersicht

### MEGA-BAS HAT (I2C-Adresse 0x48, Stack 0)

| Ressource | Anzahl | Spezifikation |
|-----------|--------|---------------|
| **TRIAC-Ausgänge** | 4 | **1A / max. 120VAC** (lt. HW-Spec v4.2) — ⚠️ brauchen AC! |
| **0-10V Ausgänge** | 4 | Steuerungssignale |
| **Universaleingänge** | 8 | Software-konfigurierbar: 0-10V, 1K/10K Thermistor, Dry Contact |
| **RS485/Modbus** | 1 | Erweiterungskommunikation |
| **1-Wire** | 1 | Digitale Temperatursensoren (DS18B20) |
| **RTC** | 1 | Batterie-gepuffert (CR2032 vorhanden) |
| **Watchdog** | 1 | Hardware — Neustart bei Software-Hänger |

### ⚠️ KRITISCH: TRIAC-Ausgänge brauchen AC-Quelle!

Die TRIACs auf der MEGA-BAS sind Halbleiter-AC-Schalter (lt. HW-Spec v4.2: **1A / max. 120V**).
Sie sind **KEINE potentialfreien Kontakte** wie Relais!

**Problem:** Das Board wird mit **24VDC** betrieben (vorhandener DC-Bus).
TRIACs schalten bei AC-Nulldurchgang ab — bei DC gibt es keinen Nulldurchgang.
→ **TRIAC-Ausgänge sind mit 24VDC unbenutzbar!**

**Lösung: Eight Relays HAT** ($45) — stackbar, potentialfreie Kontakte,
schalten AC und DC, 8 Ausgänge. Alternativ: Separater 24VAC-Trafo für TRIACs.

Die MEGA-BAS bleibt nützlich für: 8 Universal-Eingänge (Thermistoren, 0-10V),
4x 0-10V-Ausgänge, RS485/Modbus, 1-Wire, RTC, Hardware-Watchdog.

### Spitzensperrspannung & Überspannungsschutz (nur relevant falls 24VAC-Trafo verwendet wird)

Die auf der MEGA-BAS verbauten TRIACs sind typisch **Z0109MA** oder vergleichbar:

| Parameter | Wert | Bemerkung |
|-----------|------|----------|
| $V_{DRM}$ (Spitzensperrspannung) | **600V** | Repetitive peak off-state voltage |
| $I_{T(RMS)}$ | 1A | Dauerstrom |
| $I_{TSM}$ | ~10A | Stoßstrom (nicht-repetitiv) |
| **Max. Ausgangsspannung** | **120V AC** | Lt. HW-Spec v4.2 |
| Betriebsspannung | Abh. von AC-Quelle | 24VAC typisch, bis 120VAC möglich |

> **Hinweis:** Falls ein 24VAC-Trafo für die TRIACs beschafft wird, gelten die
> bisherigen Snubber-Empfehlungen (100Ω + 100nF) für induktive Lasten.
> Bei Nutzung des **Eight Relays HAT** statt TRIACs ist dieser Abschnitt irrelevant.

**Induktive Lasten (Schützspulen) — Analyse:**

Beim Abschalten einer induktiven Last (Schützspule) entsteht ein
Spannungspuls durch $V = -L \cdot \frac{di}{dt}$.

- **24VAC Schützspule**, typisch 3–10 VA → $L$ ≈ 1–5 H, $I$ ≈ 0,1–0,4A
- **Rückspannungspuls** bei 24VAC: typisch 80–150V Spitze
- **Sicherheitsabstand:** 600V $V_{DRM}$ vs. ~150V Spitze = **Faktor 4**

**Bewertung:** Bei 24VAC-Betrieb ist die Spitzensperrspannung von 600V
**ausreichend** — ein RC-Snubber ist nicht zwingend nötig, aber empfohlen
für maximale TRIAC-Lebensdauer und EMV:

```
Empfohlener Snubber über Schützspule:
  R = 100Ω (0,5W)  in Reihe mit  C = 100nF (250V AC, X2-Klasse)

  Alternative: Varistor S07K30 (Klemmspannung ~47V) parallel zur Spule
```

> **Wäre die Betriebsspannung 230VAC**: Dann wäre ein Snubber **Pflicht**, da
> Rückspannungspulse bis 600–1000V auftreten können. Aber wir arbeiten mit
> 24VAC — hier ist der Deckel bei ~150V, weit unter 600V $V_{DRM}$.

### 1.2 Stromversorgung & TRIAC-Problem

| Aspekt | Ist-Zustand | Konsequenz |
|--------|-------------|------------|
| **Board-Versorgung** | **24VDC-Bus** (im Haus vorhanden) | Board läuft, I2C, I/O ok |
| **TRIAC-Ausgänge** | Brauchen **AC**, schalten bei Nulldurchgang ab | **Funktionieren NICHT mit 24VDC!** |
| **TRIAC Max-Rating** | 1A / **120V AC** (lt. HW-Spec v4.2) | Könnten bis 120VAC schalten! |

**TRIACs sind KEINE potentialfreien Kontakte!**
Sie sind Halbleiter-Inline-Schalter, die AC durchleiten und beim Nulldurchgang
abschalten. Bei DC-Versorgung fehlt der Nulldurchgang → TRIAC schaltet nicht ab.

**Lösungsoptionen:**

| Option | Kosten | Bewertung |
|--------|--------|-----------|
| **A: Eight Relays HAT** stacken | ~$45 | ✅ **Empfohlen!** Potentialfreie Kontakte, 4A/120V, schalten AC+DC, 24VDC-Bus nutzbar |
| B: 24VAC-Trafo für TRIACs | ~15€ | Funktioniert, aber "Retro" — zusätzlicher Trafo 230V→24VAC |
| C: 24VDC-Relaismodule extern | ~10€ | MEGA-BAS 0-10V-Ausgang treibt Transistor → 24VDC-Relais |
| D: Board mit 24VAC betreiben | 0€ | Nur wenn 24VAC-Trafo eh beschafft wird; 24VDC-Bus dann nicht nutzbar |

> **Empfehlung Option A:** Sequent Microsystems [Eight Relays HAT](https://sequentmicrosystems.com/products/eight-relays-stackable-card-for-raspberry-pi)
> — stackbar auf gleichen Pi, gleiche I2C-Architektur, 8 potentialfreie
> Relaiskontakte (N.O./N.C., 4A/120VAC). Schalten problemlos 24VDC-Relais/Schütze.
> Plus: 4 Relais übrig für Bypass-Ventil und Reserven.

---

### 2.1 Heizpatrone (1000L-Warmwasserspeicher)

| Parameter | Aktuell (bestätigt) | Ziel (später) |
|-----------|----------------------|---------------|
| Leistung | **2 kW** | 3-Phasen, 3×2 kW = 6 kW? |
| Phasen | 1-phasig 230V | **3-phasig 400V** |
| **230V-Versorgung** | **Fritz!DECT Steckdose (Primärschaltung)** | MEGA-BAS → Schütz (später) |
| **Steuerung** | **✅ AktorFritzDECT (produktiv seit 2026-02-28)** | MEGA-BAS Integration |
| Schutz | 2 unabhängige Temp.-Sensoren | + MEGA-BAS Thermistor |
| PV-Abhängigkeit | Manuell / Fritz!DECT | Automatisch bei PV-Überschuss |
| Verbrauch 2025 | **2.614 kWh** (13% vom Gesamtverbrauch) | Steigend bei Vollautomatik |

**✅ Geklärt:** Heizpatrone ist **NICHT** am WPM-Ausgang E9 (Flanschheizung)!
Sie ist separat verdrahtet mit eigenem 24V-Relais und Fritz!DECT-Steckdose.

**Aktuelle Schaltung:**
```
230V Netz ──► Fritz!DECT SD (Primärschaltung) ──► 24V-Relais ──► Heizpatrone 2kW
                                                    │
                                         2 Temp.-Sensoren → Relais-Freigabe
```

**Automations-Optionen:**
1. **Fritz!DECT API nutzen** (HTTP/XML, sofort möglich, bereits vorhandene Infrastruktur)
2. **MEGA-BAS TRIAC → 24V-Relais ansteuern** (wenn Relais-Spule 24VAC)
3. **MEGA-BAS TRIAC → Schütz → Fritz!DECT ersetzen** (mittel/langfristig)

> **Frage:** Ist das 24V-Relais mit 24V**AC** oder 24V**DC** angesteuert?
> Bei 24VAC: MEGA-BAS TRIAC kann direkt die Relais-Spule schalten.
> Bei 24VDC: MEGA-BAS 0-10V-Ausgang oder separates Relais nötig.

**Sicherheit:** 3 unabhängige Abschaltpfade (bereits vorhanden!):
1. Temperatursensor 1 → 24V-Relais sperrt
2. Temperatursensor 2 → 24V-Relais sperrt
3. Fritz!DECT SD → 230V trennen

### 2.2 Lüftungsanlage

| Komponente | Steuerung | MEGA-BAS Nutzung |
|------------|-----------|------------------|
| **Brandschutzklappe 1** | 24VAC Stellantrieb | TRIAC-Ausgang |
| **Brandschutzklappe 2** | 24VAC Stellantrieb | TRIAC-Ausgang |
| **Lüftungsgerät** | Ein/Aus oder Stufen | TRIAC oder 0-10V |

**Abschaltbedingungen:**
- Außenluftqualität schlecht → Zuluft stoppen/reduzieren
- Nachts strenger Frost → Frostschutz / Absenkung
- Kein PV-Überschuss → Energiesparmodus (Grundlüftung)

### 2.3 Wärmepumpe — Dimplex SIK 11 TES

| Aspekt | Details |
|--------|---------|  
| **Modell** | **Dimplex SIK 11 TES** (Sole/Wasser-Wärmepumpe) |
| Thermische Leistung | 11 kW |
| Elektrische Leistung | **2,1 kW** (Normbetrieb), max. **4,3 kW** |
| Anschluss | Einphasig (bestätigt: SM WP nur Phase 2 aktiv) |
| Kompressor | Scroll (benötigt regelmäßige Schmierung!) |
| SmartMeter | Fronius SM Unit 4 (Verbrauch: ~3.000 kWh/a geschätzt) |
| Verbrauch 2025 | geschätzt **~6.000 kWh** (31% vom Gesamtverbrauch) |
| Steuerbare Eingänge | **Modbus RTU via LWPM 410!** SG-Ready + alle Register R/W |
| **Flanschheizung E9** | WPM-Ausgang vorhanden, aber **Heizpatrone NICHT dort angeschlossen!** |
| **Bivalenz** | **Keine!** Sole/Wasser → Sole-Temp. stabil, kein 2. Wärmeerzeuger nötig |
| **Sole-Temperatur** | Austritt (R6, Reg. 7) — wird nie -9°C erreichen (Erdwärme stabil) |
| **Betriebsmodus (Reg. 5015)** | 0=Sommer (Heizung AUS, WW bleibt!), 1=Auto, 5=Kühlen |
| Investition | 12.000 EUR (2022) + 155 EUR LWPM 410 |

**Dimplex LWPM 410 — Modbus RTU über RS485 (Integrationsoption)**

| Modul | Dimplex LWPM 410 |
|-------|------------------|
| Artikelnummer | **339410** |
| Preis | ~155 EUR |
| Protokoll | **Modbus RTU** über RS485 |
| Steckplatz | "Serial Card / BMS Card" im WPM |
| Offizielle Doku | [dimplex.atlassian.net/wiki — NWPM Modbus TCP](https://dimplex.atlassian.net/wiki/wiki/spaces/DW/pages/2873393288/NWPM+Modbus+TCP) |
| Alternative | NWPM (Art.Nr. 356960) = Modbus **TCP** über Ethernet |

**Kompatibilität (lt. offizieller Dokumentation):**
> Mindestsystemvoraussetzung: Dimplex WP mit **WPM 2004, WPM 2006, WPM 2007
> oder WPM EconPlus** Baureihe, Softwarestand **H_H50** und höher.

**⚠️ Noch zu klären:** Welche WPM-Version hat die SIK 11 TES?
- Am Gerät: Display-Typ prüfen (LCD = WPM_L/H, Touch = WPM_M)
- Softwarestand in Menü ablesen (z.B. `WPM_L23.7` oder `WPM_H60`)
- Steckplatz "Serial Card / BMS Card" vorhanden?

**Was Modbus RTU im legitimen Betrieb ermöglicht:**

Hinweis: Schreibzugriffe nur mit eigener Berechtigung, im Rahmen offizieller
Herstellerdokumentation und ohne Umgehung von Schutzmechanismen.

| Funktionsbereich | Typischer Nutzen |
|------------------|------------------|
| Warmwasser-Soll/Isttemperatur | PV-Überschussgeführt anheben, Monitoring |
| Betriebsmodus | Sommer/Auto/Absenkung im Regelbetrieb |
| Vorlauf-/Rücklauf-/Quelltemperaturen | Effizienz- und Zustandsüberwachung |
| Status- und Störmeldungen | Betriebssicherheit, Alarmierung |
| Laufzeiten und Wärmemengen | COP-/Performance-Auswertung |
| Smart-Grid-Signale | Lastverschiebung innerhalb freigegebener Betriebsarten |

**SG-Ready via Modbus RTU (ab WPM_L20.2):**

| SG1 | SG2 | Farbe | Modus | Anwendung |
|-----|-----|-------|-------|-----------|
| 0 | 1 | 🔴 rot | Abgesenkt | EVU-Sperre, teurer Netzstrom |
| 0 | 0 | 🟡 gelb | Normal | Standardbetrieb |
| 1 | 0 | 🟢 grün | Verstärkt | **PV-Überschuss → WP heizen!** |
| 1 | 1 | 🟢🟢 dunkelgrün | Maximum | **WP + Heizpatrone maximal!** |

Details zu Registern und Firmware-Abhängigkeiten sind ausschließlich der
offiziellen Herstellerdokumentation zu entnehmen.

**Physische Anbindung über MEGA-BAS RS485:**
```
MEGA-BAS RS485 [A] ──► LWPM 410 RS485 [A]
MEGA-BAS RS485 [B] ──► LWPM 410 RS485 [B]
          └──► 120Ω Terminierung an beiden Enden
```

→ **Kein TRIAC nötig für WP-Steuerung!** Alles via Modbus RTU.
→ Heizpatrone läuft separat (Fritz!DECT + 24V-Relais), NICHT über WPM E9.
→ Smart Grid "dunkelgrün" aktiviert E9-Ausgang, aber dort ist nichts angeschlossen.
→ Python-Bibliothek: `pymodbus` (bereits Modbus-Erfahrung im Workspace via `modbus_v3.py`)

**Compliance-Hinweis:**
- Diese Doku dient der Interoperabilität im Eigenbetrieb.
- Keine Gewähr für Vollständigkeit oder Freigabe einzelner Herstellerfunktionen.
- Für Implementierung, Rechte und Grenzwerte gilt immer die offizielle Dokumentation.
- Veröffentlichungs- und Compliance-Regeln stehen zentral in
   `doc/VEROEFFENTLICHUNGSRICHTLINIE.md`.

**Noch relevante Fallback-Optionen:**
1. **Bypass-Ventil am Speicher** — Umschaltung über Stellantrieb (24VAC):
   - **Bypass EIN** → Warmwasser nur im oberen Speicherbereich
   - **Bypass AUS** → Warmwasser im gesamten Speicher
2. **Täglicher Pflichtlauf** — Scroll-Kompressor braucht Schmierung →
   Auch über Modbus-Modus steuerbar (Betriebsmodus schreiben).

### 2.4 Klimaanlage (Split-Klima)

| Parameter | Details (lt. PV-Referenz) |
|-----------|---------------------------|
| Typ | Split-Klimagerät |
| Leistung | **1,3 kW** |
| Zweck | "Überschussvernichtung" — PV-Eigenverbrauch maximieren |
| Schaltung | Installationsschütz mit 24VAC-Spule |
| Steuerung | MEGA-BAS TRIAC → Schützspule (Ein/Aus) |

> **Hinweis:** Wenn das Klimagerät einen Standby-Modus hat, der die interne
> Steuerung beibehält, muss das Schütz den Leistungsteil schalten und nicht
> die komplette Stromversorgung (sonst Verlust der Einstellungen bei jedem
> Schaltvorgang).

### 2.5 Fritz!DECT-Steckdosen (optional, Übergangslösung)

| Vorteil | Nachteil |
|---------|----------|
| Sofort einsetzbar, kein Verkabelungsaufwand | Nur 1-phasig, max. ~2.3kW |
| Energiemessung integriert | Latenz (DECT-Funk) |
| API verfügbar (HTTP/XML) | Nicht geeignet für 3-Phasen-Heizpatrone |

---

## 3. Betriebsstrategien (Jahreszeitabhängig)

### 3.1 Winter (Heizperiode: Okt–Mär)

```
PV-Überschuss GERING → WP macht Heizung + Warmwasser
                        E-Auto mit Restüberschuss laden
                        Heizpatrone AUS (zu ineffizient bei wenig PV)

PV-Überschuss MITTEL → WP Warmwasser, Bypass EIN (nur oben)
(Übergangszeit nah)     E-Auto laden wenn Batterie nicht leer
                        Heizpatrone prüfen (lohnt sich ab ~2kW Überschuss?)
```

### 3.2 Übergangszeit (Frühling/Herbst)

```
PV-Überschuss MITTEL → Heizpatrone übernimmt Warmwasser teilweise
                        Bypass AUS (ganzer Speicher)
                        WP 1× täglich Pflichtlauf (Schmierung)

PV-Überschuss HOCH  → Heizpatrone übernimmt Warmwasser vollständig
                        E-Auto laden
                        WP nur für Pflichtlauf
```

### 3.3 Sommer (Apr–Sep)

```
PV-Überschuss HOCH  → Heizpatrone = alleinige Warmwasserbereitung
                        E-Auto = primärer Überschuss-Puffer
                        WP 1× täglich Pflichtlauf (Schmierung)
                        Batterie → Nacht-Eigenverbrauch

PV-Überschuss SEHR  → Nulleinspeisung: Alles nutzen!
HOCH                    Heizpatrone → E-Auto → Batterie → (Einspeisung=0)
```

---

## 4. I/O-Planung (Vorläufig)

### ⚠️ TRIAC-Ausgänge — NICHT NUTZBAR mit 24VDC!

Die 4 TRIAC-Ausgänge der MEGA-BAS (max 120V, 1A) sind **AC-Halbleiterschalter**.
Sie sind **KEINE potentialfreien Kontakte** — sie benötigen eine AC-Quelle im Lastkreis.
Da das Board über den 24VDC-Bus versorgt wird, fehlt die AC-Quelle → **TRIACs sind tot.**

### ✅ Lösung: Sequent Microsystems Eight Relays HAT (~$45)

- 8 **potentialfreie** Relais-Kontakte (N.O. + N.C.)
- **4A / 120VAC** pro Kontakt — schaltbar AC und DC
- Stackbar auf demselben Pi (gleiche I2C-Architektur)
- Python-Library: `lib8relay`
- Shop: https://sequentmicrosystems.com/products/eight-relays-8-layer-stackable-hat-for-raspberry-pi

| Relais | Funktion | Last | Bemerkung |
|--------|----------|------|-----------|
| R1 | **Heizpatronen-Schütz** (Spule 24VDC) | ~0.1A | Schütz schaltet 230V/2kW |
| R2 | **Klimaanlagen-Schütz** (Spule 24VDC) | ~0.1A | Schütz schaltet 230V/1.3kW |
| R3 | **Brandschutzklappe 1** Stellantrieb | ~0.3A | 24VDC-Antrieb direkt |
| R4 | **Brandschutzklappe 2** Stellantrieb | ~0.3A | 24VDC-Antrieb direkt |
| R5 | **Bypass-Ventil** (Speicher) | ~0.3A | Motorventil 24VDC |
| R6 | Reserve | — | — |
| R7 | Reserve | — | — |
| R8 | Reserve | — | — |

> **Vorteil:** 8 Relais genügen für alle Aktoren inkl. Bypass-Ventil.
> Keine separate 24VAC-Versorgung nötig — alles läuft über den 24VDC-Bus.

### Universaleingänge

| Input | Typ | Funktion |
|-------|-----|----------|
| IN1 | 10K Thermistor | Speichertemperatur oben (≤80°C!) |
| IN2 | 10K Thermistor | Speichertemperatur mitte |
| IN3 | 10K Thermistor | Speichertemperatur unten |
| IN4 | 10K Thermistor | Außentemperatur (Frost-Erkennung) |
| IN5 | 0-10V | Reserviert (ggf. Luftqualitätssensor) |
| IN6 | Dry Contact | Brandschutzklappe 1 Rückmeldung |
| IN7 | Dry Contact | Brandschutzklappe 2 Rückmeldung |
| IN8 | Dry Contact | Reserve |

### 0-10V Ausgänge

| Ausgang | Funktion |
|---------|----------|
| OUT1 | Lüftungsstufe (0-10V → Drehzahl) |
| OUT2 | WP-Temperatursensor-Manipulation? |
| OUT3 | Reserve |
| OUT4 | Reserve |

---

## 5. PV-Anbindung (Datenquellen)

Die Automation nutzt die bereits vorhandene Monitoring-Infrastruktur:

| Datenquelle | Abruf | Relevante Werte |
|-------------|-------|-----------------|
| Fronius Modbus (Pi4) | Echtzeit, 3s Polling | PV-Erzeugung, Netz-Import/Export, Batterie-SOC |
| Wattpilot WebSocket | Echtzeit | E-Auto Ladeleistung, Status |
| Solar Forecast | Prognose | Erwarteter PV-Ertrag |
| MEGA-BAS I2C | Echtzeit | Temperaturen, Inputs, 0-10V-Status |
| Eight Relays HAT I2C | Echtzeit | Relais-Status (R1-R8) |
| battery_control.py | Bestehendes System | Batterie-Steuerungsentscheidungen |

**Entscheidungslogik:**
```
PV_Überschuss = PV_Erzeugung - Hausverbrauch - Batterie_Ladung - Wallbox
Wenn PV_Überschuss > Schwellwert UND Speicher_Temp < 80°C:
    → Heizpatrone EIN
```

---

## 6. Abhängigkeiten & Integration

> **Hinweis (2026-03-01):** Die Automation-Engine ist produktiv als `pv-automation.service`.
> Architektur-Details: [doc/AUTOMATION_ARCHITEKTUR.md](../doc/AUTOMATION_ARCHITEKTUR.md)

```
 solar_forecast.py ──┐
                     │
 collector.py ───────┤     ┌───────────────────────┐
   (Modbus-Daten)    ├────►│  automation/engine/   │
                     │     │  (4-Schichten-Engine) │
 battery_control.py ─┤     └───────┬───────────────┘
                     │             │
 wattpilot_api.py ───┘             ▼
                       ┌──────────────────────────────┐
                       │ Aktoren:                      │
                       │  AktorBatterie (Modbus TCP)    │
                       │  AktorFritzDECT (HTTP API)     │
                       │  AktorWattpilot (Stub)         │
                       └──────────────────────────────┘

 Geplant (MEGA-BAS):
                            ┌──────────────┐
                            │  MEGA-BAS    │  Eight Relays HAT
                            │  (I2C 0x48)  │  (I2C, stackable)
                            └──────────────┘  └──────────────┘
                              │    │    │        │
                           0-10V  Inputs RS485  Relais (R1-R8)
                                                 │
                                            Schütze / Ventile
```

---

## Weitere Dokumente

- [TODO.md](TODO.md) — Aufgabenliste & Meilensteine
- [HARDWARE_SETUP.md](HARDWARE_SETUP.md) — Verkabelung, I2C-Setup, Inbetriebnahme
- [STRATEGIEN.md](STRATEGIEN.md) — Detaillierte Betriebsstrategien & Algorithmen
- [OFFENE_FRAGEN.md](OFFENE_FRAGEN.md) — Klärungsbedarf & Recherche
