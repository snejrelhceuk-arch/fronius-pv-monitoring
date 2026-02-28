# Offene Aufgaben & Roadmap — Fronius PV-Monitoring

> Letzte Aktualisierung: 2026-02-28

---

## System-Audit 2026-02-27 — Befunde & Fixes

### Umfang
Tiefgreifende Prüfung aller Schichten: Datensammlung (Collector/Modbus), Aggregations-Pipeline
(5 Stufen), Web-API (52 Endpoints), Automations-Engine (9 Regeln, 4-Schichten-Architektur),
Code-Struktur (23.321 Zeilen Python, 58 Module). Gesamtbewertung: **7/10**.

### Behoben (2026-02-27)
P0 (5 Fixes): Actuator.close, _retry() None-Handling, DB-Connection-Leaks,
aggregate.py Error-Handling, RAM-Buffer Flush-Reihenfolge.
P1 (6 Fixes): W_PV_Direct_total Formel, API-Query-Limits, AktorWattpilot Stub,
aggregate_1min Idempotenz, Winner-takes-all Safety, get_db_connection dedupliziert.
→ Details in Git-History + Archiv unten.

### Offen — Für spätere Diskussion
- [ ] **API-Authentifizierung** — Kein Auth im privaten 192.x-Netz. Akzeptables Risiko
      für LAN-only, aber bei Remote-Zugriff (VPN/Port-Forwarding) nachrüsten.
- [ ] **Rate Limiting** — Noch kein DoS-Schutz. `flask-limiter` (60 req/min/IP) evaluieren.
- [ ] **CORS auf Frontend einschränken** — Default `*` für LAN akzeptabel, bei Öffnung anpassen.
- [ ] **TLS** — Unverschlüsselt auf Port 8000; bei Bedarf nginx-Proxy mit Let's Encrypt.
- [ ] **Fehlermeldungen entschärfen** — `str(e)` exponiert Python-Interna; generische Antworten.

### Hochgestuft aus Audit-Neubewertung — Behoben (2026-02-27)

