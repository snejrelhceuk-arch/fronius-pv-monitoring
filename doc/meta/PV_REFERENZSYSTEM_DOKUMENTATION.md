# PV-Anlage Referenzsystem - Daten & Erfahrungen

## Lizenz & Nutzung

Diese Daten werden **gemeinfrei** zur Verfügung gestellt.

**Erlaubte Nutzung:**
- Wissenschaftliche Arbeiten
- Blog-Posts / Artikel
- Präsentationen
- Vergleichsstudien
- Kommerzielle Nutzung (Beratung, Planung)

**Keine Einschränkungen**, aber **Hinweis erwünscht**:
"Daten basierend auf Fronius-Referenzsystem (37,6 kWp, 2022-2025)"

## Kontakt & Weiteres

**Datenquelle**: Fronius Modbus-Logging (3s-Auflösung)  
**Zeitraum**: 06.02.2026 - laufend (15min-Aggregation, Zählerstand-Delta)  
**Historisch**:  
  - 2022-2025 (CSV-Import aus Fronius Solar.web)  
  - Jan-Feb 2026 (Solarweb-korrigiert, P×t-Drift-Problem behoben)  
  - 2021 (Teilbetrieb ab 5.11.2021)

**Technische Details**:
- Raspberry Pi 5 + NVMe SSD
- Python-basiertes Monitoring
- SQLite Datenbank (11 MB, 13 Tabellen)
- ECharts 5.4.3 Visualisierung

---

## System-Übersicht

### Hardware-Entwicklung

| Phase | Zeitraum | Generator | Wechselrichter |
|-------|----------|-----------|----------------|
| **1** | Nov 2021 – Apr 2025 | 21,40 kWp | Gen24 10kW |
| **2** | Mai 2025 – Sep 2025 | 26,07 kWp | Gen24 12kW + Gen24 10kW |
| **3** | Ab Okt 2025 | **37,59 kWp** | Gen24 12kW + Gen24 10kW + Symo 4,5kW |

**Standort:** Mittelsachsen (Erlau, 51,01°N 12,95°E, 315m NN)  
**Batterie:** 2× BYD HVS 20,48 kWh / 12 kW (Tower 1 seit Nov 2021, Tower 2 seit März 2026)  
**Strategie:** Nulleinspeiser (seit Beginn)

---

### String-Konfiguration (Phase 3 — aktuell ab Okt 2025)

#### Wechselrichter F1: Fronius Gen24 12 kW — 19,32 kWp (Overpaneling 161%)

| String | MPPT | Module | Ausrichtung | Neigung | Leistung | Bemerkung |
|--------|------|--------|-------------|---------|----------|-----------|
| **1** | MPPT1 | 20× 345 Wp | **SSO** (150°) | 52° | 6,90 kWp | Satteldach Süd |
| **2** | MPPT1 ∥ | 20× 345 Wp | **NNW** (330°) | 52° | 6,90 kWp | Satteldach Nord |
| **3** | MPPT2 | 8× 345 Wp | **SSO** (150°) | 45° | 2,76 kWp | Gaube/Anbau Süd |
| **4** | MPPT2 ∥ | 8× 345 Wp | **NNW** (330°) | 45° | 2,76 kWp | Gaube/Anbau Nord |

> String 1+2 parallel an MPPT1, String 3+4 parallel an MPPT2.  
> **Overpaneling 161%**: Gegenüberliegende Dachflächen (SSO+NNW) erzeugen Azimut-180°-Versatz → tägliche Produktionszeitverschiebung statt gleichzeitigem Peak.

#### Wechselrichter F2: Fronius Gen24 10 kW — 12,42 kWp (Overpaneling 124%)

| String | MPPT | Module | Ausrichtung | Neigung | Leistung | Bemerkung |
|--------|------|--------|-------------|---------|----------|-----------|
| **5** | MPPT1 | 15× 450 Wp | **WSW** (240°) | 18° | 6,75 kWp | Flachdach West |
| **6** | MPPT2 | 8× 450 Wp | **WSW** (240°) | 90° | 3,60 kWp | Fassade West |
| **7** | MPPT2 → | 6× 345 Wp | **WSW** (240°) | 90° | 2,07 kWp | Fassade West, **mit Optimierern** |

> String 6+7 in Reihe an MPPT2 (Optimierer gleichen unterschiedliche Module aus).  
> **Overpaneling 124%**: Gleicher Azimut, aber gegensätzliche Einfallswinkel-Schwankungen (18° vs. 90°).

