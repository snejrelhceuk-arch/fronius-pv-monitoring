# Zentrale TODO-Liste — PV-System

**Stand:** 2026-10-24  
**Regel:** Alle offenen Aufgaben gehoeren in DIESE Datei. Keine verteilten TODOs in Subdirectories. Ausschliesslich offene `- [ ]` ToDos — keine Audit-/Entwicklungsnotizen.

---

## Sicherheit & Haertung

- [ ] API-Authentifizierung evaluieren (bei Remote-Zugriff)
- [ ] Rate Limiting (`flask-limiter`, 60 req/min/IP)
- [ ] CORS auf Frontend einschraenken (bei Oeffnung)
- [ ] TLS via nginx-Proxy (bei Bedarf)
- [ ] Fehlermeldungen entschaerfen (`str(e)` → generische Antworten)

---

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

## Architektur-Haertung

- [ ] P3: Hotspot-Dateien nur risikogetrieben zerlegen; vor Aenderungen an grossen Regel-/Routenmodulen passende Charakterisierungstests ergaenzen.

---

## Backup / Datensicherung

- [ ] Täglicher Primary↔FB-Wechsel der `data.db`-Persistierung (SD-Schreibpause je 1 Tag pro Karte) — Design steht (s. `doc/system/BACKUP_STRATEGY.md`), noch nicht umgesetzt; aktuell erzeugt der FB das `data.db`-GFS aus seinem tmpfs-Mirror.
- [ ] Weekly-Stufe zusätzlich zur Küche spiegeln — erst mit größerer SD-Karte tragfähig (29-GB-Karte: weekly ~11,8 GB/Jahr füllt sie in ~1,2 Jahren). Bei Kartentausch: `TIERS=(weekly monthly yearly)` in `scripts/backup_longterm_offload.sh` + Weekly-Retention auf der Küche prüfen.
- [ ] `doc/system/DUAL_HOST_ARCHITECTURE.md` §7 an IST angleichen: `backup_db_gfs.sh` läuft auf dem **FB** (nicht Primary), Header-Kommentar im Skript ist pre-REFORMATION.
- [ ] Kontrollierter Code-Resync FB (Repo-Stand Feb 2026) und Küche (Juli 2026) auf Primary-Stand — betrifft u. a. veraltete Service-Skripte; Failover-Dienste vor/nach Sync prüfen.
