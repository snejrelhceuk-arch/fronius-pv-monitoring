# Zentrale TODO-Liste — PV-System

**Stand:** 2026-09-29  
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
Ist die Größe der DB im RAM wirklich konstant, wenn doch jeden Tag neue Daten dazukommen und permanent bleiben sollen? Deine Umsetzung der Struktur der Datenablage ist nicht konsequent. Wie wächst die Datenbank im RAM, wenn jeden Tag ein Satz neuer Daten dazukommt? Wäre nicht die von mir vorgeschlagene Struktur der Datenhaltung besser: (1) Konstant große Datenbank im RAM durch konsequentes Abschneiden nach bekannter Intervalldauer aus AGGREGATION_PIPELINE. ABER hier müssen noch immer je 5 Tage in die Zukunft hinein gespeichert werden - für die Abbildung der Prognosen! (2) Monitoring-Datenbank mit Speicherung der bekannten Größen im 5min-Intervall für die ewige Tag-Ansicht. Dennoch Korrektur der weiteren abgeleiteten Daten durch Zähler-System. (3) Statistik-Datenbank mit Tages-Intervall zur dauerhaften Speicherung der bekannten Größen für den Bereich Analyse im pv-system. 
Fazit: Eine Überarbeitung der Aggregationen ist nicht zu vermeiden. Erarbeite und teste parallel zum Produktionssystem! Stelle bei Erfolg um. Wir müssen also das Herz des pv-systems komplett überprüfen und systematisch, sehr sorgfältig überarbeiten, um den Erfordernissen gerecht zu werden. Überprüfe also alle Tabellen, alls Spalten, wo sie hingehören. RAM ist eine begrenzte Ressource, daher sollte die Größe der RAM-DB definiert konstant bleiben. Schreibzugriffe auf SD-Karten müssen minimiert bleiben. Wir haben schon die stündliche Persistierung - die wollte ich eigentlich nicht, aber die erhöht die Datensicherheit, ok, können wir beibehalten. Die daraus abgeleitete Monitoring-Datenbank kann täglich einmal aktualisiert werden. Das erhöht auch die Redundanz, da 90 Tage im RAM liegen. Vielleicht kann man das GFS für die RAM-DB noch entspannen, Intervall auf Monat verlängern? Die API entnimmt aus der RAM-DB dann nur noch die aktuellen Daten des laufenden Tages, sowie die Prognose-Daten der zukünftigen 5 Tage. Alle vergangenen UND (bezüglich Clearsky-Darstellung) zukünftigen Daten werden aus der (2) Monitoring-DB gelesen. Daten für die Analyse werden aus (3) Analyse-DB gelesen.

Also, dass heute, 18.10.26, 12:45 Uhr die HP eingeschaltet war, müssen wir unbedingt nochmal überarbeiten - die Prognose und der Akkustand hätten das verhindern müssen! Prüfen der Bedingungsgefüge für Prognose, Uhrzeit, SOC, auch Jahreszeit bzw. Tageslänge könnten einbezogen werden, dass soetwas nicht wieder passieren kann. Es hat ja nichts mit sommerlichem Morgen-Drain zu tun!

Balkenanzeigen in allen Ansichten des Monitoring/Lasten mit grünem Dreieck seitlich am Balken als Marker für die Erzeugung des Tages/Monats/Jahres!
Tooltipps auf allen Balken sollen die Gesamt-Erzeugung neben Gesamtverbrauch bzgl Intervall anzeigen!

Analyse -> Haushalt zeigt 37198€ Vorteil/Ersparnis
Analyse -> Amortisation dagegen zeigt 24686€ Ersparnis, daher erst 2030 fertig.
Hier müssen wir nochmal genauer hinschauen. Die jährlichen Einsparungen sind nicht exakt abgebildet, da wir den Einbau der Wohnung im Dachboden und den Mehrverbrauch durch 2 Erwachsene nicht abgebildet haben. Sicher kann man nicht einfach im Dreisatz hochrechnen, aber es müssen 60m² Wohnfläche im Dach (große Außenflächen) beheizt werden. Der Stromverbrauch aktiver PC-Nutzer, sowie für Kochen, Licht und Fernseher haben wir übersehen. Das E-Auto ist schon mit drin - das ist der Citroen.
Oktober 2024 sind die 2 Personen eingezogen.
