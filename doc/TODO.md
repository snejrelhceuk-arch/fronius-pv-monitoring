# Zentrale TODO-Liste — PV-System

**Stand:** 2026-10-18  
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

## Datenhaltung: 3-Stufen-Umbau (parallel, Cutover bei Erfolg)

Ziel: RAM-DB wirklich **konstant** (nur rollierende Hot-Tabellen 90 T + Prognose
+5 T); permanente Daten in zwei SD-DBs. Entscheidungen: zwei Dateien
(`monitoring.db` + `analysis.db`), RAM-Retention 90 T (Redundanz), RAM-GFS auf
Monat entspannen. Platzierungs-Manifest: `tools/build_tiered_dbs.py`.

- [x] Stage 1: Parallele SD-DBs `monitoring.db` (5-min) + `analysis.db` (Tag)
      aufgebaut + Wert-/Zeilen-Äquivalenz verifiziert.
      (`tools/build_tiered_dbs.py`, `config.MONITORING_DB_PATH`/`ANALYSIS_DB_PATH`)
- [x] Stage 2: Schatten-Writer — `scripts/sync_tiered_daily.sh` (Cron `35 0`) pflegt
      monitoring.db + analysis.db täglich (inkrement. Upsert bewahrt Historie).
- [x] Stage 3: API-Read-Routing via Shadow-Views (`config.TIERED_READS`,
      `db_utils._attach_tiered_ro`): volle Historie aus analysis.db, laufender Tag
      aus RAM; 5-min aus monitoring.db (`stats`-Alias = monitoring.db).
- [x] Stage 4: Cutover — RAM-Retention der permanenten Tabellen auf 120 T
      (`collector/poller.py:_cleanup_tiered`, korrelierter Delete); RAM-GFS auf Monat;
      GFS-Backup beider SD-DBs (`scripts/backup_tiered_dbs_gfs.sh`); Cron/Docs/Cards.
      Rollback: `config.TIERED_READS=False` + Snapshot `backup/pre_tiered_*`/Pi5.

## User
Tiefgreifendes Audit der Datenerfassung und Aggregation in den neuen 3 Datenablagen RAM/monitoring.db/analysis.db!
