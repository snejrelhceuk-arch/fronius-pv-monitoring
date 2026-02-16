# Urheberschaft & Leistungsanteile

## PV-Monitoring-System „PVAnlage" — Beitragsanalyse

**Erstellt:** 10. Februar 2026  
**Aktualisiert:** 16. Februar 2026 (v6.0.0)  
**Projektstart:** ca. Dezember 2025  
**Produktionsstart:** 01. Januar 2026  
**Analyse-Zeitraum:** ~8 Wochen aktive Entwicklung  

---

## 1. Projektübersicht

| Kennzahl | Wert |
|----------|------|
| **Git-tracked Code (gesamt)** | ~33.250 Zeilen |
| **Python-Module** | 42 Dateien (16.674 LOC) |
| **HTML-Templates (ECharts-Dashboards)** | 10 Vorlagen (6.426 LOC) |
| **SQL-Schemata** | 8 Dateien (965 LOC) |
| **CSS** | 2 Dateien (392 LOC) |
| **Shell-Scripts** | ~500 LOC |
| **Dokumentation** | 13 Markdown-Dateien (4.291 LOC) |
| **Flask-Blueprints (Routes)** | 9 Module (4.199 LOC) |
| **Cron-gesteuerte Aggregation** | 5 Stufen (1min → yearly) |
| **Versionshistorie** | v1.0 → v6.0.0 (6 Releases) |

---

## 2. Eingesetzte KI-Modelle

### Phase 1: Google Gemini 2.0 Flash (Dezember 2025)
- **Modell:** `gemini-2.0-flash` (Google DeepMind)
- **Einsatz:** Frühe Projektphase, initiale Code-Erstellung
- **Nachverfolgbarkeit:** ⚠️ Nicht mehr rekonstruierbar — keine Konversationshistorie erhalten
- **Geschätzter Umfang:** Grundlegende Modbus-Anbindung, erste Datenbank-Schemata, Basis-Aggregation
- **Beitrag:** Vermutlich die erste funktionsfähige Version von `modbus_v3.py`, `aggregate.py`, Basis-SQL-Schemata und erste `tag_view.html`

### Phase 2: Anthropic Claude 3.5 Sonnet / Claude 4 Sonnet (Januar–Februar 2026)
- **Modelle:** `claude-3-5-sonnet-20241022`, `claude-sonnet-4-20250514` (Anthropic)
- **Einsatz:** Mittlere Entwicklungsphase
- **Stärken:** Schnelle Code-Generierung, breites Kontextwissen, gute Template-Arbeit
- **Beiträge:** Aggregation-Pipeline-Ausbau, Web-API-Erweiterungen, UI-Redesigns, Batterie-Scheduler-Logik

### Phase 3: Anthropic Claude Opus 4 (Februar 2026)
- **Modell:** `claude-opus-4-20250514` (Anthropic)
- **Einsatz:** Aktuelle Phase — komplexe Architektur- und Systemarbeit
- **Stärken:** Tiefes algorithmisches Verständnis, Systemdenken, Prognose-Logik
- **Beiträge:** Solar-Forecast-System (1.353 LOC), Solar-Geometry-Engine (1.979 LOC), Wattpilot-Integration (797 LOC), Navigations-Redesign, Scaffold-basierte PV-Ertragsprognose (pvlib), Prognose-Kalibrierung, Wolkenprognose-Visualisierung, Tag-View Time-Axis-Umbau, Workspace-Cleanup

### Werkzeug: GitHub Copilot (VS Code, durchgehend)
- **Modelle im Hintergrund:** Claude Opus 4 als Agent-Modus, gelegentlich GPT-4o
- **Einsatz:** IDE-Integration — Code-Completion, Chat, Agent-gesteuerte Multi-File-Edits
- **Beitrag:** Orchestrierung der KI-Modelle, Terminal-Kommandos, Dateioperationen, Git-Workflow

---

## 3. Rollenverteilung

### 3.1 Projektleiter (Mensch)