#### Wechselrichter F3: Fronius Symo 4,5 kW — 5,85 kWp (Overpaneling 130%)

| String | MPPT | Module | Ausrichtung | Neigung | Leistung | Bemerkung |
|--------|------|--------|-------------|---------|----------|-----------|
| **8** | MPPT1 | 13× 450 Wp | **SSO** (150°) | 90° | 5,85 kWp | Fassade Süd |

> MPPT2 deaktiviert (kein zweiter String).

#### Zusammenfassung

| | F1 (Gen24 12kW) | F2 (Gen24 10kW) | F3 (Symo 4,5kW) | **Gesamt** |
|--|-----------------|-----------------|------------------|------------|
| **Module** | 56× 345 Wp | 15× 450 Wp + 8× 450 Wp + 6× 345 Wp | 13× 450 Wp | **98 Module** |
| **Generator** | 19,32 kWp | 12,42 kWp | 5,85 kWp | **37,59 kWp** |
| **Inverter** | 12,0 kW | 10,0 kW | 4,5 kW | **26,5 kW** |
| **Overpaneling** | 161% | 124% | 130% | **142%** |
| **Batterie** | BYD HVS 10 kWh | — | — | **20,48 kWh** (2× HVS parallel, ab März 2026) |

> Summe Module: 62× 345 Wp + 36× 450 Wp = 21,39 + 16,20 = **37,59 kWp**  
> Summe Wechselrichter: 12 + 10 + 4,5 = **26,5 kW** (+ 1 kW Smart Meter = 27,5 kW Systemleistung)  
> Inverter-Clipping: Maximale Eingangsleistung 37,59 kWp wird auf 26,5 kW AC begrenzt

---

### Verbraucher

| Verbraucher | Leistung | Typ | Bemerkung |
|-------------|----------|-----|-----------|
| **5-Personen-Haushalt** | variabel | Grundlast | ~5.400 kWh/a |
| **Sole-Wasser-Wärmepumpe** | 2,5–4 kW el. (11 kW th.) | Dimplex SIK 11 TES | Heizung + Warmwasser |
| **3× E-Auto** | je ~30–50 kWh/Tag | 2× Renault Zoe + 1× Citroën | via Wattpilot |
| **Wattpilot "go"** | max. 22 kW | Fronius go-eCharger | PV-Überschussladen |
| **Heizpatrone** | 2 kW | Warmwasserspeicher | Überschussvernichtung |
| **Klimagerät** | 1,3 kW | Split-Klima | Überschussvernichtung |

> Heizpatrone + Klimagerät "verbessern" die Nulleinspeisung-Statistik.  
> Jahresverbrauch 2025: **19.407 kWh** (davon Wattpilot: 5.423 kWh = 28%)

**Einspeisung:** Nulleinspeiser (Eigenverbrauch 2022–2025 durchschnittlich **98,6%**)

---

### Besonderheiten

1. **Null-Einspeisung-Strategie**
   - Von Anfang an auf maximalen Eigenverbrauch optimiert
   - Intelligente Steuerung über Fronius-System
   - Batteriespeicher für Tag/Nacht-Verlagerung

2. **E-Mobilität Integration (ab April 2024)**
   - 3 Elektrofahrzeuge als zusätzlicher Energiespeicher
   - PV-Überschussladen mit Wattpilot
   - Durchschnittlicher Verbrauch: ~15kWh/100km pro Fahrzeug

3. **Multi-Wechselrichter-Setup**
   - Verteilung auf 3 separate Wechselrichter (F1, F2, F3)
   - Ermöglicht optimale MPP-Tracking-Effizienz
   - Redundanz bei Wartung/Ausfall

## Messergebnisse 2022-2025

### Eigenverbrauchsquote (Jahreswerte)

| Jahr | PV-Ertrag | Einspeisung | Eigenverbrauch | System |
|------|-----------|-------------|----------------|--------|
| **2021** | 501 kWh | 1,8 kWh | **99,63%** | Teilbetrieb Nov-Dez (21,4 kWp) |
| **2022** | 9.267 kWh | 37 kWh | **99,60%** | Basis (21,4 kWp) |
| **2023** | 9.798 kWh | 167 kWh | **98,30%** | Basis (21,4 kWp) |
| **2024** | 11.986 kWh | 280 kWh | **97,67%** | Basis + E-Autos (ab Apr) |
| **2025** | 15.496 kWh | 199 kWh | **98,71%** | Erweitert (37,6 kWp + 3 E-Autos) |
| **2026*** | 1.117 kWh | 10 kWh | **99,13%** | *Nur Jan-Feb, Solarweb-korrigiert |

