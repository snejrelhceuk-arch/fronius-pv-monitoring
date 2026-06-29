# Zentrale TODO-Liste — PV-System

**Stand:** 2026-06-29  
**Regel:** Alle offenen Aufgaben gehoeren in DIESE Datei. Keine verteilten TODOs in Subdirectories. Ausschliesslich offene `- [ ]` ToDos — keine Audit-/Entwicklungsnotizen.

---

## Sicherheit & Haertung

- [ ] Team-Remediation: frische Klone bzw. `git fetch --all` + `git reset --hard origin/main` auf Pi4-Failover und Pi5-Backup ausfuehren (Nachgang zur Git-History-Bereinigung 2026-05-04)
- [ ] API-Authentifizierung evaluieren (bei Remote-Zugriff)
- [ ] Rate Limiting (`flask-limiter`, 60 req/min/IP)
- [ ] CORS auf Frontend einschraenken (bei Oeffnung)
- [ ] TLS via nginx-Proxy (bei Bedarf)
- [ ] Fehlermeldungen entschaerfen (`str(e)` → generische Antworten)

---

## Automation (Schicht C)

### Software-Items

- [ ] Dashboard-Erweiterung: Automation-Tab in Web-UI
- [ ] HP-Status in tag_view integrieren (flow_view zeigt bereits HP EIN/AUS)

### Architektur

- [ ] Wattpilot externe Pause-Erkennung in `AktorWattpilot.verifiziere()`
- [ ] State-Machine fuer HP-Phasen statt If-Kette (RegelHeizpatrone, 6 Phasen, ~1600 LOC → Phase-Objekte). **Vorbedingung:** Characterization-Test-Harness fuer die Phasenlogik (kein Test-Setup vorhanden → blinder Umbau des Produktiv-Schreibpfads zu riskant).
- [ ] pv-config: restliche ~36 inline-Magic-Numbers (Drain-/Probe-Konstanten, `HP_NENN_W` etc.) verhaltensneutral in `soc_param_matrix.json` heben (4 get_param-Defaults bereits freigelegt). Test-Harness empfohlen.

### Architektur-Refactor

- [ ] **`pv-config.py` (2145 Z.) sektionieren**: Whiptail-UI-Skript. Kandidaten fuer Auslagerung: Matrix-Editor (~500 Z.) → `tools/pv_config/matrix_editor.py`, Diagnose-Reader (~300 Z.) → `tools/pv_config/diagnose.py`, Service-Steuerung (~200 Z.) → `tools/pv_config/service.py`. Kein Service-Impact (manuell aufgerufen), aber Aufruf-Pfade in OLLI/-Scripts pruefen.
- [ ] `solar_geometry.py` (1979 Z.) und `solar_forecast.py` (1368 Z.) auf logische Sub-Module pruefen (Sonnengeometrie vs. Forecast-Cache vs. OpenMeteo-Client).
- [ ] `automation/engine/event_notifier.py` (1126 Z.) in Schwellen-/Dedup-/Mail-Module zerlegen.

### Tech-Debt (niedrige Prio)

- [ ] ForecastCollector Sunrise/Sunset-Fallback: saisonale Tabelle statt festem 7/17
- [ ] `tier1_checker._check_netz_ueberlast()`: `reduce_power`-Kommando mit explizitem Reduktionswert (proportional)
- [ ] `HP_NENN_W=2000` aus Code in `soc_param_matrix.json` als `hp_nenn_w` (statt Hardcode)

### Warnungen & Benachrichtigungen

- [ ] Passive Warnungen (Web-Dashboard): Inverter-Ausfall >10 min, Clear-Sky-Abweichung >40%, SOC-Spruenge >20%
- [ ] Forecast-Empfehlung: "Guter Tag morgen → EV-Ladung auf Mittagszeit"
- [ ] Wochenvorschau in Web-Ansicht

### Hardware: MEGA-BAS HAT

- [ ] Phase 0: I2C aktivieren, SMmegabas installieren, Board-Erkennung
- [ ] Phase 1: Thermistoren (WW oben/mitte/unten + Aussen) verkabeln & kalibrieren
- [ ] Phase 2: Installationsschuetz fuer 3-Phasen-HP (Zukunft)
- [ ] Phase 2b: Klimaanlage-Steuerung klaeren (Schuetz vs. IR-Sender)
- [ ] Phase 3: Bypass-Ventil (Stellantrieb 24VAC?)
- [ ] Phase 4: Lueftungsanlage & Brandschutzklappen
- [ ] Phase 7: 3-Phasen-Heizpatrone (Zukunft)

### Offene Hardware-Fragen

- [ ] F2: Externer WW-Temperatursensor der WP — Typ? NTC 10K? PT1000?
- [ ] F3: WPM-Reglerversion am Geraet pruefen (LCD=WPM_L/H, Touch=WPM_M)
- [ ] F5: Brandschutzklappen-Stellantriebe — Hersteller, Spannung, Rueckmeldekontakt?
- [ ] F5b: Klimaanlage — Schuetz oder IR-Sender?
- [ ] F6: Lueftungsgeraet — Steuerungsmoeglichkeiten (0-10V? Modbus?)
- [ ] F7: Bypass-Ventil — Motor- oder Magnetventil? Spannung?

---

## Diagnos (Schicht D)

- [ ] `integrity:monthly_rollup`: ~48 kWh Abweichung zwischen `monthly_statistics` und `daily_data`-Summe (CRIT, stabil) — Ursache klären (Counter-Reset / `statistics_corrections` / Aggregations-Drift) und bereinigen.
- [ ] Diagnos-Mailstruktur: Wording/Reihenfolge nachschärfen, nachdem die Statusdateien (`logs/diagnos/*.md`) im Betrieb beobachtet wurden.
- [ ] RAW-Status-Ursachenheuristik erweitern: Stromausfall vs. stale process klarer trennen (Korrelation mit Service-Restart-Logs statt nur Boot-Zeit).
- [ ] Optional: Netz-Anomalien (Schwankungen/Extremwerte) als eigene `logs/diagnos/Netz-Status.md`, sobald PAC4200/NQ produktiv.
- [ ] Phase 3: Infrastruktur-/IO-Pruefungen (LAN, SSH, API, MEGA-BAS, RS485) — sinnvoll **parallel** zur PAC4200-Inbetriebnahme im Mai
- [ ] Phase 4: Begrenzte Schutzaktionen mit Cooldown (nur falls noetig)
- [ ] Phase 5: Langzeitspeicher Diagnos-Berichte auf Pi5-SSD
- [ ] 3. lauschende Instanz: `failover_health_check.sh` analog auf Pi5-Backup deployen
- [ ] NQ-Aktivierung: `nq_notifier.ENABLED = True` setzen + `automation_daemon` einklinken, sobald PAC4200 produktiv


## Netzqualitaet

- [ ] Datenreduktion fuer Visualisierung: Min/Max/Spread/Std pro 5min-Bucket
- [ ] Baender-Darstellung (min/max als Flaeche + Mittelwert als Linie)

---

## Web / Datenexport

- [ ] Failover: Automatische Uebernahme und Rueckfall (aktuell manuell, bewusste Entscheidung)
- [ ] Datenexport CSV/JSON fuer externe Analyse
- [ ] Optional: Influx/Grafana-Bridge

---

## Solarweb-Abgleich

- [ ] Maerz-Abgleich durchfuehren
- [ ] 2022–2025 CSV-Import pruefen
- [ ] Langfristig: Abweichung beobachten (Zaehlerstand-Delta = korrekt seit Feb 6)
