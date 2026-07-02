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

- [ ] State-Machine fuer HP-Phasen statt If-Kette (RegelHeizpatrone, 6 Phasen → Phase-Objekte). **Sicherheitsnetz vorhanden:** `tests/test_heizpatrone_characterization.py` (28 Szenarien, golden-master) — Refactor inkrementell gegen das gruene Golden ausfuehren und die Szenario-Abdeckung dabei erweitern.
- [ ] pv-config: `HP_NENN_W` ist gehoben (`heizpatrone.hp_nenn_w`), zusammen mit 4 get_param-Defaults. Übrige Inline-Literale in `geraete.py` (z.B. 0.25-PV-Faktor, 8 kW-Ladelimit) sind bewusste Implementierungs-Koeffizienten und bleiben inline — nur klar operator-relevante Schwellen bei Bedarf nachziehen.

### Tech-Debt (niedrige Prio)

- [ ] ForecastCollector Sunrise/Sunset-Fallback: saisonale Tabelle statt festem 7/17
- [ ] `tier1_checker._check_netz_ueberlast()`: `reduce_power`-Kommando mit explizitem Reduktionswert (proportional)

### Warnungen & Benachrichtigungen

- [ ] Passive Warnungen (Web-Dashboard): Inverter-Ausfall >10 min, Clear-Sky-Abweichung >40%, SOC-Spruenge >20%
- [ ] Forecast-Empfehlung: "Guter Tag morgen → EV-Ladung auf Mittagszeit"
- [ ] Wochenvorschau in Web-Ansicht

### Einspeise-Schutz (Nulleinspeisung) — Nachgang Zwischenfall 2026-07-02

- [ ] **Fronius-Support informieren:** Entwurf `doc/system/FRONIUS_SUPPORT_EINSPEISUNG_2026-07-02.md` prüfen und über Solar.web/Fronius Technical Support senden (Ursache: F3 ignoriert Soft-Limit-Curtailment).
- [ ] **`automation_log`-Persistenz reparieren:** Aktor schreibt nach `data.db`, aber Persist-Sync/Restore überschreibt `data.db` mit RAM-`fronius_data.db` (dort `automation_log` seit 2026-05-29 eingefroren) → Aktor-Inserts verpuffen. Forensik-Lücke; Live-Log läuft nur über `logs/schaltlog.txt`.
- [ ] **Einspeise-Schutz Stufe 2/3 nach Review scharfschalten:** `dumpload_aktiv`/`provokation_aktiv` in `config/soc_param_matrix.json` (Konflikt mit Geräteregeln bzw. AUS-Phase-Risiko vorab bewerten).
- [ ] **Dashboard-Sichtbarkeit:** ObsState-Feld `einspeis_heute_kwh` + Web-Anzeige/EVENT_THRESHOLDS für Einspeisung (aktuell nur Guard-intern + Mail/Log).
- [ ] **Schwellen pflegen:** `einspeise_schutz.netto_warn_kwh`/`netto_akt_kwh` (30-min-Netto) periodisch gegen die rollierende 90-Tage-Verteilung der max Netto-Einspeisung/30 min prüfen (aktuell Normalmax 0,35 kWh, Vorfall 0,75 kWh).

### Task A — WR-Fernsteuerung (Design: `doc/system/WR_FERNSTEUERUNG.md`)

- [ ] **F1-Soft-Standby via SunSpec Model 123 `Conn`** (Disconnect/Connect, update-sicher) evaluieren — Schreibpfad zum GEN24 neu + risikobehaftet (Batterie-WR), erst nach Einzelvalidierung, gated, nie autonom.
- [ ] **F2-Standby via eigenem Modbus (Model 123 `Conn`)** implementieren — F2 hat eigene IP + Modbus TCP:502 + Solar-API (verifiziert 2026-07-02, analog F1). Gated, Einzelvalidierung.
- [x] **F3-Digitalzugang ermittelt** (2026-07-02): eigene IP im LAN, Modbus TCP:502 + Solar-API v1, SunSpec Model 123 `Conn` vorhanden (analog F1/F2). CustomName „F3", DT=111, UID 1029499.
- [ ] **F3-IP in `.infra.local`** (`PV_TERTIARY_INVERTER_API`) + Collector-Monitoring aufnehmen; danach **F3-Standby via eigenem Modbus** (Model 123 `Conn`) implementieren — gated, Einzelvalidierung.
- [ ] **Read-only WR-Link-Health-Check:** Fronius interne Config-API (Soft-Limit=0 W + Multi-WR-Limiting gesetzt?) + Runaway-Frühsignatur (F3 hoch trotz Einspeisung + Batt voll/gedeckelt + F1/F2 abgeregelt) → alarmieren, kein Aktor.
- [ ] **Reset-Sequenz** (F3 aus → F2 aus → F1 Conn-Reset → +3 min F2 → F3) erst nach vorhandener Relais-HW/F3-Zugang implementieren + jeden Schritt einzeln verifizieren.

### Task C — Tagesdaten-Haltbarkeit / STATS-DB (IST: `doc/system/TAGESDATEN_HALTBARKEIT.md`)

- [x] STATS-DB `data_stats.db` + `data_5min_permanent` (`tools/build_stats_db.py`). — 2026-07-02
- [x] Backfill Jan 1 – Jul 2 aus Pi5-Backups (51 692 Buckets). — 2026-07-02
- [x] Tages-Archiv-Cron `scripts/stats_archive_daily.sh` (00:20) + Sync Pi5/Failover. — 2026-07-02
- [x] Web-Tag-Chart STATS-Fallback (`db_utils` ATTACH + `routes/helpers.py:tag_table`). — 2026-07-02
- [ ] Optional: `DATA_1MIN_RETENTION_DAYS` senken (RAM entlasten) — jetzt möglich, bewusst offen gelassen.
- [ ] STATS-DB in die reguläre GFS-Backup-Kette aufnehmen (nicht nur täglicher Direkt-Sync).

### Task Pi4-Failover — Einsatzbereitschaft (Status: `doc/system/FAILOVER_STATUS.md`)

- [ ] **venv offline provisionieren** (Failover hat KEIN Internet) — `.venv` vom Primary klonen (identische HW aarch64/Py3.13.5) + Pfade patchen; danach App-Import verifizieren.
- [ ] `pv-failover-health.service` reparieren (schlug fehl — venv/Script) + Code-Sync (`sync_code_to_peer.sh`) auf aktuellen Stand.

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
