# Netzqualitäts-Monitoring

Eigenständiges Teilprojekt innerhalb des PV-Systems. Überwacht Leiterspannungen,
Netzfrequenz und (perspektivisch) Muster in der Netzqualität.

## Status

| Phase | Status | Beschreibung |
|-------|--------|-------------|
| Sofortmaßnahme | ✅ erledigt | Frequenzlinie aus Tagesmonitoring entfernt, Echtzeit → Maschinenraum |
| Phase 1a | ✅ erledigt | Tagesprofil L-L-Spannungen + Frequenz |
| Phase 1b | ✅ erledigt | Eigene NQ-Datenbank (Monats-DBs) + 15min-DFD-Analyse |
| Phase 2 | geplant | Visualisierung, Kalenderprofile, Voraggregation, Messtechnik-Entscheidung |

## Architektur

- **Route:** `/netzqualitaet` → `templates/netzqualitaet_view.html`
- **API:** `/api/netzqualitaet/tag` → `routes/netzqualitaet.py`
- **NQ-Datenbank:** `netzqualitaet/db/nq_YYYY-MM.db` (monatliche SQLite-Dateien, ~20 MB/Monat)
- **Export:** `netzqualitaet/nq_export.py` (Cron, täglich 01:10)
- **Analyse:** `netzqualitaet/nq_analysis.py` (Cron, täglich 01:20)
- **Daten:** raw_data (3s) resampelt auf 5min-Raster; Fallback data_1min (L-N × √3)
- **Einstieg UI:** Flow → Maschinenraum → Button „Netzqualität"

## Projektgrenze

Netzqualitaet ist **fachlich ein separates Messtechnik-Projekt**, aber bewusst
im PV-System belassen.

- **Warum separat:** eigene Fragestellung, eigene NQ-DB, eigene Analyselogik,
  perspektivisch eigene Messtechnik
- **Warum im System:** bestehende API/UI, gemeinsamer Maschinenraum,
  Wiederverwendung vorhandener Infrastruktur und Feldsemantik

Aktueller Zuschnitt:

- `nq_export.py` liest die Haupt-DB **read-only** und kopiert nur NQ-relevante
  Spalten in eigene Monats-DBs
- `nq_analysis.py` arbeitet nur auf den NQ-DBs
- `routes/netzqualitaet.py` bleibt **read-only**
- es gibt **keinen** Write-Pfad vom NQ-Projekt in Collector, Automation oder
  Aktorik

Damit ist die Trennungspolicy fuer das NQ-Projekt aktuell eingehalten:

- **lesen** aus dem Gesamtsystem: ja
- **eigene Analyse-/Ablageebene:** ja
- **Rueckschreiben in die Produktionskette:** nein

## Phase-1-Signale

| Signal | DB-Feld | Quelle | Ebene |
|--------|---------|--------|-------|
| Leiterspannung L1-L2 | `U_L1_L2_Netz` | SmartMeter Netz | raw_data |
| Leiterspannung L2-L3 | `U_L2_L3_Netz` | SmartMeter Netz | raw_data |
| Leiterspannung L3-L1 | `U_L3_L1_Netz` | SmartMeter Netz | raw_data |
| Netzfrequenz | `f_Netz` | SmartMeter Netz | raw_data, data_1min |
| Phasenstrom L1 | `I_L1_Netz` | SmartMeter Netz | raw_data (Kontext) |
| Phasenstrom L2 | `I_L2_Netz` | SmartMeter Netz | raw_data (Kontext) |
| Phasenstrom L3 | `I_L3_Netz` | SmartMeter Netz | raw_data (Kontext) |

## Phase-1-Bausteine

1. **Tagesprofil** — Leiterspannungen + Frequenz im 5min-Raster (✅ vorhanden)
2. **NQ-Datenbank** — Eigene schlanke Monats-DBs mit 3s-Auflösung (✅ nq_export.py)
3. **15min-Handelstakt-Analyse** — DFD-Erkennung an Blockgrenzen (✅ nq_analysis.py)
4. **Lokale Kompensation** — Strom↔Spannung-Korrelation, Local Impact Score (✅ in Analyse integriert)

