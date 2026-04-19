# Zentrale TODO-Liste — PV-System

**Stand:** 2026-04-19  
**Regel:** Alle offenen Aufgaben gehoeren in DIESE Datei. Keine verteilten TODOs in Subdirectories.

---

## Sicherheit & Haertung

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

- [ ] Phase 1: Read-only Health-Checks (Freshness, CPU, Unterspannung, Disk)
- [ ] Phase 2: Datenintegritaet, Aggregations-Invarianten, Parity-Checks
- [ ] Phase 3: Infrastruktur-/IO-Pruefungen (LAN, SSH, API, MEGA-BAS, RS485)
- [ ] Phase 4: Begrenzte Schutzaktionen mit Cooldown (nur falls noetig)

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