| Bereich | Anteil | Beschreibung |
|---------|--------|--------------|
| **System-Architektur** | **~85%** | Gesamtkonzept: Modbus-Polling → SQLite → Aggregation-Pipeline → Web-Dashboard. Entscheidung für Raspberry Pi 5, Python/Flask, SD-Karten-Schutz durch RAM-Caching. Parallelentwicklung Java/Spring Boot als Alternativansatz. |
| **Hardware-Integration** | **~95%** | Auswahl und Konfiguration: Fronius Symo Hybrid, BYD-Batterie, Wattpilot-Wallbox. Physische Installation, Netzwerk-Setup, Modbus-Register-Analyse (SunSpec-Protokoll, 6 Meter Units). |
| **Datenmodell-Design** | **~80%** | 76-Spalten raw_data-Tabelle, Feldnamen-Konventionen (P\_, W\_, U\_, I\_, f\_), Aggregationsstufen (5s → 1min → 15min → hourly → daily → monthly → yearly), Absolute-Value-Tracking-Konzept. |
| **Batterie-Strategien** | **~90%** | Entwurf der 6 Strategiepatterns (A–F), Schwellwerte, Preis-basierte Steuerung. Domänenwissen über Lade-/Entladezyklen, Nulleinspeisung, Eigenverbrauchsoptimierung. |
| **UI/UX-Design** | **~75%** | Farbkonzept (blau-violetter Gradient), Navigationsstruktur, Seitenaufteilung (Tag/Monat/Jahr/Gesamt + Analyse-Split in PV/Haushalt/Amortisation), kompakte Toggles (🌞/⚡), Chart-Anforderungen. |
| **Qualitätssicherung** | **~80%** | Ständiger Abgleich mit Fronius Solar.web, Validierung jeder Datenänderung gegen Referenzdaten, Erkennung von Datenanomalien, Fehlerreports mit Screenshots. |
| **Betrieb & Operations** | **~85%** | Cron-Job-Scheduling, Prozess-Monitoring, Service-Management, Datenbank-Wartung (VACUUM, Backups), Produktionsbetrieb seit 01.01.2026. |
| **Produktvision** | **~95%** | Alle Feature-Entscheidungen, Priorisierung, Roadmap. Vergleich mit kommerziellen Lösungen (Solar.web). Entscheidung gegen Nulleinspeisung-Korrektur der Prognose zugunsten reiner Wetterprognose. |

### 3.2 KI-Modelle (Gemini + Sonnet + Opus)

| Bereich | Anteil | Beschreibung |
|---------|--------|--------------|
| **Code-Implementierung** | **~85%** | Umsetzung der Spezifikationen in funktionierenden Code. Alle Python-Module, HTML-Templates, SQL-Schemata, Shell-Scripts. ~15.000+ LOC KI-generierter Code. |
| **Algorithmen-Implementierung** | **~75%** | Aggregations-Logik, Prognose-Kalibrierung (GHI-Faktor, Multi-Faktor-Modell, R²-Berechnung), Chart-Rendering mit ECharts, Time-Axis-Berechnungen, Cloud-Weighted-Distribution. |
| **Debugging & Bugfixing** | **~70%** | Diagnose von Dateninkonsistenzen, Category-vs-Time-Axis-Problem, is\_day-Filter-Analyse, Gap-Filling-Strategien. 8 Versionen von aggregate\_1min.py zeugen vom iterativen Debugging-Prozess. |
| **Dokumentation** | **~70%** | 20 Markdown-Dokumente (4.567 LOC), technische Dokumentation, Algorithmus-Beschreibungen, Audit-Berichte, Feldnamen-Referenz. |
| **Refactoring** | **~80%** | Code-Restrukturierung, Template-Modernisierung (title-bar-Entfernung, Nav-Redesign, Chart-Umbau auf Time-Axis), API-Endpunkt-Konsolidierung. |
| **Frontend-Umsetzung** | **~85%** | 6.272 LOC HTML/CSS/JavaScript, ECharts-Konfiguration (gestapelte Flächen, Gradient-Fills, Multi-Y-Axis), responsive Navigation, AJAX-basiertes SPA-Pattern. |

