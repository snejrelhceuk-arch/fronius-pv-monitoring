# NQ – Netzqualitäts-Analyse

Dedizierter Workspace auf Pi5 (192.0.2.204) für die Analyse der Stromnetzbeschaffenheit
am Hausanschluss (PCC – Point of Common Coupling).

## Herkunft

Extrahiert aus dem PVAnlage-Projekt auf Primary Pi4 (192.0.2.181).
Phase 1 dort vollständig abgeschlossen (2026-04-02).

## Struktur

```
NQ/
├── netzqualitaet/          # Python-Module (Export, Analyse, Detection)
│   ├── nq_export.py        # Täglicher Export raw_data → Monats-DBs
│   ├── nq_analysis.py      # 15min-DFD-Analyse (Deterministic Frequency Deviation)
│   ├── nq_trade_switch_detect.py  # Handelstakt-Detektion
│   └── db/                 # SQLite Monats-Datenbanken (~20 MB/Monat, 3s-Auflösung)
├── doc/netzqualitaet/      # Projektdokumentation
│   ├── README.md           # Übersicht
│   ├── METHODEN.md         # Mess- und Analysemethoden
│   ├── MESSTECHNIK.md      # Sensor-/Messtechnik-Dokumentation
│   ├── TOOLS.md            # Werkzeuge und Abhängigkeiten
│   ├── PHASE_1_PLAN.md     # Phase-1-Planung (abgeschlossen)
│   ├── TODO.md             # Offene Punkte
│   └── TRADE_SWITCH_DETECTION.md  # Handelstakt-Forschung
├── routes/                 # Flask-Route für Web-UI
├── templates/              # HTML-Templates (ECharts-Visualisierung)
├── config/                 # Konfiguration (nq_impedance.json)
└── .venv/                  # Python 3.11 + numpy
```

## Datenquellen

- **Fronius Smart Meter** via Fronius API (3s-Auflösung)
- Daten liegen weiterhin auf Pi4 und werden dort gesammelt
- Pi5 erhält Kopien der Monats-DBs zur Offline-Analyse

## Phase 2 (offen)

- DFD-Visualisierung in der Web-UI
- Kalenderprofile (Wochentag, Feiertag, Jahreszeit)
- Tages-/Wochenvergleiche der DFD-Stärke
- Erweiterte Sensorik (THD, Harmonische) – siehe MESSTECHNIK.md
