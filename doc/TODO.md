# Zentrale TODO-Liste — PV-System

**Stand:** 2026-11-01  
**Regel:** Alle offenen Aufgaben gehoeren in DIESE Datei. Keine verteilten TODOs in Subdirectories. Ausschliesslich offene `- [ ]` ToDos — keine Audit-/Entwicklungsnotizen.

---

## Monitoring & Messkette

- [ ] **Erzeugungsview: Zwangsnachladung sichtbar machen** — `P_inBatt_Grid` als separate Kategorie „Netzladen/Schutzladung" im Tag-Ansicht-Chart einblenden. Daten liegen fertig in `data_1min.P_inBatt_Grid`. Farblich von PV-Ladung abheben.
- [ ] **Stichproben-Alarm SM-LCD vs. DB** — monatlicher Vergleich enwitec-LCD-Ablesung gegen `raw_data.W_Imp_Netz` zum selben Zeitstempel; Alarm bei Δ > 1 kWh.
- [ ] **Stichproben-Alarm Dimplex WP-Zähler vs. DB** — periodischer Vergleich Dimplex-kumulativ gegen `SUM(energy_wh) FROM heizpatrone_daily` ab Startdatum; Alarm bei Δ > 5 %. Startdatum festzulegen sobald DB-Gegenwert belastbar.
- [ ] **PAC-Abweichungsdarstellung gewichten** — in der NQ-Energievergleichs-Ansicht Abweichungen bei kleinen Energiedurchsätzen (< 50 kWh Periode) visuell dämpfen (Graustufe / reduzierte Opazität oder Tooltip-Hinweis), damit systembedingte hohe %-Abweichungen bei kleinen Einspeisemengen nicht beunruhigen.
- [ ] **Tages-CSV-Export** `tools/export_daily_csv.py` anlegen: exportiert `daily_data` als tagegenaue CSV für das gesamte System-Lebensalter. Felder: date, pv, bezug, einsp, batt_in, batt_out, verbr, direktverbr, wp, wattpilot. Manuell oder jährlich automatisiert. Ziel: `doc/csv/daily_YYYY.csv`.

---

## Wärmepumpe COP/SCOP (geplant)

- [ ] **Thermische Erfassung WP** — Vorlauf-/Rücklauf-Temperatursensor (Typ klären: F2-Frage, s. Hardware-Abschnitt). Voraussetzung für COP-Berechnung. Abhängig von MEGA-BAS-HAT Phase 1.
- [ ] **COP-Tracking (24h)** — nach Thermosensor-Integration: COP = Q_th / P_el im 24h-Fenster. Q_th aus (T_VL − T_RL) × Volumenstrom. P_el aus `heizpatrone_daily.energy_wh`.
- [ ] **SCOP (12 Monate rollierend)** — Seasonal COP über gleitende 12-Monats-Summe.
- [ ] **Anzeige in Flow → Maschinenraum → WP** — COP (24h) und SCOP (12 Monate) tagesaktuell. Referenz: Nenn-COP laut Datenblatt Dimplex SIK 11 TES (A7/W35).

---

## Solarweb-Abkopplung (Deadline 26.11.2026)

- [ ] **Solarweb November 2026 sichern** — nach Monatswechsel: `python3 scripts/fetch_solarweb_daily.py --year 2026 --month 11`
- [ ] **Solarweb Jahressummen 2026 sichern** — Januar 2027 (falls noch zugänglich): `solarweb_yearly_2021-26_working.csv` aktualisieren
- [ ] **Solarweb-Credentials aus `.secrets` entfernen** — nach abgeschlossener Sicherung und nach dem 26.11.2026
- [ ] **Abgleich-Matrix Nov 2026** (`abgleich_2026-11_daily_vs_pvsystem.csv`) nach Monatswechsel

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

## Failover (Pi5-FB → Primary)

- [ ] Optionales `scripts/failover_promote.sh`: bündelt Stufe 1+2 inkl. `pv-automation`-Start zu einem Kommando (Runbook in `doc/system/FAILOVER_STATUS.md`). Bewusst ungetestet lassen, da echter Promotion-Test Datenverlust riskiert.
- [ ] `data_stats.db` in den Mirror-/Backup-Fluss aufnehmen (aktuell nur täglicher Direkt-Sync via `scripts/stats_archive_daily.sh`).