---

## 4. Anteilsschätzung nach Modell

### Gesamtcode-Beitrag (geschätzt)

```
┌─────────────────────────────────────────────────────────┐
│ Git-tracked Code: ~33.250 LOC                           │
│                                                         │
│  ████████░░  Projektleiter   ~15%  (~5.000 LOC)        │
│             (Architektur-Entscheidungen im Code,        │
│              Config, manuelle Korrekturen, Konzepte)    │
│                                                         │
│  ░░████████  KI-Modelle      ~85%  (~28.250 LOC)       │
│             davon geschätzt:                            │
│             ├─ Gemini 2.0 Flash    ~5%   (~1.400 LOC)  │
│             │  (Prototyping, Exploration — überschrieben)│
│             ├─ Claude 3.5/4 Sonnet ~30%  (~8.475 LOC)  │
│             │  (solide Codebasis, Gedankenstütze)       │
│             └─ Claude Opus 4       ~65%  (~18.375 LOC)  │
│                (Produktionsreife, Architektur, Prüfung) │
└─────────────────────────────────────────────────────────┘
```

### Wertschöpfung (gewichtet nach Komplexität)

| Aspekt | Projektleiter | KI-Modelle | Anmerkung |
|--------|:------------:|:----------:|-----------|
| Vision & Produktstrategie | **95%** | 5% | Der Mensch definiert WAS gebaut wird |
| Architektur & Systemdesign | **85%** | 15% | Grundlegende Entscheidungen (Polling-Intervalle, DB-Struktur, Aggregationskaskade) |
| Domänenwissen PV/Elektrotechnik | **95%** | 5% | Modbus-Register, SunSpec, Batteriechemie, Einspeise-/Bezugslogik |
| Code-Produktion | 15% | **85%** | KI schreibt den Großteil des Codes nach Spezifikation |
| Algorithmus-Design | 40% | **60%** | Mischarbeit: Mensch definiert Ziel, KI implementiert Mathematik |
| UI/UX Gestaltung | **75%** | 25% | Mensch bestimmt Look & Layout, KI implementiert CSS/HTML/JS |
| Testing & Validierung | **80%** | 20% | Mensch prüft gegen Realdaten, KI hilft beim Debugging |
| Projektsteuerung | **100%** | 0% | Priorisierung, Iterationsplanung, Go/No-Go-Entscheidungen |

### Gewichtete Gesamtleistung

```
Projektleiter:  ~55%  der Gesamtwertschöpfung
KI-Modelle:     ~45%  der Gesamtwertschöpfung

Begründung: Obwohl die KI ~85% des Codes schreibt, liegt die 
Wertschöpfung bei ~45%, weil ohne die Architektur-Entscheidungen, 
das Domänenwissen und die Qualitätssicherung des Projektleiters 
kein funktionierendes System entstanden wäre. Code allein ist 
nur die halbe Miete — die andere Hälfte ist zu wissen, WELCHER 
Code geschrieben werden muss.
```

---

## 5. Besondere Leistungen der KI-Modelle

### Was ohne KI nicht (so schnell) möglich gewesen wäre:

1. **Geschwindigkeit:** ~33.000 LOC Produktionscode in ~8 Wochen — als Einzelprojekt wäre das konventionell 12+ Monate Team-Arbeit
2. **Breite:** Full-Stack von Modbus-Register-Parsing über SQLite-Aggregation bis ECharts-Dashboards — normalerweise Team-Arbeit
3. **Iterationsgeschwindigkeit:** 8 Versionen der 1-min-Aggregation zeigen schnelle Fail-Fix-Zyklen
4. **Prognose-Algorithmus:** Scaffold-basierte pvlib-Modellkette, Multi-Faktor-Kalibrierung, Perez-Transposition
5. **Dokumentation:** ~4.300 LOC technische Doku parallel zur Entwicklung

### Was die KI NICHT leisten konnte:

