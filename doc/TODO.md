# Zentrale TODO-Liste — PV-System

**Stand:** 2026-05-03  
**Regel:** Alle offenen Aufgaben gehoeren in DIESE Datei. Keine verteilten TODOs in Subdirectories.

---

## Sicherheit & Haertung

### ~~Kritisch: Git-History hart bereinigen~~ ✅ erledigt 2026-05-04

- [x] `git filter-repo --replace-text scripts/filter-expressions.txt --force` auf gesamter History ausgefuehrt
- [x] Verifikation: `./scripts/publish_audit.sh --history` → 0 Treffer (alle 3 Phasen gruen)
- [x] `git push --force origin main` + alle Tags aktualisiert
- [ ] Team-Remediation: frische Klone bzw. `git fetch --all` + `git reset --hard origin/main` auf Pi4-Failover und Pi5-Backup ausfuehren

- [ ] UFW auf Primary (.181) aktivieren — `scripts/safe_ufw_apply.sh`
- [ ] SSH `StrictHostKeyChecking=no` → `accept-new` in sync_code_to_peer.sh, backup_db_gfs.sh, routes/system.py
- [ ] API-Authentifizierung evaluieren (bei Remote-Zugriff)
- [ ] Rate Limiting (`flask-limiter`, 60 req/min/IP)
- [ ] CORS auf Frontend einschraenken (bei Oeffnung)
- [ ] TLS via nginx-Proxy (bei Bedarf)
- [ ] Fehlermeldungen entschaerfen (`str(e)` → generische Antworten)

---

## Automation (Schicht C)

### Kurz: Offene Software-Items

- [ ] `AktorBatterie.verifiziere()` — HTTP-API Read-Back implementieren
- [ ] WP-Automation Phase 2 Stubs in `aktor_wattpilot.py` anbinden (set_strom, pause, resume, set_modus_pv, stoppe_laden)
- [ ] Dashboard-Erweiterung: Automation-Tab in Web-UI
- [ ] HP-Status in tag_view integrieren (flow_view zeigt bereits HP EIN/AUS)
- [ ] RegelHeizpatrone Refactoring: 903 LOC → Phase-Objekte (Wunsch, nicht dringend)

### Architektur (aus Audits 2026-04 / 2026-06 konsolidiert)

- [ ] **ExternalRespectManager** als Singleton-Modul (`automation/engine/external_respect.py`) einfuehren — vereinigt Regel-Veto, SOC-Tracker und Operator-Overrides in einer API (Audit AUT-2026-04, HOCH)
- [ ] HP-, Klima- und Batterie-Respekt-Detection auf `ExternalRespectManager` migrieren (Asymmetrie-Heilung; abhaengig von obigem)
- [ ] Wattpilot externe Pause-Erkennung in `AktorWattpilot.verifiziere()`
- [ ] Batterie-Aktor: Modus-Wechsel-Erkennung (`auto`/`manual`/`hold`) in `verifiziere()`
- [ ] Plugin-faehige Engine: Regel-/Aktor-Registrierung von Hardcode zu JSON-Registry (`engine.py` A1/A2; grosse Investition)
- [ ] Zentrale Modbus-Register-Map extrahieren (aktuell auf collectors/aktoren verteilt)
- [ ] State-Machine fuer HP-Phasen statt If-Kette (6 Phasen, ~1600 LOC)
- [ ] `engine_vorausschau()` Web-API: 9 fehlende Regeln nachtragen (WP-Absenkung, Klimaanlage, WP-Regeln, Heiz-Bedarf) oder Code-Duplikation eliminieren (Audit DEEP-2026-06 K-02)
- [ ] Klimaanlage-Startup-Pruefung: `_hp_startup_check()` auf Fritz!DECT-Geraete erweitern oder `_fritzdect_startup_check()` (K-03)
- [ ] Matrix-Reload klaeren: SIGHUP-Auto-Trigger in pv-config.py ODER Engine pruft mtime periodisch ODER pv-config-Text korrigieren (K-04 — "Wirksam ≤1 Min" stimmt aktuell nicht)
- [ ] pv-config Whiptail-UI: ~40 versteckte Parameter freilegen (Drain-, WP-Soll-, Absenkung-, Klima-Parameter)

### Tech-Debt (Audit-Befunde, niedrige Prio)

- [ ] Phantom-Regelkreis-Referenz `soc_schutz` in `geraete.py` RegelHeizpatrone durch Konstante ersetzen (Matrix-Eintrag existiert nicht mehr seit 2026-03-07)
- [ ] ForecastCollector Sunrise/Sunset-Fallback: saisonale Tabelle statt festem 7/17
- [ ] `data_collector.py`: `_modbus_fail_count` von Class- auf Instance-Attribut
- [ ] `schaltlog.py`: Truncation nicht bei jedem Eintrag (Dateigroessencheck oder N-Eintraege-Intervall)
- [ ] `tier1_checker._check_netz_ueberlast()`: `reduce_power`-Kommando mit explizitem Reduktionswert (proportional)
- [ ] `HP_NENN_W=2000` aus Code in `soc_param_matrix.json` als `hp_nenn_w` (statt Hardcode)
- [ ] `battery_control_log`-Reader in `pv-config.py` und `routes/system.py` entfernen \u2014 Tabelle wird seit 2026-03 nicht mehr beschrieben (keine `INSERT INTO battery_control_log` im Code), Lese-Fallback ist obsolet

