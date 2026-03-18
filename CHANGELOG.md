# Changelog — PV-System Erlau

Alle wesentlichen Änderungen am System, chronologisch absteigend.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/).

---

## [Unreleased]

### Projektankündigungen
- MEGA-BAS Rollout: I2C-HAT-Inbetriebnahme mit zusätzlicher Temperatur-Sensorik und vorbereiteter Aktorik für kommende Hardware-Phasen.
- 3-Phasen-Heizpatrone (Zukunftsphase): Konzept für stufenweise Zuschaltung und Schützstrategie als nächster Ausbauschritt.

## v1.2.0 — 2026-03-18

### Features
- Batterie-System auf 2× BYD HVS (20.48 kWh) umgestellt; Automationslogik auf SOC-Entscheidungen fokussiert (keine Lade-/Entladeraten-Regelkreise mehr, klare SOC-Fensterstrategie).
- Wärmepumpe über LWPM-410 Modbus-RTU integriert: Infos auslesen und WW-Nachtabsenkung automatisch.
- Fritz!DECT Multi-Device-Integration (Heizpatrone + Klimaanlage) mit 10s-Polling in der Automation.
- Flow-View erweitert: Informationen und tägliche Zuschaltung für Eigenverbrauch (Wattpilot, Wärmepumpe, Heizpatrone, Klimaanlage).
- HP-Schaltchronik in der UI: Automation-Events orange, externe/manuelle Schaltungen rot.
- Eigenes System-Health-Modul zur Systemüberwachung (Rollenverteilung Schicht D) mit Checks für Host, Services, Daten-Freshness und Push-Mail-Warnungen.

### Fixes
- `NaN`-Flackern in der Flow-Ansicht behoben (Smoothing ergänzt um HP/Klima).
- API liest HP/Klima ausschließlich aus Observer-DB (`fritzdect_readings`), ohne Hardwarezugriff.
- DB-Schema für Fritz!DECT-Echtzeitdaten auf Multi-Device-Betrieb korrigiert (`PRIMARY KEY (ts, device_id)`).

### Dokumentation
- Fritz!DECT-Dokumentation in den Automation-Bereich verschoben:
  doc/automation/fritzdect/.

---

## v1.1.1 — 2026-03-14

### Geändert
- **Autoritätsschaltung:** Manuelle HP-Einschaltung wird für `extern_respekt_s` (Default 30 Min, 15 Min–2 h) respektiert. Nur Übertemp, SOC ≤ 5% und SOC ≤ `extern_notaus_soc_pct` (15%) überstimmen. Phase 4 und weiche Kriterien pausieren. Manuelles Ausschalten sperrt hp_ein analog.
- **extern_respekt_s**: Default 3600→1800, Bereich [0,7200]→[900,7200]

### Hinzugefügt
- **extern_notaus_soc_pct**: Neuer Parameter (Default 15%, [5–30%]) — SOC-Schwelle für Autoritäts-Override bei manueller Einschaltung

---

## v1.1.0 — 2026-03-09

### Dokumentation
- Doku-Restrukturierung in Themenordner (`system/`, `automation/`, `collector/`, `web/`, `meta/`, `archive/`).
- SYSTEM_BRIEFING und Batterie-Doku konsolidiert; Korrekturen zu Kapazität und Architekturdetails.

### Fixes (Tiefenprüfung 2026-03-08)
- HP-Startup-Schutz, SLS-Regel-Integration und SOC-Extern-Registrierung stabilisiert.
- Früh-Reset-Hysterese und DataCollector-Cache-Verhalten verbessert.
- Technische Bereinigung: toter Modbus-Code entfernt, Magic Number durch Config-Parameter ersetzt.

### Config
- **S2:** 4 entfernte Regelkreise auf `aktiv: false` gesetzt (GEN24 HW-Limit)
- **S3:** Hardware-Kapazität 10.24→20.48 kWh korrigiert

---

## 2026-03-08

### Features
- **SLS-Netzschutz:** `RegelSlsSchutz` — 35A/Phase-Überwachung mit Fritz!DECT + Wattpilot-Dimmung (`6fd032d`)
- **HP 6-Phasen-Logik:** Differenziertes Heizpatronen-Verhalten nach Tageszeit und SOC

### Fixes
- Drain nur bei PV-Ladung + ABC-Policy durchsetzen (`0d61ed0`)
- Falsche EXTERN-Erkennung durch `engine_vorausschau()` und Daemon-Restart (`e15d23e`)
- Drain-Selbstoszillation — HP-Eigenverbrauch von `house_load` abziehen (`3eebf33`)

---

## 2026-03-07

### Refactoring
- **Entladerate/Laderate-Regeln entfernt** — GEN24 DC-DC HW-Limit macht sie obsolet (`5b34661`)

### Fixes
- NULLIF(0)-Schutz für SmartMeter/F2/F3/WP-Counter nach FW-Update (`94be85d`)
- Fritz!DECT `dry_run=True` entfernt — HP-Schaltbefehle aktiv (`e09e373`)

---

## 2026-03-06