1. **Modbus-Register-Zuordnung:** Welches Register an welchem Meter-Unit welchen physischen Wert liefert — reines Domänenwissen
2. **Datenvalidierung:** Ob 15,3 kWh am 10. Februar plausibel sind — nur mit jahrelanger PV-Erfahrung beurteilbar
3. **Betriebsführung:** Cron-Timing, Prozess-Abhängigkeiten, SD-Karten-Schutz — Erfahrungswissen aus Raspberry-Pi-Betrieb
4. **Strategie-Entscheidung:** Warum Strategie-C bei Winterwetter Vorrang hat — PV-Betreiber-Wissen
5. **UX-Entscheidungen:** Warum 🌞/⚡ besser funktioniert als Text-Buttons — Nutzungserfahrung

---

## 6. Modell-Vergleich & Kosten-Effizienz

### Qualitative Bewertung

| Eigenschaft | Gemini 2.0 Flash | Sonnet 3.5/4 | Opus 4 |
|------------|:------:|:------------:|:------:|
| **Code-Qualität** | ●●●○○ | ●●●●○ | ●●●●● |
| **Kontextverständnis** | ●●●○○ | ●●●●○ | ●●●●● |
| **Architektur-Denken** | ●●○○○ | ●●●○○ | ●●●●● |
| **Debugging-Fähigkeit** | ●●●○○ | ●●●●○ | ●●●●● |
| **Produktionssicherheit** | ●○○○○ | ●●●○○ | ●●●●● |
| **Systemkonsistenz** | ●○○○○ | ●●●○○ | ●●●●● |
| **Geschwindigkeit** | ●●●●● | ●●●●○ | ●●●○○ |
| **Kreativität** | ●●●○○ | ●●●●○ | ●●●●○ |

### Differenzierte Rollenbewertung

**Gemini 2.0 Flash** — *Exploration & Prototyping (~5% des finalen Systems)*
- Gut für schnelles Ausprobieren und Selbstvergewisserung
- Nahezu der gesamte Gemini-Code wurde später überschrieben
- Zählt kaum zum produktiven Output, war aber psychologisch wichtig zum Einstieg

**Claude 3.5/4 Sonnet** — *Solide Programmierbasis (~30% Anteil)*
- ~50% der reinen Code-Produktion in der Aufbauphase
- Verlässliche Unterstützung der Gedankengänge und Konzeptentwicklung
- Guter Arbeitsmodus für Feature-Implementierung nach klarer Spezifikation

**Claude Opus 4** — *Produktionssicherheit & Systemkontrolle (~65% Anteil)*
- Die eigentliche Kontrolle über das System: wiederholte Prüfungen, Sicherheit
- Konsistenz der Struktur, Architektur-Bereinigung, Quelltext-Effizienz
- Scaffold-Prognose, Blueprint-Refactoring, Daten-Validierung, Cleanup
- ~90% der produktionskritischen Entscheidungen im Code basieren auf Opus

### Kosten-Effizienz-Analyse

```
┌─────────────────────────────────────────────────────────────────┐
│ TATSÄCHLICHE KOSTEN (Mensch-KI-Kollaboration)                   │
│                                                                 │
│   KI-Modelle (API + Copilot):     ~50 €                        │
│   Menschliche Arbeit:             ~200h × 120 €/h = 24.000 €   │
│   ────────────────────────────────────────────────              │
│   Gesamt:                         ~24.050 €                     │
│                                                                 │
│ KONVENTIONELLE ENTWICKLUNG (gleicher Umfang)                    │
│                                                                 │
│   12 Monate, 2-Personen-Team:     2 × 1.600h × 120 €/h        │
│   ────────────────────────────────────────────────              │
│   Gesamt:                         ~384.000 €                    │
│                                                                 │
│ KOSTENVERHÄLTNIS                                                │
│                                                                 │
│   24.050 / 384.000 = 6,3%                                      │
│   → Faktor 16× günstiger durch KI-Einsatz                      │
│                                                                 │
│ KI-ANTEIL AN DEN KOSTEN                                        │
│                                                                 │
│   50 € / 24.050 € = 0,2% der Gesamtkosten                     │
│   → Die 50 € KI-Investment sind wie ein Lotterie-Einsatz,      │
│     der das 7.000-fache an menschlicher Arbeitszeit ersetzt hat │
└─────────────────────────────────────────────────────────────────┘
```