### Entwicklung Solar-Ertrag

- **2021**: 501 kWh (Teilbetrieb Nov-Dez, 2 Monate)
- **2022 → 2025**: +67% Steigerung (9.267 → 15.496 kWh)
- **Durchschnitt 2022-2025**: 11.637 kWh/Jahr (21,4-37,6 kWp gemischt)
- **2025 mit Vollausbau**: 15.496 kWh (+29% vs. 2024)
- **2026** (Jan-Feb, hochgerechnet): ~6.700 kWh/Jahr (geschätzt)

### Autarkiegrad (Durchschnitt)

| Jahr | Autarkie | Verbrauch gesamt |
|------|----------|------------------|
| 2021 | 29,3% | 1.651 kWh (Teilbetrieb Nov-Dez) |
| 2022 | 81,6% | 11.717 kWh |
| 2023 | 77,7% | 12.170 kWh |
| 2024 | 74,6% | 14.183 kWh |
| 2025 | 78,8% | 19.407 kWh |
| 2026* | 40,6% | 2.695 kWh (*Nur Jan-Feb, Wintermonate) |

**Bemerkenswert**: 
- Trotz massivem Verbrauchsanstieg durch E-Autos (+65% 2022→2025) bleibt Autarkiegrad über 75%!
- 2021 niedriger Wert (29,3%) durch Teilbetrieb Nov-Dez (Wintermonate mit geringer Erzeugung)
- 2026 (Jan-Feb, Winter): 40,6% — typisch für Wintermonate mit 37,6 kWp

## Technische Erkenntnisse

### 0. P×t-Drift Problem (Jan-Feb 2026)

**Problem entdeckt:** Energiewerte vor 6. Feb 2026 systematisch ~50% zu niedrig

**Ursache:**
- Modbus-Polling alle 3s + Fronius-Counter-Update alle 5s
- P×t-Integration (Leistung × Zeit) driftete durch asynchrone Updates
- Beispiel: 193 kWh Solarweb-Referenz → 100 kWh gemessen (48% Fehler)

**Lösung:**
- Seit 6. Feb 2026: **Zählerstand-Delta** statt P×t-Integration
- Register-Differenz zwischen Messungen = exakte Energiemenge
- Kalibrierung mit Solarweb-Monatssummen für Jan+Feb 2026

**Status:**
- ✅ Jan+Feb 2026 mit Solarweb-Werten korrigiert
- ✅ Ab 6. Feb 2026 Zählerstand-Delta aktiv (korrekt)
- ⚠️ 2022-2025 CSV-Import ungeprüft (vermutlich korrekt, da aus Solarweb)

**Lesson Learned:**
- Modbus-Counter immer als Delta verwenden, nie als Instant-Wert mit P×t
- Regelmäßiger Solarweb-Abgleich essentiell
- Monatliche Validierung empfohlen

### 1. Null-Einspeisung funktioniert hervorragend

- **Durchschnitt 2022-2025**: 98,6% Eigenverbrauch
- Nur **170 kWh/Jahr** durchschnittliche Einspeisung
- Bei 12.137 kWh Jahresertrag im Schnitt

**Schlüsselfaktoren:**
- Batteriespeicher für Zeitverschiebung
- Wärmepumpe als flexibler Grundlast-Verbraucher
- E-Autos als "rollende Speicher" (ab 2024)
- Intelligente Steuerung (Fronius Solar.web)

### 2. E-Auto-Integration ist Gamechanger

**Vorher (2022-2023)**:
- Durchschnitt: 9.533 kWh Ertrag, 97 kWh Einspeisung
- Eigenverbrauch: 98,9%

**Nachher (2024-2025, mit E-Autos)**:
- Durchschnitt: 13.741 kWh Ertrag, 239 kWh Einspeisung
- Eigenverbrauch: 98,2% (nur -0,7% trotz +44% Ertrag!)

→ E-Autos absorbieren nahezu perfekt den Erweiterungsertrag

### 3. Skalierung der Anlage

Die Erweiterung von 21,4 kWp auf 37,6 kWp (+76%) führte zu:
- +67% mehr Ertrag (erwartet: +76% → Realität: -9% durch Teilverschattung?)
- Gleichbleibend hoher Eigenverbrauch (98,7%)
- Autarkie steigt von 74,6% auf 78,8%