### Doku-Konsistenz (Audit-Restposten)

- [ ] `PV_CONFIG_HANDBUCH.md`: alle 31 Regelkreise aufnehmen (aktuell nur 18)
- [ ] `SCHUTZREGELN.md`: SR-EV-01 (NMC-Ueberladeschutz) als "GEPLANT — E-Auto-SOC nicht verfuegbar" kennzeichnen
- [ ] `CHANGELOG.md` v1.3.1 K-04 (Matrix-Auto-Reload): Feature implementieren ODER Eintrag korrigieren

### Mittel: Warnungen & Benachrichtigungen

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
- [ ] Phase 5: WP SG-Ready via Modbus, WW-Solltemp schreiben, Betriebsmodus umschalten
- [ ] Phase 7: 3-Phasen-Heizpatrone (Zukunft)

### Offene Hardware-Fragen

- [ ] F2: Externer WW-Temperatursensor der WP — Typ? NTC 10K? PT1000?
- [ ] F3: WPM-Reglerversion am Geraet pruefen (LCD=WPM_L/H, Touch=WPM_M)
- [ ] F5: Brandschutzklappen-Stellantriebe — Hersteller, Spannung, Rueckmeldekontakt?
- [ ] F5b: Klimaanlage — Schuetz oder IR-Sender?
- [ ] F6: Lueftungsgeraet — Steuerungsmoeglichkeiten (0-10V? Modbus?)
- [ ] F7: Bypass-Ventil — Motor- oder Magnetventil? Spannung?

---

## Steuerbox (Schicht E)

- [ ] Phase 1: API-Grundgeruest (steuerbox_api.py, validators.py, intent_handler.py)
- [ ] Phase 2: Release-1 Schalter (HP, WP, Batterie, Wattpilot, Regelkreis EIN/AUS)
- [ ] Phase 3: Safety Enforcer + D/E-Integration (Respekt-Zeitueberwachung, Heartbeat, 6h-Reset)
- [ ] Phase 4: pv-config Integration (Respekt-Verfahren, Override-Status)
- [ ] Phase 5: Cockpit-UI (optional, spaeter)
- [ ] Querschnitt: Audit-Logging, Rate-Limiting, Failover-Verhalten, Testmatrix

---

## Diagnos (Schicht D)

- [x] Phase 1: Read-only Health-Checks (Freshness, CPU, Unterspannung, Disk) — `diagnos/health.py`, deployed Commit 4168e53 (2026-04-04)
- [x] Phase 2: Datenintegritaet, Aggregations-Invarianten, Parity-Checks — `diagnos/integrity.py`, 9 Checks aktiv
- [x] Mail-Diff-Filter & Subject-Severity-Suffix (2026-04-27) — `automation/engine/diagnos_alert_state.py`
- [x] Health-Sofortpfad (2026-04-29) — CPU-Crit / Disk-Crit / Service-Down / Throttle, 10-min-Takt, persistent dedupliziert
- [x] Sofortalarm-Dedup persistent (2026-04-29) — `config/event_notifier_dedup.json`
- [x] NQ-Mail-Skelett (2026-04-29) — `automation/engine/nq_notifier.py`, ENABLED-Flag, eigener State `config/nq_alert_state.json`
- [ ] Phase 3: Infrastruktur-/IO-Pruefungen (LAN, SSH, API, MEGA-BAS, RS485) — sinnvoll **parallel** zur PAC4200-Inbetriebnahme im Mai
- [ ] Phase 4: Begrenzte Schutzaktionen mit Cooldown (nur falls noetig)
- [ ] Phase 5: Langzeitspeicher Diagnos-Berichte auf Pi5-SSD
- [ ] 3. lauschende Instanz: `failover_health_check.sh` analog auf Pi5-Backup deployen
- [ ] NQ-Aktivierung: `nq_notifier.ENABLED = True` setzen + `automation_daemon` einklinken, sobald PAC4200 produktiv

---

## Betriebsstabilitaet

- [ ] Auffrischungs-Policy: Service-Restart vs. Host-Reboot definieren
- [ ] `pv-restart.timer` Intervall benchmarken (3 vs. 7/14 Tage)
- [ ] Restart-Fenster standardisieren (Geisterstunde, minimales Risiko)
- [ ] Ausfallklassen definieren: Mikro (<2 min), Kurz (2–30 min), Mittel (30 min–6h), Lang (>6h)
- [ ] Post-Restart-Checkliste automatisieren

---

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