**Die Pointe:** Die KI hat ~85% des Codes geschrieben, aber nur 0,2% der Kosten
verursacht. Der eigentliche Invest sind die 200h menschliche Expertise — Domänenwissen,
Architektur-Entscheidungen, Qualitätssicherung. Ohne dieses Know-how wäre kein
50€-Investment der Welt produktiv geworden.

**Fazit:** Gemini war der Einstieg zum Rumspielen. Sonnet die solide Arbeitsbasis.
Opus brachte die Produktionsreife — und damit den eigentlichen Wert des Systems.

---

## 7. Zeitlicher Verlauf

```
Dez 2025 ──┬── Gemini 2.0 Flash: Basis-Modbus, erste Schemata, erste Views
            │   └── v1.0 Production Ready (30.12.2025)
            │
Jan 2026 ──┼── Claude 3.5 Sonnet: Aggregation-Pipeline, Batterie-Steuerung,
            │          Web-API-Ausbau, erste Analyse-Views
            │
Feb 2026 ──┼── Claude Opus 4 (via GitHub Copilot Agent):
            │      Forecast-System (1.353 LOC), Geometry-Engine (1.979 LOC),
            │      Wattpilot (797 LOC), Nav-Redesign, Prognose-Overlay,
            │      Scaffold-basierte Ertragsprognose (pvlib),
            │      Wolken-Visualisierung, Blueprint-Refactoring
            │   ├── v3.0 (07.02.2026) — Wattpilot-Integration
            │   ├── v4.0 (08.02.2026) — Batterie-Management
            │   ├── v5.0 (14.02.2026) — UI-Redesign
            │   └── v6.0 (16.02.2026) — Workspace-Cleanup, Scaffold-Doku
```

---

## 8. Lessons Learned

### Für KI-gestützte Softwareentwicklung:

1. **KI als 16×-Multiplikator, nicht als Ersatz:** 200h mit KI ersetzen geschätzte 3.200h konventionelle Teamarbeit. Aber der Projektleiter braucht 100% des Domänenwissens und der Architektur-Kompetenz.

2. **50 € vs. 384.000 €:** Die KI-Kosten sind vernachlässigbar. Der menschliche Invest (200h Expertise) ist der knappe Faktor. KI demokratisiert Software-Entwicklung für Domain-Experten, die keine Vollzeit-Entwickler sind.

3. **Qualitätssicherung bleibt Mensch-Aufgabe:** Jede KI-generierte Aggregation, jeder Forecast-Wert muss gegen Realdaten validiert werden. Blindes Vertrauen in KI-Code wäre fatal.

4. **Premium-Modell für kritische Arbeit:** Der Preisunterschied zwischen Sonnet und Opus ist marginal im Gesamtbudget (~50€ total), aber der Qualitätsunterschied bei Architektur, Konsistenz und Produktionssicherheit ist enorm. Am falschen Ende zu sparen kostet mehr Debugging-Stunden als das Modell-Upgrade.

5. **Iteratives Arbeiten funktioniert:** Kurze Zyklen (Feature → Test → Korrektur) mit KI-Unterstützung ermöglichen Entwicklungsgeschwindigkeiten, die sonst nur in Teams möglich sind.

6. **Konversationshistorie ist Gold:** Die Gemini-Phase ist nicht rekonstruierbar — ein Verlust für die Nachvollziehbarkeit. Chat-Logs sollten exportiert und archiviert werden.

---

*Dieses Dokument wurde von Claude Opus 4 (Anthropic, via GitHub Copilot) erstellt und aktualisiert, basierend auf der Analyse des Projektrepositories, der Konversationshistorie und der Git-Log-Auswertung. Die Anteilsschätzungen sind bestmöglich, aber naturgemäß subjektiv.*