**Warum funktioniert das?**
- Verbrauch wächst parallel (E-Autos: +5.423 kWh Wattpilot in 2025)
- 20,48 kWh Batterie (seit März 2026, vorher 10,2 kWh) bietet größere Nacht-/Morgen-Pufferung
- Multi-Wechselrichter-Setup verhindert Abregelung

### 4. Batterie-Dimensionierung

**20,48 kWh Batterie** (seit März 2026, vorher 10,2 kWh) bei 37,6 kWp PV!

Ratio: 0,27 kWh Batterie pro kWp PV (extrem niedrig)

**Normalerweise empfohlen**: 1-1,5 kWh/kWp

**Warum funktioniert es trotzdem?**
- Null-Einspeisung erzwingt Direktverbrauch
- Wärmepumpe (Dimplex SIK 11 TES): 2,1 kW Normbetrieb, max. 4,3 kW
- E-Autos: 3x 50kWh = 150 kWh "virtuelle Speicher"
- Batterie nur für Nacht/Morgen-Pufferung nötig

→ **Alternative zu großer Batterie: Große Verbraucher intelligent steuern**

## Verbrauchsstruktur 2025

| Verbraucher | Jahresverbrauch | Anteil |
|-------------|-----------------|--------|
| Gesamt | 19.407 kWh | 100% |
| Wattpilot (E-Autos) | 5.423 kWh | **28%** |
| Heizpatrone | 2.614 kWh | 13% |
| Wärmepumpe | geschätzt ~6.000 kWh | 31% |
| Haushalt | Rest ~5.370 kWh | 28% |

**Erkenntnisse:**
- E-Autos größter Einzelverbraucher (28%)
- Fast 100% PV-geladen (nur 199 kWh Einspeisung!)
- Wärmepumpe (Dimplex SIK 11 TES) ideal für PV-Grundlast

## Wirtschaftlichkeit

### Strompreise (taggenau, 2021-2026)

**Variable Tarife:**
- 05.11.2021 - 31.12.2022: **0,300 EUR/kWh** (1 Zähler)
- 01.01.2023 - 22.02.2024: **0,400 EUR/kWh** (3 Zähler)
- 23.02.2024 - 22.02.2026: **0,330 EUR/kWh** (schwankend 1-3 Zähler)
- Ab 23.02.2026: **0,300 EUR/kWh** (1 Zähler)

**Zählermiete:** 10 EUR/Monat (120 EUR/Jahr)

**Gewichtete Durchschnittspreise:**
- 2021 (Nov-Dez): 0,300 EUR/kWh + 20 EUR Zählermiete
- 2022: 0,300 EUR/kWh + 120 EUR Zählermiete
- 2023: 0,400 EUR/kWh + 120 EUR Zählermiete
- 2024: 0,344 EUR/kWh (gewichtet) + 120 EUR Zählermiete
- 2025: 0,330 EUR/kWh + 120 EUR Zählermiete
- 2026 (Jan-Feb): 0,324 EUR/kWh (gewichtet) + 20 EUR Zählermiete

### Einsparungen durch PV (2025)

**Berechnung:**
- Eigenverbrauch: 15.297 kWh × 0,33 €/kWh = **5.048 € gespart**
- Einspeisung: 199 kWh × 0,082 €/kWh = **16 € Vergütung**
- **Gesamt: 5.064 € Ersparnis in 2025**

**Vergleich mit Netzstrom:**
- Bei 19.407 kWh Verbrauch × 0,33 € + 120 € Zählermiete = **6.524 € Kosten**
- Mit PV: 3.911 kWh Netzbezug × 0,33 € + 120 € Zählermiete = **1.410 €**
- **Ersparnis: 5.114 € (78% weniger Kosten)**

### ROI-Überlegungen

**Investition (geschätzt):**
- Phase 1 (2021): ~20.000 € (21,4 kWp + Gen24 + Batterie)
- Phase 2 (2025): ~15.000 € (16,2 kWp + Gen24 + Symo)
- Batterie 2 (2026): ~3.000 € (2. BYD HVS Tower)
- **Gesamt: ~38.000 €**

**Amortisation:**
- Bei 5.000 €/Jahr Ersparnis: **7,6 Jahre**
- Ohne Erweiterung (bei 3.000 €/Jahr): **6,7 Jahre**