- [x] **P1: `RegelZellausgleich` Zyklustracking** (Befund #8) —
      Fix: `bewerte()` liest jetzt `last_balancing` aus `battery_scheduler_state.json`
      (Fallback: `letzter_ausgleich` aus `battery_control.json`). Wenn Ausgleich im
      laufenden Monat schon stattfand → Score 0. Statische Methode `_letzter_ausgleich()`.
- [x] **P2: `bitfield32` im Modbus-Parser** (Befund #1) —
      Fix: (a) `bitfield32`-Case in `parse_sunspec_value()`: 2 Register → 32-Bit-Wert,
      (b) Register-Length-Berechnung auf `length=2` für `bitfield32` erweitert.
      13 SunSpec-Event-Felder werden jetzt korrekt gelesen.
- [x] **P2: Hardcodierte Default-Daten** (Befund #7) —
      Fix: Alle 5 Stellen auf dynamische Defaults umgestellt:
      `date.today().isoformat()` (3×), `today - 30d` + `today` (daily),
      `1. Jan` + `31. Dez` des laufenden Jahres (monthly).

### Erkenntnisse aus dem Audit — Neubewertung 2026-02-27
| # | Bereich | Befund | Schwere | Status |
|---|---------|--------|---------|--------|
| 1 | Collector | `bitfield32` nicht in `parse_sunspec_value` — 13 Event-Felder in 3 SunSpec-Modellen liefern `None`, Alarm-Sichtbarkeit fehlt komplett. 2-Zeilen-Fix in `modbus_v3.py` | **Mittel** | **✅ Behoben** |
| 2 | Collector | WR-Effizienz 0,97 hardcodiert (1 Stelle `modbus_v3.py:679`); `geometry_config.json` hat bereits 0.96/WR. Differenz 1% | Niedrig | Akzeptiert |
| 3 | Aggregation | Drei verschiedene Batterie-Berechnungen (P×t / I×U×0.25 / BMS) | Info | Bewusst — verschiedene Zwecke |
| 4 | Aggregation | Dual-Pipeline (P×t für Charts, Zähler für Abrechnung) gut begründet | Info | Bewusst — korrekt so |
| 5 | Web-API | 3 Response-Formate (Array / {data,stats} / {datapoints,totals}) | Niedrig | Akzeptiert — kosmetisch |
| 6 | Web-API | Mix Deutsch/Englisch Endpoints | Niedrig | Akzeptiert — kosmetisch |
| 7 | Web-API | Hardcodierte Default-Daten (`2026-01-01`) in 5 Stellen: `routes/data.py` (4×) + `routes/realtime.py` (1×). Fix: `date.today().isoformat()` | **Niedrig→Mittel** | **✅ Behoben** |
| 8 | Automation | `RegelZellausgleich` trackt nicht ob Zyklus durchgeführt — `letzter_ausgleich` wird nie geprüft. An jedem sonnigen Tag wird Vollzyklus ausgelöst statt 1×/Monat. Belastet BYD-Zellen. | **Mittel→Hoch** | **✅ Behoben** |
| 9 | Automation | Observer vs. AutomationDaemon: redundante `_load_schutz_config()`, Datensammlung, Tier-1. `AutomationDaemon` ist die Weiterentwicklung | Niedrig | Beobachten — prüfen ob Observer noch aktiv |
| 10 | Struktur | 6 Dateien >1.000 Zeilen, 15 >500 Zeilen | Mittel | Beobachten → C4 |
| 11 | Struktur | 0% automatisierte Testabdeckung | Mittel | Beobachten → C4 |
| 12 | Struktur | Flask 1.1.2 / NumPy 1.19.5 veraltet — armv7l/Python 3.9 Pin begründet, LAN-only mitigiert Risiko | Mittel | Beobachten — bei Python-Upgrade angehen |

### Forecast-Qualität — Validierung 2026-02-27 (wolkenlos)
Messung in abregelungsfreien Zeitfenstern (einzige korrekte Methode bei wolkenlosem Himmel):

| Zeitfenster | Ist (kWh) | Prognose (kWh) | Abweichung | Highlight |
|-------------|-----------|----------------|------------|-----------|
| 07:00–08:40 | 3.592 | 3.625 | **0.9 %** | 07:30 = 100.9 % Trefferquote (4 Wh daneben) |
| 13:00–14:00 | 12.146 | 12.991 | **6.5 %** | 13:15 = 99.9 % (3 Wh daneben bei 4.3 kWh) |

Atmosphärischer Korrekturfaktor (Prognose/Clearsky): 61–85 % — bildet Aerosole, Luftmasse
und Trübung Ende Februar korrekt ab. Die Prognose-Engine modelliert nicht Wolken, sondern
die reale atmosphärische Durchlässigkeit. Bester Bewertungsansatz: wolkenlose Tage,
**ausschließlich** Zeitfenster ohne Abregelung.

---

## Priorität A — Kurzfristig (nächste Wochen)

### A3: Monatlicher Solarweb-Abgleich
Seit Feb 6, 2026 arbeitet das System mit Zählerstand-Deltas (korrekt).
Davor war P×t-Integration im Einsatz, die ~50% systematisch zu niedrig lag.

**Korrekturverfahren ("Hubble-Konstante für PV"):**
- [x] **Jan 2026 + Feb 1–5**: Solarweb-Korrektur manuell durchgeführt (2026-02-19)
- [x] `aggregate_statistics.py` FIRST_AUTO_MONTH auf `(2026, 1)` gesetzt
- [ ] **Anfang März**: Feb-Abgleich durchführen, FIRST_AUTO_MONTH auf `(2026, 2)` hochsetzen
- [ ] **2022–2025 CSV-Import**: Solarweb-Jahreswerte prüfen (vermutlich korrekt, da Solarweb-Export)
- [ ] Langfristig: Abweichung Richtung 0 beobachten (Zählerstand-Delta = korrekt seit Feb 6)

**Referenz-Workflow (bewährt für Jan+Feb 2026):**
```
1. Solarweb → Monatssummen ablesen (Solar, Bezug, Einsp, Batt, Direkt, Gesamt)
2. monthly_statistics mit Solarweb-Werten überschreiben
3. daily_data: Korrekte Tage (Zählerstand-Delta) identifizieren
4. Restliche Tage: Faktor = (Solarweb - korrekte Tage) / (P×t-Summe der Resttage)
5. UPDATE daily_data SET spalte = spalte * faktor WHERE ts BETWEEN ...
6. yearly_statistics neu berechnen
7. FIRST_AUTO_MONTH in aggregate_statistics.py hochsetzen
```

### A5: Tag-Anzeige — Batterie-Zeile überarbeiten
- [x] Batterie-Daten in Info-Zeile (SOC, SOC_MIN/MAX, Ladestatus, SOH) via `/api/battery_status`
- [x] "Netzladung" und "Reserve" aus tag_view entfernt (API liefert noch, UI zeigt nicht)
- [ ] Override-Buttons in tag_view: [SOC_MIN → 5%] [SOC_MAX → 100%] [Reset]
      *(existieren in flow_view, fehlen in tag_view)*
- [ ] Scheduler-Status in tag_view: nächste geplante Aktion
      *(existiert in flow_view via automation_phasen, fehlt in tag_view)*

### A6: Batterie-Scheduler beobachten
- [x] `battery_scheduler.py` implementiert (Morgen + Nachmittag + Zellausgleich)
- [x] `config/battery_control.json` parametrisiert
- [x] `battery_control_log` DB-Tabelle angelegt + aktiv beschrieben
- [x] Cron-Job alle 15 Min aktiv (seit 2026-02-10) — **abgelöst durch `pv-automation.service` (systemd, seit 2026-02-28)**
- [x] `battery_control.py` + `battery_scheduler.py` importieren `config.py`
      (IP, DB-Pfad); Laufzeit-Parameter weiterhin aus `battery_control.json` (bewusst)
- [ ] Log-Analyse: Schwellen kalibrieren (Daten da, Auswertung fehlt)
- [ ] API-Endpunkt `/api/battery_control` (Design in BATTERY_ALGORITHM.md, nicht implementiert)
- [ ] UI-Buttons in tag_view.html (→ A5)

---

## Priorität B — Mittelfristig

### B0: Solar Geometry Engine — nachhaltig nutzen
`solar_geometry.py` + `solar_forecast.py` = **3.026 Zeilen Engine** (läuft, ~50% genutzt).

*Automation (→ battery_scheduler.py):*
- [x] **Geometry-Prognose statt GHI-Skalierung:** `get_remaining_pv_surplus_kwh()`
      bevorzugt bereits `power_hourly` aus `get_hourly_power_forecast()`. GHI nur Fallback.
- [ ] **Mehrtages-Strategie:** `get_week_forecast()` existiert, wird nur im CLI genutzt →
      z.B. 2-Tages-Vorausschau für Batterie-Management

*Warnungen/Alerting (→ B3 unten):*
- [ ] **Clear-Sky-Abweichung live:** Real vs. Modell → "Produktion 40% unter Erwartung"
      *(Daten in `data_15min.W_PV_CS_delta` vorhanden, Auswertung fehlt)*
- [ ] **String-Vergleich:** Per-String Soll/Ist → F2 fällt ab → automatische Warnung
- [ ] **Hitze-Warnung:** Temperaturkoeffizient ist modelliert → "35°C morgen = 8% weniger"

*Selbst-Optimierung:*
- [x] **Auto-Kalibrierung:** `calibrate(days=90)` — wöchentlicher Cron eingerichtet
      (Sonntag 05:00, `--calibrate-days 90`, Log: `/tmp/solar_calibrate.log`) (2026-02-28)

### B1: Redundantes System (Failover-Pi) — Weitgehend implementiert
3-Host-Architektur dokumentiert in `doc/DUAL_HOST_ARCHITECTURE.md` (2026-02-20).

- [x] **DB-Replikation**: `scripts/failover_sync_db.sh` + `pv-mirror-sync.timer` (alle 10 Min)
- [x] **Failover-Erkennung**: `scripts/failover_health_check.sh` (Ping + API + Sync-Alter)
- [x] **Identische Installation**: `scripts/sync_code_to_peer.sh` (rsync Code + Config)
- [x] **Rollen-Guard**: `host_role.py` → Primary/Failover/Backup, Collector nur auf Primary
- [ ] **Automatische Übernahme**: Failover-Aktivierung noch manuell (bewusste Design-Entscheidung)
- [ ] **Automatischer Rückfall**: Primary → retake nach Recovery (manuell)

### B2: Pi4/SD-Karten-Portabilität — Weitgehend erledigt
tmpfs-Architektur läuft seit 2026-02-12.

- [x] **GFS-Backup**: `scripts/backup_db_gfs.sh` (daily/weekly/monthly/yearly),
      `pv-backup-gfs.timer` + `pv-backup-2d.timer` aktiv, Ziel: `backup/db/` + Pi5 rsync
- [x] **Reboot-Test**: `ensure_tmpfs_db()` in `db_init.py` — Fallback NVMe → Backup,
      aufgerufen von Collector, Web-API, Gunicorn, db_utils
- [x] **DB-Größe**: `monitor_health.sh` warnt bei Überschreitung (aktuell ~150 MB)
- [ ] SD-Karte als zusätzliches Backup-Ziel (`/mnt/sd-karte`) — nicht eingerichtet

### B3: Warnungen & Proaktives Alerting
Die Prognose-Engine liefert die Daten — jetzt fehlt die Auswertung.
*(Komplett offen — keine der drei Stufen ist implementiert)*

**Stufe 1 — Passive Warnungen (Web-Dashboard, kein Push):**
- [ ] Inverter-Ausfall: kein neuer `raw_data` >10min → rotes Banner in Tag-Ansicht
- [ ] Ertrag unter Erwartung: Clear-Sky-Abweichung >40% bei wolkenlosem Wetter → Hinweis
- [ ] Batterie-Anomalie: SOC-Sprünge >20% in einer Messung → Logfile-Warnung

**Stufe 2 — Aktive Benachrichtigungen (Pushover/E-Mail):**
- [ ] Kanal: Pushover (einfachste Integration, ~5 Zeilen Python)
- [ ] Trigger: Inverter offline >30min, Collector gestoppt, DB-Schreibfehler
- [ ] Tageszusammenfassung abends: Ertrag, Autarkie, Auffälligkeiten

**Stufe 3 — Forecast-getriebene Empfehlungen:**
- [ ] "Morgen erwartet: X kWh (schlecht) → Eigenverbrauch priorisieren"
- [ ] "Guter Tag morgen → EV-Ladung auf Mittagszeit verschieben"
- [ ] Wochenvorschau in der Web-Ansicht

### B4: Mirror/Service-Aufräumen
- [x] `scripts/monitor_health.sh:58`: Service-Check auf `pv-collector.service` korrigiert (2026-02-28)
- [x] `doc/SINGLE_INSTANCE_PROTECTION.md`: `modbus-collector` → `pv-collector` + Pfad `Documents` → `Dokumente` korrigiert (2026-02-28)
- [x] `README.md:181`: Pfad `Documents` → `Dokumente` in Troubleshooting korrigiert (2026-02-28)
- [x] `doc/SYSTEM_ARCHITECTURE.md`: `battery_scheduler.py | Cron` → `pv-automation | systemd` korrigiert (2026-02-28)
- [x] `doc/AUTOMATION_ARCHITEKTUR.md`: Phase-0-Text aktualisiert (2026-02-28)
- [x] `doc/BATTERY_ALGORITHM.md`: Implementierungsplan-Status aktualisiert (2026-02-28)

### B5: Heizpatrone (HP) — Prognosegesteuerte Automation via Fritz!DECT
HP (2 kW) wird über Fritz!DECT-Steckdose geschaltet. Ziel: Überschuss-Verwertung
ohne Batterie-Entladung. Forecast-gesteuerte Burst-Strategie (15–30 Min Laufzeit).
→ Detailstrategie dokumentiert in `automation/STRATEGIEN.md` §2.6 (2026-02-28)

- [x] **AktorFritzDECT**: `automation/engine/aktoren/aktor_fritzdect.py` (~365 Z.) —
      Fritz!Box AHA-HTTP-API (SID-Cache 15 Min, Bulk-Query `getdevicelistinfos`,
      setswitchon/off, getswitchstate, get_status, Retry-Logik, Credentials aus .secrets)
- [x] **RegelHeizpatrone**: `automation/engine/engine.py` —
      4-Phasen-Logik (Morgen-Burst, Mittag-Überschuss, Nachmittag-Burst, Abend-Block),
      Trigger=P_Batt (nicht P_PV), nutzt forecast_rest_kwh + rest_h, Burst-Timer,
      Notaus bei Netzbezug/Entladung/Übertemperatur
- [x] **Parametermatrix**: Regelkreis `heizpatrone` in `config/soc_param_matrix.json` —
      17 Parameter (min_ladeleistung, burst_dauer, min_rest_kwh/h, notaus,
      notaus_entladung_hochsoc_w, notaus_soc_schwelle_pct)
- [x] **Registrierung**: `AktorFritzDECT` in `actuator.py` registriert (3 Aktoren:
      batterie, wattpilot, fritzdect)
- [x] **Config**: `config/fritz_config.json` (Fritz!Box-IP, AIN=11657 0535198/SDHeizPatrone),
      Credentials via .secrets (FRITZ_USER/FRITZ_PASSWORD, nicht im JSON)
- [x] **pv-config.py**: Menüpunkt 6 "Heizpatrone (Fritz!DECT)" — Status, Config, Verbindungstest,
      manuell Ein/Aus, Schwellwerte, .secrets-Editor für Credentials
- [x] **SOC-abhängiger Notaus**: Immer aktiv (auch bei aktiv=False), SOC ≥90% toleriert
      bis −1000 W Entladung (konfigurierbar), SOC <90% sofort AUS bei jeder Entladung
- [x] **Fritz!Box-Optimierung**: Bulk-Query (`getdevicelistinfos`) statt Einzelabfragen,
      SID-Cache (15 Min), 60 s Poll-Intervall im Daemon
- [x] **flow_view HP-Zeile**: Live-Status (EIN/AUS + Leistung), 120 s Cache,
      Fritz!Box-XML `present` als Child-Element (nicht Attribut) korrekt geparst
- [x] **Schutzregel-Klassifikation**: Engine `_ist_schutz()` erkennt FritzDECT-Regeln
      mit erhöhtem Score als Schutzregeln (können nicht von Batterie-Regeln blockiert werden)
- [ ] **Status-Anzeige**: HP-Schaltzustand in flow_view (Fritz-API-Abfrage)
      → **Teilweise implementiert**: flow_view zeigt HP EIN/AUS + Leistung (120 s Cache),
      live Fritz!Box-Query in `/api/battery_status`. Noch offen: tag_view Integration.

---

## Priorität C — Langfristig / Nice-to-have

### C1: Amortisation verfeinern
- [x] **Strompreise pro Monat**: `config.STROMTARIFE` tagesgenau + `get_strompreis(year, month)`
      mit tagesgewichtetem Mittel bei Tarifwechseln
- [x] **Einspeisevergütung als Config-Wert**: `config.EINSPEISEVERGUETUNG` (Runtime);
      Import-Tool `tools/import_statistics.py` hat noch Hardcode 0.082 als Default
- [ ] **Batterie-Amortisation**: DB-Spalten existieren (`kosten_batterie_eur`,
      `batterie_amort_prozent`), aber keine Live-Aggregation. Benötigt: separater
      `INVEST_BATTERIE` in config.py + Berechnung in `aggregate_statistics.py`

### C2: Datenexport / Backup
- [x] GFS-Backup auf NVMe + Pi5 rsync *(→ B2, erledigt)*
- [ ] SD-Karte als zusätzliches Backup-Ziel (`/mnt/sd-karte`)
- [ ] Export nach CSV/JSON für externe Analyse
- [ ] Optional: Influx/Grafana-Bridge für erweiterte Auswertungen

### C3: Alerting → **Hochgestuft nach B3** (siehe Priorität B)

### C4: Code-Qualität
- [x] **K7:** `web_api.py` aufgeteilt — nur noch 210 Zeilen App-Factory,
      8 Blueprints in `routes/` (pages, data, realtime, visualization, verbraucher,
      erzeuger, system, forecast)
- [x] **Unit-Tests Basis**: `automation/engine/test_skeleton.py` (977 Zeilen) —
      Tier-1, Engine-Zyklus, Actuator, Param-Matrix, 9 Regelkreise abgedeckt.
      Restliche Module (Aggregation, Routes, Collector) noch ohne Tests.
- [x] **Type-Hints**: Guter Abdeckungsgrad in neueren Modulen (host_role, automation/,
      ollama/). Fehlend in Kern-Modulen: routes/helpers, aggregate_*, modbus_v3, db_utils
- [ ] **Modul-Rename/Split**: Soll-Mapping dokumentiert in `SYSTEM_ARCHITECTURE.md` §9.
      Voraussetzung: CI-Import-Check. Wichtigste Kandidaten:
      `modbus_v3.py` → `collector_modbus.py`, `battery_control.py` → Split (3 Rollen).
      Nicht vor CI-Einführung!
- [ ] Collector als systemd-Service (aktuell nohup + monitor_collector.sh cron)
- [ ] CI: Syntax-Check vor Deployment (aktuell nur Compliance-Checkbox in PR)
- [ ] **Dateigrößen-Audit**: Richtlinie in `SYSTEM_ARCHITECTURE.md` §10.
      Prüfen: `find . -name "*.py" | xargs wc -l | sort -rn | head -15`
      Schwelle: >800 prüfen, >1.200 aktiv splitten.
- [ ] data_15min/hourly_data Lücke vor 04.02. untersuchen

---

## Erledigte Aufgaben (Archiv)

Komprimierte Übersicht — Details in Git-History.

| Datum | Thema | Highlights |
|-------|-------|------------|
| 2026-02-28 | Doc-Bereinigung + Auto-Kalibrierung | `modbus-collector`→`pv-collector` (3 Dateien), `Documents`→`Dokumente` (2 Dateien), SYSTEM_ARCHITECTURE/BATTERY_ALGORITHM/AUTOMATION_ARCHITEKTUR auf pv-automation.service aktualisiert, Solar-Kalibrierung Cron (So 05:00), Forecast-Accuracy-Dashboard verworfen (self-healing), Nachtladung verworfen (Festvertrag 30,3ct), **K9 Dual-Modbus verworfen** (ABC-Policy: Collector=A darf nur lesen, Automation=C darf schreiben — getrennte Clients sind bewusste Schichtentrennung, Code-Duplikation hier erforderlich) |
| 2026-02-13 | Flow-View Enhancements + Bugfixes | Gauge-Arcs 360° (PV/Netz/SOC), Responsive Mobile, Aktivitätslevel-Farben, **WP-Vorzeichen-Bug** (`P_WP` negiert), Strompreise korrigiert, Heizkosten-Logik, SOH-Fix, Code-Bereinigung (10 Dateien), pgrep-Pattern-Fix |
| 2026-02-12 | tmpfs-Architektur + Energieflow | DB→`/dev/shm` (RAM), 3→1 Schicht, `db_init.py`, 8 Dateien migriert, 0.04 GB/d I/O, SVG-Energieflow-Chart mit Partikeln |
| 2026-02-11 | Wattpilot + Bugfixes | Wattpilot WebSocket-API, f_Netz Chart-Bug (`category`→`time`) |
| 2026-02-10 | System-Audit v4.0.0 + K1–K11 | Bewertung 7.0/10, `db_utils.py`, bare-except→Exception, config.py zentralisiert, ChaSt-Bug, Service-Crash-Loops behoben |
| 2026-02-08 | Pipeline + Solarweb-Abgleich | Audit 6.5/10, modbus_v3 1956→880 Zeilen, Aggregation-Pipeline, Solarweb-Datenkorrektur (Jan+Feb 2026), config.py erstellt |