### Features
- **Sunset-Tagesbericht:** Tägliche 24h-Zusammenfassung per E-Mail (`d32c8a1`)
- **BMS-Live + E-Mail:** Tier-1 SOC Recovery, BMS-Zustandsanzeige, Forecast-Verbesserungen (`47cb477`)

### Fixes
- Tiefenprüfung v1.1.0 — 8 Bug-Fixes (2×CRITICAL, 4×HIGH, 2×Infra) (`4575c34`)

---

## 2026-03-05

### Features
- **Batterie-Upgrade:** 2× BYD HVS 20.48 kWh parallel — Kapazität verdoppelt (`403135c`)

---

## 2026-03-04

- SOC-Extern-Toleranz + Morgen-Vorlauf + Docs (`18f4bbf`)

---

## 2026-03-02

### Features
- **Analyse-Ansichten:** Navigation, Tages-/Monatssummen, Amortisationsrechner, Dark-Theme (`ff8c768`)

---

## 2026-03-01

### Features
- **Heizpatrone:** RegelGeraete-Integration, Failover-Tuning, Kalibrierung (`0adc07e`)

### Dokumentation
- Doku-Audit: 17 Dokumente mit Code-Realität abgeglichen (`b4bdfe6`)

### Refactoring
- `sys.path`-Hacks entfernt, `system.py` refactored, `monitor_web_service.sh` gelöscht (`f923b14`)

---

## 2026-02-28

### Features
- **HP-Automation via Fritz!DECT** — Komplett-Implementation (`85ef2b3`)
- **RegelKomfortReset**, SOC-HTTP-Collector, DB-Fix, Scheduler archiviert (`f04128b`)
- **ForecastCollector (Tier-3)** — Trigger-basierte Prognose (`0414f74`)
- **Observer:** systemd-Service + SQLite `check_same_thread` Fix (`0ce4f72`)

### Refactoring
- **Engine + Observer** in Subpackages aufgeteilt (`b443081`)
- `battery_control.py` → `automation/battery_control.py` (`3188b8a`)
- Morgen-Algo: PV-Rampe statt Tagesprognose, Sunrise-Start statt 05:00, radikal vereinfacht (`172bf00`, `6610328`, `f9c07e9`)
- Morgen-Schwelle 500→1500 W (Haushaltslast berücksichtigen) (`fd4031b`)

### Fixes
- Tiefenprüfung: 12 Fixes (K1-K3 kritisch, H1-H7 hoch, M5-M8 mittel) (`0ee2301`)
- Tiefenprüfung: 7 Fixes (P1-P3) + 21/21 Tests grün (`b20fab8`)
- Morgen-Algo Regel B: falsche Untergrenze 25%→5 % (`10afa9a`)
- ForecastCollector: Sunrise-Fallback auf Vortageswerte (`0ebb751`)

---

## 2026-02-27

### Features
- **pv-config.py** + Windows-Terminal Zugang (`93ef251`)

### Fixes
- SOC-Schutz blockierte Laden — `hold_battery()` durch `set_discharge_rate(0)` (`7665d66`)
- Windows: BAT-Dateien ASCII, FAT32-kompatible Dateinamen (`4d64e75`, `3e4140d`)

---

## 2026-02-25 – 2026-02-26

### Features
- **Automation-Engine:** Sunrise-basierte Morgen-Regel + Nachmittag-Dynamik (`d677a6d`)

### Fixes
- Simulation entfernt, Konsistenz-Check Richtungslogik (`2b18f46`)

---

## 2026-02-20 – 2026-02-22

### Features
- **Dual-Host Failover:** Role-Guard, `host_role.py`, Mirror-Standby (`6d93295`, `ffed876`)
- **Flow-View:** Failover-Status-Badge (Safe: Live/Host/Down), Backup-Badge (`eb10a92`, `67705bc`)
- **Simulation-Modus**, Favicon, Scheduler-Bar + 4 neue Dokus (`926140d`)

### Fixes
- Aggregations-Pipeline und Verlustanalyse (`d21913e`)
- Failover: Reboot-Resilienz, SD-Fallback-DB, Safe-Badge via SSH (`89e0087`, `33e9f50`)
- `geschützte Tage` (SolarWeb-Korrektur) nicht überschreiben (`40f263f`)

### Dokumentation
- SYSTEM_ARCHITECTURE + DUAL_HOST auf 3-Host-Topologie aktualisiert (`647f427`)
- Compliance-Checkliste in PRs, Governance-Referenzen (`21abd73`, `0526c5f`)

---

## v6.1.0 — 2026-02-19

### Features
- **SolarWeb-Import**, Counter-Strategie, Frequenz-Infozeile, Scroll-Legende (`6a99bce`)
- **Batterie-Energie:** I×U-Integration statt Proxy-Formel + BMS-Fixpunkte (`b938786`)
- Update-Strategie dokumentiert, Dependencies gepinnt (`476e040`)

---

## v6.0.0 — 2026-02-16

### Initial Release
- **Fronius PV-Monitoring System** — Erstversion mit Collector, Web-API (Flask/Gunicorn), Flow-View (`65ba369`)
- Mobile-Optimierung: kompakte Achsen, Flow ohne Sub-Kreise (`3ffc10c`)