**Faktoren:**
- E-Autos amortisieren sich selbst (kein Benzin mehr)
- Wärmepumpe statt Gas/Öl: Zusätzliche Ersparnis
- Strompreissteigerung → schnellere Amortisation

## Empfehlungen für Nachahmer

### Was funktioniert hervorragend:

1. **Null-Einspeisung-Konzept**
   - Maximiert Eigenverbrauch
   - Minimiert Abhängigkeit von Einspeisevergütung
   - Stabilisiert Wirtschaftlichkeit

2. **E-Autos als Energiesenke**
   - Perfekte Nutzung von PV-Überschüssen
   - Wattpilot/go-eCharger für intelligentes Laden
   - 3 Autos = höhere Flexibilität (immer eines leer)

3. **Wärmepumpe als Grundlast**
   - Dimplex SIK 11 TES: 2,1 kW elektrisch (Normbetrieb), max. 4,3 kW
   - Perfekt für PV-Direktverbrauch
   - Pufferspeicher = thermische Batterie

4. **Multi-Wechselrichter-Setup**
   - Redundanz
   - Besseres MPP-Tracking
   - Flexible Erweiterung

### Was überrascht hat:

1. **Kleine Batterie ausreichend**
   - 20,48 kWh seit März 2026 (vorher 10,2 kWh für 37,6 kWp — funktionierte bereits)
   - Große Verbraucher wichtiger als große Batterie
   - Kosten/Nutzen: Kleine Batterie besser

2. **Eigenverbrauch trotz Erweiterung konstant**
   - Erwartet: Bei mehr PV sinkt Eigenverbrauch
   - Realität: E-Autos gleichen perfekt aus
   - 98-99% über alle Jahre

3. **Autarkie steigt mit E-Autos**
   - Erwartet: Verbrauch steigt, Autarkie sinkt
   - Realität: Von 74,6% auf 78,8%
   - Grund: E-Autos laden tagsüber (hohe PV)

### Kritische Erfolgsfaktoren:

1. **Verbrauchssteuerung**
   - Ohne Wattpilot/Smart Home: deutlich schlechter
   - Fronius Solar.web Integration wichtig
   - Automatisierung essentiell

2. **Dimensionierung**
   - PV großzügig, wenn Verbraucher da sind
   - Batterie klein halten, wenn Flexibilität vorhanden
   - Wechselrichter-Leistung > PV-Spitze

3. **Verbrauchsprofil passt**
   - E-Autos: Laden tagsüber möglich (Home Office/Schichtarbeit?)
   - Wärmepumpe: Kann zeitlich shiften
   - Haushalt: Normal verteilt

## Lessons Learned

### Was würde man anders machen?

1. **Noch früher größer bauen**
   - 2021 gleich 30+ kWp statt 21,4 kWp
   - Kosten/kWp sinken bei größeren Anlagen
   - Erweiterung kostet extra (Gerüst, Elektriker, ...)

2. **Zweite Batterie?**
   - Diskussionswürdig
   - Aktuell: 20,48 kWh (2× HVS parallel seit März 2026)
   - Alternative: E-Auto-Batterien als V2H (Vehicle-to-Home)
   - Kosten: 8.000 € für +10 kWh Batterie vs. bereits 150 kWh in Autos

3. **Symo statt zweiter Gen24?**
   - Gen24 bietet Notstrom + Batterieanbindung
   - Symo deutlich günstiger
   - Für F3 (4,5 kW) vermutlich ausreichend

### Zukunft: Was kommt?

1. **Vehicle-to-Home (V2H)**
   - Bidirektionales Laden
   - E-Auto als Haus-Batterie nutzen
   - 150 kWh statt 20,48 kWh verfügbar!

2. **Dynamische Stromtarife**
   - Tibber, aWATTar etc.
   - Netzbezug in günstigen Stunden
   - Weitere Optimierung möglich

3. **Wasserstoff-Heizung?**
   - Alternative zu Wärmepumpe
   - PV-Überschuss in H2 wandeln
   - Aktuell: Noch zu teuer/ineffizient

## Datenzusammenfassung

### Hardware Timeline

```
5. Nov 2021 | Start: 21,4 kWp + Gen24 10kW + BYD 10,2 kWh + WP
Apr 2024    | +3x E-Autos (50kWh) + Wattpilot
Mai 2025    | Erweiterung Start
Okt 2025    | Final: 37,6 kWp + Gen24 12kW + Gen24 10kW + Symo 4,5kW
Feb 2026    | Modbus-Logging: P×t → Zählerstand-Delta (Driftkorrektur)
Mär 2026    | +BYD HVS Tower 2 (BCU 2.0) → 20,48 kWh parallel
```