### NQ-Datenbank-Schema

**nq_samples** — Rohdaten (3s-Auflösung, ~20 MB/Monat):
`ts`, `f_netz`, `u_l1_l2`, `u_l2_l3`, `u_l3_l1`, `i_l1`, `i_l2`, `i_l3`

**nq_15min_blocks** — Blockstatistiken (96/Tag):
Frequenz (avg/min/max/std), Spannungen, Ströme, Unsymmetrie

**nq_boundary_events** — Grenzübergangs-Analyse (95/Tag):
DFD-Amplitude, Frequenzgradienten, Nadir, lokale Rückwirkung (Local Impact Score)

**nq_daily_summary** — Tageszusammenfassung:
DFD-Mittel (gesamt/Vollstunde/Viertelstunde), Frequenzbereich, Lokale vs. Netz-Events

### 15-Minuten-Handelstakt (DFD)

Hintergrund: EPEX SPOT handelt in 15-min-Blöcken. An Blockgrenzen
(xx:00, :15, :30, :45) wechseln die Fahrpläne der Erzeuger. Das erzeugt
die „Deterministic Frequency Deviation" (DFD) — dokumentiert von ENTSO-E.

Die Analyse untersucht:
- **Pre-Boundary** (letzte 60s vor Grenze): Frequenzabfall-Gradient
- **Post-Boundary** (erste 60s nach Grenze): Recovery-Gradient
- **Nadir**: Frequenzminimum im ±30s-Fenster um die Grenze
- **Referenz**: Blockmitte (5:00–10:00 im Block) als Baseline
- **Grenztyp**: Vollstunde > Halbstunde > Viertelstunde (nach Stärke)
- **Lokale Rückwirkung**: Stromänderung bei gleichzeitiger Spannungsänderung

## Phase-2-Ausblick

- Voraggregation L-L-Spannungen in data_1min / data_15min
- Kalenderprofile (Wochentag, Feiertag, Ferien, Jahreszeit)
- 15min-Handelsmuster-Indikatoren
- Unsymmetrie- und Korrelationskennzahlen
- Messtechnik-Entscheidung für Oberschwingungen (kHz–100kHz)

## Dateien

```
netzqualitaet/                   — Analyse-Modul
  __init__.py
  nq_export.py                   — Täglicher Export raw_data → Monats-DBs
  nq_analysis.py                 — 15min-DFD-Analyse + lokale Rückwirkung
  db/                            — Monatliche NQ-Datenbanken (gitignored)
    nq_2026-03.db
    nq_2026-04.db
routes/netzqualitaet.py          — API Blueprint (Tagesprofil)
templates/netzqualitaet_view.html — Chart-Seite (ECharts)
doc/netzqualitaet/               — Projektdokumentation
  README.md                      — dieses Dokument
  METHODEN.md                    — Methodenwahl fuer RMS-/Zeitreihenanalyse
  TOOLS.md                       — Python-Werkzeuge, Sinn vs. Aufwand
  MESSTECHNIK.md                 — Hardware-Matrix, Geraeteklassen, Trennlinie
  TRADE_SWITCH_DETECTION.md      — Erkennung Handels-/Schaltvorgaenge
  PAC4200_PI5_ENTSCHEIDUNGSVORLAGE.md — Hardware-Entscheidung
```

## Cron-Einrichtung

```bash
# NQ-Export: täglich 01:10, volle 2 Tage Puffer
10 1 * * *  cd ~/Dokumente/PVAnlage/pv-system && .venv/bin/python netzqualitaet/nq_export.py >> /tmp/nq_export.log 2>&1

# NQ-Analyse: täglich 01:20 (nach Export)
20 1 * * *  cd ~/Dokumente/PVAnlage/pv-system && .venv/bin/python netzqualitaet/nq_analysis.py >> /tmp/nq_analysis.log 2>&1
```