### Performance Summary

```
Zeitraum: Nov 2021 - Feb 2026 (4 Jahre 4 Monate)
Gesamt-Ertrag: 48.165 kWh
Gesamt-Einspeisung: ~695 kWh
Durchschnittlicher Eigenverbrauch: 98,56%

Beste Eigenverbrauch: 2021 (99,63%, Teilbetrieb)
Höchster Ertrag: 2025 (15.496 kWh)
Beste Autarkie: 2022 (81,6%)

Datenqualität:
- 2021-2025: CSV-Import aus Fronius Solarweb (validiert)
- Jan-Feb 2026: Solarweb-Korrektur wegen P×t-Drift (~50% Fehler)
- Ab 6. Feb 2026: Zählerstand-Delta (korrekt)
```

---

## Finanzielle Analyse & Amortisation (Update: 1. Januar 2026)

### Batteriewirkungsgrad-Entwicklung

**Kontinuierliche Verbesserung über 4 Jahre:**

| Jahr | Entladung | Ladung | Wirkungsgrad | Trend |
|------|-----------|--------|--------------|-------|
| 2022 | 1.766 kWh | 1.886 kWh | **93,63%** | Basis |
| 2023 | 1.751 kWh | 1.864 kWh | **93,94%** | +0,31% |
| 2024 | 2.066 kWh | 2.187 kWh | **94,46%** | +0,52% |
| 2025 | 2.375 kWh | 2.500 kWh | **95,00%** | +0,54% |

**Erkenntnis:** BYD HVS verbessert sich mit Alter/Nutzung, statt zu degradieren!  
Mögliche Gründe: Einfahreffekt, optimierte Ladealgorithmen, konstante Temperierung

### Autarkie-Validierung (Solarweb-Vergleich)

**2025 Detailanalyse:**
- **CSV-Berechnung**: 76,47% Autarkie
- **Solarweb-Anzeige**: ~76% Autarkie
- **Status**: ✅ **Perfekte Übereinstimmung**

Formel bestätigt:
```
Autarkie = Solar-Erzeugung / Gesamt-Verbrauch × 100%
Autarkie = 15.940 kWh / 20.844 kWh = 76,47%
```

**Interpretation:** Trotz 20,8 MWh Jahresverbrauch (inkl. E-Autos, Wärmepumpe, Haushalt) 
werden 76% selbst erzeugt – nur 4.905 kWh Netzbezug notwendig.

### Solarweb vs. Eigene Berechnung

**Wichtiger Unterschied bei Ersparnis-Darstellung:**

| Methode | 2025 Ersparnis | Formel |
|---------|----------------|--------|
| **Solarweb (Brutto)** | 5.251,93 € | Solar × Strompreis |
| **Eigene (Netto)** | 3.641,65 € | (Solar × Preis) - (Netz × Preis) |

**Differenz:** 1.610,28 € = Netzkosten, die Solarweb nicht abzieht

**Erklärung:**
- Solarweb zeigt: "Was ist Solar-Strom wert?" (Brutto)
- Wir zeigen: "Was spare ich wirklich?" (Netto = Brutto - Netzkosten)

Beide Methoden sind korrekt, nur unterschiedliche Perspektiven!

### PV-Anlage: Kosten pro kWh

**Investition:** 35.000 € (2022: 24.000 € + 2024: 8.000 € + 2026: 3.000 € Batterie 2)

**EUR/kWh Entwicklung (real):**

| Jahr | Kum. Invest | Kum. Solar | EUR/kWh (real) | Interpretation |
|------|-------------|------------|----------------|----------------|
| 2022 | 24.000 € | 9.267 kWh | **2,590 €** | Anfangsinvest sehr hoch |
| 2023 | 24.000 € | 19.065 kWh | **1,259 €** | Halbierung durch Produktion |
| 2024 | 32.000 € | 31.050 kWh | **1,031 €** | Neue Invest erhöht Kosten |
| 2025 | 32.000 € | 46.991 kWh | **0,681 €** | Weitere Amortisation |

**EUR/kWh Prognose (25 Jahre, 18.000 kWh/Jahr ab 2026):**

| Jahr | Prognose Gesamt | EUR/kWh (25J) |
|------|-----------------|---------------|
| 2022 | 441.267 kWh | **0,054 €** |
| 2023 | 433.065 kWh | **0,055 €** |
| 2024 | 427.050 kWh | **0,075 €** ← Sprung durch 8.000 € Invest |
| 2025 | 424.991 kWh | **0,075 €** |

**Wichtig:** Der Sprung von 0,055 auf 0,075 €/kWh ist auf die 8.000 € Erweiterung 2024 
zurückzuführen. Die zweite Investition erhöht die Kosten/kWh temporär, sinkt dann aber 
kontinuierlich durch steigende Produktion.

### Zwei-Tabellen-Amortisation

**Warum zwei Berechnungen?**

Die Gesamtinvestition umfasst **zwei unterschiedliche Systeme**:

#### 1. PV-Amortisation (Technische Sicht)
**Investition:** 35.000 € (reine PV-Anlage inkl. Batterie-Erweiterung 2026)  
**Berechnung:** Brutto-Ersparnis (Solar × Strompreis, wie Solarweb)

| Jahr | Brutto-Ersparnis | Rel. Amort. | EUR/kWh (25J) |
|------|------------------|-------------|---------------|
| 2022 | 2.780 € | 8,69% | 0,054 € |
| 2023 | 2.939 € | 9,19% | 0,055 € |
| 2024 | 3.955 € | 12,36% | 0,075 € |
| 2025 | 5.260 € | 16,44% | 0,075 € |

**Fokus:** Was kostet die PV-Anlage pro kWh? Wie schnell amortisiert sich das System selbst?

#### 2. Haushalts-Amortisation (Finanzielle Realität)
**Investition:** 47.000 € (PV 35.000 € + Wärmepumpe 12.000 €)  
**Berechnung:** Alle Ersparnisse (Strom-Netto + Heizung + Benzin)

**WICHTIG:** Heiz- und Benzin-Ersparnis sind **netto nach Abzug anteiliger Netzkosten** für WP und E-Auto.

| Jahr | Invest Jahr | Strom-Netto | Heizung | Benzin | GESAMT | Kumuliert |
|------|-------------|-------------|---------|--------|--------|-----------|
| 2022 | 36.000 € | 2.132 € | 1.500 € | 0 € | **3.632 €** | 3.632 € |
| 2023 | — | 2.228 € | 3.000 € | 0 € | **5.228 €** | 8.860 € |
| 2024 | 8.000 € | 2.665 € | 2.073 € | 1.694 € | **6.431 €** | 15.291 € |
| 2025 | — | 3.642 € | 1.997 € | 3.240 € | **8.879 €** | **24.170 €** |

**Amortisationsstand:** 24.170 € / 44.000 € = **54,9%** nach 4 Jahren

**Fokus:** Wie viel spart der gesamte Haushalt durch die Energiewende?

#### Anteilige Netzkosten-Korrektur (2024 & 2025)

**Methodik:**  
Nicht alle WP- und E-Auto-Energie kommt von PV. Ein Teil wird vom Netz bezogen:

**2024:**
- Netzbezug gesamt: 3.911 kWh × 0,33 € = 1.291 €
- Haushalt-Basis: 3.000 kWh (Licht, Komfort, Lüftung)
- **Netz-Überschuss:** 911 kWh → geht an WP (3.909 kWh) + E-Auto (2.726 kWh)
- Anteil WP aus Netz: 537 kWh → **177 €** (von Heiz-Ersparnis abgezogen)
- Anteil E-Auto aus Netz: 374 kWh → **124 €** (von Benzin-Ersparnis abgezogen)

**2025:**
- Netzbezug gesamt: 4.905 kWh × 0,33 € = 1.619 €
- Haushalt-Basis: 3.000 kWh
- **Netz-Überschuss:** 1.905 kWh → geht an WP (3.653 kWh) + E-Auto (5.423 kWh)
- Anteil WP aus Netz: 767 kWh → **253 €** (von Heiz-Ersparnis abgezogen)
- Anteil E-Auto aus Netz: 1.138 kWh → **376 €** (von Benzin-Ersparnis abgezogen)

**Resultat:** Die 2024/2025 Ersparnisse sind ehrlich – bezahlte Netzenergie wird nicht als "Ersparnis" gezählt.

### Heizkosten-Ersparnis (Basis-Faktor-Methode)

**Problem:** Brennstoffpreise schwanken (Energiekrise 2022/23)

**Lösung:** Basiswert mit Faktor multiplizieren

| Jahr | Faktor | Basiswert | Ersparnis |
|------|--------|-----------|-----------|
| 2022 | 1,0 | 1.500 € | **1.500 €** |
| 2023 | 2,0 | 1.500 € | **3.000 €** |
| 2024 | 1,5 | 1.500 € | **2.250 €** |
| 2025 | 1,5 | 1.500 € | **2.250 €** |

**Gesamt 2022-2025:** 9.000 € eingesparte Heizkosten (brutto, vor anteiligen Netzkosten)

### E-Auto Benzin-Ersparnis

**Berechnung über Wattpilot:**

| Jahr | Wattpilot | km gefahren | Benzin gespart |
|------|-----------|-------------|----------------|
| 2024 | 2.726 kWh | 18.177 km | **1.818 €** (brutto) |
| 2025 | 5.423 kWh | 36.155 km | **3.616 €** (brutto) |

**Formel:**
- Verbrauch E-Auto: 15 kWh/100km
- km = (Wattpilot kWh / 15) × 100
- Benzin-Ersparnis = (km / 100) × 10 € (angenommene Verbrenner-Kosten)

**Gesamt 2024-2025:** 5.434 € Benzin-Ersparnis (brutto, vor anteiligen Netzkosten)

### Gesamtersparnis 2022-2025

**Zusammenfassung aller Spareffekte (netto nach anteiligen Netzkosten):**

| Kategorie | 2022 | 2023 | 2024 | 2025 | Summe |
|-----------|------|------|------|------|-------|
| Strom (Netto) | 2.132 € | 2.228 € | 2.665 € | 3.642 € | **10.667 €** |
| Heizung (Netto) | 1.500 € | 3.000 € | 2.073 € | 1.997 € | **8.570 €** |
| Benzin (Netto) | — | — | 1.694 € | 3.240 € | **4.934 €** |
| **GESAMT** | **3.632 €** | **5.228 €** | **6.431 €** | **8.879 €** | **24.170 €** |

**Amortisation:** 24.170 € von 44.000 € = **54,9%** nach 4 Jahren  
**Hochrechnung:** Bei gleichbleibender Ersparnis vollständig amortisiert in ~8-9 Jahren

### Wichtige Schlussfolgerungen

1. **Batteriesystem verbessert sich mit Alter**
   - Von 93,63% auf 95,00% in 4 Jahren
   - Kein Degradations-Effekt sichtbar
   - BYD HVS sehr stabil und zuverlässig

2. **Autarkie-Messungen sind konsistent**
   - CSV-Auswertung und Solarweb stimmen überein
   - 76,47% bei 20,8 MWh Jahresverbrauch ist exzellent
   - E-Autos + Wärmepumpe perfekt integriert

3. **Ehrliche Ersparnis-Rechnung (anteilige Netzkosten)**
   - WP und E-Auto beziehen teilweise Strom vom Netz (2024: 911 kWh, 2025: 1.905 kWh)
   - Diese bezahlte Energie wird von Heiz- und Benzin-Ersparnis abgezogen
   - Resultat: Realistische Werte statt geschönte Zahlen
   - 2025: 629 € weniger "Ersparnis" als Brutto-Rechnung (aber dafür ehrlich)

4. **Solarweb zeigt Brutto, wir rechnen Netto**
   - Unterschied ~1.600 €/Jahr (Netzkosten)
   - Beide Perspektiven valide
   - Für Amortisation ist Netto relevanter

5. **PV-Kosten sinken dramatisch**
   - Von 2,59 €/kWh (2022) auf 0,68 €/kWh (2025)
   - Prognose 25 Jahre: 0,075 €/kWh
   - Deutlich günstiger als Netzstrom (0,30-0,33 €/kWh)

6. **Energiewende rechnet sich**
   - 54,9% amortisiert nach 4 Jahren
   - Drei Spareffekte zusammen: 24.170 € (netto)
   - Ohne System: ~24.000 € mehr Kosten gehabt

7. **Unsichtbare Ersparnisse**
   - Geld wird nicht verdient, sondern nicht ausgegeben
   - Portemonnaie fühlt sich leer an, aber Rechnung ist 77% niedriger
   - 2025 ohne PV: ~6.800 € Stromkosten (statt 1.619 €)

---

*Erstellt: 31. Dezember 2025*  
*Letzte Aktualisierung: 9. Februar 2026*  
*Version: 1.3 - P×t-Drift-Korrektur, 2021/2026-Daten, taggenau variable Strompreise + Zählermiete*
