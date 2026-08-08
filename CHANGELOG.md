# Changelog — PV-System Erlau

Alle wesentlichen Änderungen am System, chronologisch absteigend.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/).

---

## [2.0.0] - 2026-08-08

### Changed
- **Web-UI: Deutsches Zahlenformat für alle Analyse-Seiten (2026-08-08):** Alle Analyse-Seiten (`/analyse/pv`, `/analyse/haushalt`, `/analyse/amortisation`) verwenden jetzt einheitlich deutsches Zahlenformat (Punkt als Tausendertrennzeichen, Komma als Dezimaltrennzeichen). Beispiele: `60.382` kWh statt `60,382`, `1.799,1` kWh statt `1,799.1`, `16,3` MWh statt `16.3`. Betrifft alle Summary Cards, Tabellen (PV-Kennzahlen, Strompreise, Haushalt-Kennzahlen, Amortisation) und Investitionsübersichten. Template-Formatierung via `.replace(",", "X").replace(".", ",").replace("X", ".")` für Jinja2-Kompatibilität. (`templates/analyse_pv_view.html`, `templates/analyse_haushalt_view.html`, `templates/analyse_amortisation_view.html`)

- **Web-UI: PV-Übersicht mit Bestenliste & Extremwerte-Tabellen (2026-08-08):** `/analyse/pv` komplett umgebaut: Netzfrequenz-Zeile entfernt, „seit 2022" → „seit 2021" korrigiert. Alte Grenzwerte-Tabelle ersetzt durch zwei neue Tabellen: **„Bestenliste"** zeigt monatliche Ertragswerte über alle Jahre mit Top-3-Medaillen-Färbung (Gold fett Platz 1, Weiß fett Platz 2, Bronze Platz 3, Rest dunkelgrau #666), Jahre zentriert mit Gesamtertrag in Klammern (z.B. „2025 (16,3 MWh)"). **„Extremwerte Spannung und Frequenz"** zeigt monatliche P_max, U_min/max, f_min/max pro Jahr mit Top-3-Farbcodierung pro Metrik (nur Schriftfarbe: Rot/Rosa für P_max, Blau/Hellblau für U_max, Türkis für U_min, Violett für f_max, Lila für f_min). Neue Backend-Helfer `_get_monthly_yield_bestenliste()` und `_get_monthly_extremwerte()` in `routes/pages.py` mit vorberechneten Rankings. Template mit CSS-Inline-Styling für Rank-Klassen. (`routes/pages.py`, `templates/analyse_pv_view.html`, `doc/llm/cards/web-display-api.card.md`)

- **Ticker 2. Zeile: Erklaerungsmodell qwen2.5:7b → gemma2:9b (2026-07-27):** Die KI-Erklaerungen der zweiten Tickerzeile (`tools/ticker_service/ticker_server.py`) nutzen jetzt **`gemma2:9b`** (Q4_K_M, ~5.4 GB) statt `qwen2.5:7b` — natuerlicheres Deutsch (weniger Schlagzeilen-Echo) bei gleicher RTX-3070-Tauglichkeit (8 GB VRAM; ~1.5 s warm, ~30 s Kaltstart < 90-s-Timeout). Reine Konfiguration, kein Code-Change: Modell auf dem Ollama-Host per `POST /api/pull` gezogen; massgebliche Env-Var `TICKER_EXPLAIN_MODEL` in der systemd-Drop-in auf dem Ticker-Host (`config/systemd/pv-ticker.override.conf`, jetzt gitignored wegen realer Host-IP) plus `.infra.local`-Referenz auf gemma2:9b gesetzt; `TICKER_EXPLAIN_MODEL_FALLBACK` identisch. Doku: `tools/ticker_service/README.md`. Resilienz-Fallback auf RSS-Details unveraendert.
- **NQ-Maschinenraum: 5-min-Tagesansicht + 10-s-Hochauflösung (2026-07-25):** Die NQ-Einzelwertansicht (`/maschinenraum?db=nq`) zeigt initial wieder den **vollständigen** Tag im 5-min-Raster — `nq/tech_read.py:fetch_agg` mergt jetzt die Primary-Historie (`nq/db/nq_YYYY-MM.db:nq_5min`) mit Techs jüngstem, noch nicht transferiertem Live-Rand (`source=nq_5min_merged`), statt nur Techs nach Transfer geleertes `nq_5min` zu lesen (vorher nur ~2 h). Neuer **10-s-Schalter** (nur „Jetzt"/heute; gestern nur vormittags): `nq/tech_read.py:fetch_agg_fast` aggregiert `nq_raw_fast`/`nq_raw_medium` aus Techs RAM (~letzte 12 h) zu 10-s-Buckets und blendet sie über den 5-min-Tagesraster (ältere Buckets aus Primary), zoombar; Rück-Navigation deaktiviert 10 s. Analog zur 3-s-Umschaltung der Kern-DB. `routes/pac4200.py:api_nq_realtime_smart` erlaubt `resolution<300`. Netzkriterien-Quelle bestätigt: `/api/nq/netzkriterien` liest die PAC4200-NQ-DB (`fetch_aggregates`, `source=nq_primary_agg`).
- **NQ Analysen: 4h-Fenster für HF/NF (2026-07-16):** Refactor `nq/analysis/nq_events.py` für Dual-Modus: neue `analyze_window(ts_start, ts_end, bands=[...])` für Fenster-basierte Analysen, alte `analyze_day(day)` als Backward-Compat-Wrapper. CLI erweitert: `--hours N --bands HF_local,NF_global` für 4h-Läufe, `--date YYYY-MM-DD --bands VLF` für tägliche VLF. Systemd-Restructuring: `pv-nq-analysis.service` → **nur VLF täglich 00:30** (Vortag), neue `pv-nq-analysis-hf-nf.service` → **HF/NF alle 4h** (00:30, 04:30, ..., 20:30, aktuelle Daten). Upsert-Logik: Duplikat-Key = Trigger + Stunden-Bucket (INSERT OR REPLACE idempotent). **Lokale Spannungsschwankungen-Filterung via Impedanz (Z=299 mΩ) + ΔU-Residual bereits implementiert** — Transientendaten (min/avg/max Sprünge, Anstiegsgeschwindigkeit, Phasen-Klassifikation) in `nq_transient_5min` beim Tech-Collector erfasst, von Transfer in Primary übernommen. Bänder-Klassifikation: origin='lokal' (Pearson(ΔI,ΔU)>0.7) | 'netzseitig' (r<0.2) | 'unklar'. Vorteil: HF/NF-Events alle 4h statt täglich verfügbar, Live-Netzqualität-Überwachung aktiviert.
- **REFORMATION — Produktion auf Pi5 (2026-07-11):** [gekürzt für Übersicht; siehe HEAD~2]

### Fixes
- **Schaltlog-Encoding + Flow-Infozeilen (2026-07-25):** Unter der systemd-Locale `LANG=de_DE` (= latin-1) scheiterte jeder `logs/schaltlog.txt`-Eintrag mit `→`/Nicht-latin-1-Zeichen (`UnicodeEncodeError`) — dadurch fehlten SOC-/HP-/Klima-Schaltungen komplett in den Flow-Infozeilen (SOC-Gründe enthalten fast immer `→`, z. B. „SOC_MAX 75 → 100 %"). `automation/engine/schaltlog.py` schreibt/liest jetzt explizit `encoding='utf-8'`; Bestandsdatei einmalig latin-1→utf-8 konvertiert; Leser `routes/system/battery.py:_fetch_hp_status` liest utf-8 (`errors='replace'`). Zusätzlich: Anzeige-Sammelfenster der Infozeilen 24 h→14 Tage (seltene SOC-Schaltungen sichtbar), Datum-Prefix für ältere Einträge, Labels „Batt/HP/Klima"; dynamische Fit-Strategie (so viele letzte Schaltvorgänge wie ins Fenster passen) unverändert.
- **Wattpilot Flex Local-Auth (2026-05-27):** Authentifizierung auf Hash-Negotiation über `authRequired.hash` umgestellt. Für Flex (`hash=bcrypt`) wird bcrypt-basierte Passwort-Ableitung genutzt, für ältere Geräte weiterhin `pbkdf2`. Betrifft `wattpilot_api.py` (Read + setValue) und `tools/wattpilot_read.py`.

- **HP-AUS Energie-Integral statt Forecast/Winter-Vetos (2026-05-16):** Vorfall an diesem Tag — HP lief 04:16–08:03 (≈ 3 h) mit sustained Netzbezug (>3 kWh) im Drain-Modus, weil das alte `_netzbezug_notaus_ausloesen` ein Forecast-Rest-Veto („gute Prognose holt's nach") besaß, das Netzbezug tolerierte. Neue Logik: HP ist Überschuss-Verbraucher und darf grundsätzlich keinen Netzbezug verursachen; nur kurze Schaltverluste durch Lastwechsel/Erzeugungsschwankungen werden geduldet. Messung über Energie-Integral des positiven Netzbezugs über 5 Min (Engine-Tick 60 s, 5 Samples): ≥ 0.02 kWh ≡ Ø 240 W → HP AUS. Veto nur bei aktuellem Bezug < 200 W. Forecast-Vetos, Winter-Schutz-Veto, Transient-Fenster-Veto und Drain-spezifische Netzbezug-Schwelle entfernt. Winter-Tiefentladung ist weiterhin über dynamisches SOC_MIN-Sliding (5–25 %) und die HART-Schwellen `stop_entladung_unter`/`extern_aus_soc_pct` abgesichert.
- **Terminologie Notaus → AUS (HP-Kontext):** „Notaus" ist reserviert für menschen-/spannungsbezogene Schutzkontexte (BYD-BMS, Tier-1-Alarm). Im HP-Kontext: `notaus_grund`→`aus_grund`, `notaus_ausloesen`→`aus_ausloesen`, `extern_notaus_soc_pct`→`extern_aus_soc_pct`, Drain-Notaus→Drain-AUS, Notaus-Pfad→AUS-Pfad, Notaus-Kriterien→AUS-Kriterien. Doku (PV_CONFIG_HANDBUCH, HP_TOGGLE_OVERRIDE_FLOW, Card automation-regel-heizpatrone) konsistent nachgezogen.

### Removed
- **Matrix-Parameter (Regelkreis `heizpatrone`):** `notaus_netzbezug_w`, `notaus_netzbezug_aktuell_veto_w`, `notaus_forecast_sicherheit_kwh`, `notaus_forecast_haushalt_min_w`, `notaus_forecast_batt_ziel_soc_pct`, `notaus_forecast_batt_ignore_ab_soc_pct`, `notaus_forecast_klima_last_w`, `notaus_forecast_klima_plan_h`, `notaus_drain_netzbezug_w`, `notaus_winter_schutz_soc_pct`, `notaus_transient_aktiv_ab_h`, `notaus_transient_einspeisung_w`, `notaus_transient_fenster_zyklen` ersatzlos entfernt; ersetzt durch `aus_netzbezug_energie_kwh` (0.02 kWh), `aus_netzbezug_fenster_min` (5 min), `aus_netzbezug_aktuell_veto_w` (200 W). Rename: `extern_notaus_soc_pct` → `extern_aus_soc_pct`.

### UI
- **Flow-Ansicht:** Datum/Uhrzeit höher gesetzt (mittig zwischen F1- und Netz-Bubble); Prognose-Symbol weiter nach rechts oben verschoben, damit Abstand zur PV-Gesamt-Bubble entsteht.
- **NQ-Ansicht (Extrema-Marker):** Mouseover-Tooltip zeigt Wert + exakte Zeit; Min-Marker zusätzlich zu Max für Spannung **und** Frequenz. Backend `/api/netzqualitaet/maxima` liefert dafür `u_voltage_min` und `f_netz_min` (inkl. Zeitstempel) über alle vier Aggregationsstufen.

---

## v1.4.0 — 2026-06-20

### Features
- **Einheitliche Perioden-Extremwerte (`GET /api/period_extremes`):** Neuer read-only Endpoint (`routes/visualization.py`) liefert für `period=tag|monat|jahr|gesamt` konsistente Extremwerte (Peak-Leistung, größter/kleinster Ertrag, Netzspannung L-L, Netzfrequenz, cos φ) inkl. Datum/Uhrzeit. Geteilter Frontend-Formatter `static/js/extremes.js` bindet sie in Monitoring- und Analyse-Tooltips (Tag/Monat/Jahr/Gesamt) sowie die Statistik-Tabelle ein — konsistente Gleichschaltung gleicher Größen über alle Ansichten.
- **Leistungsfaktor-Aggregation:** `data_1min` führt jetzt `PF_Netz`/`PF_Inv` als avg/min/max mit (`collector/aggregate/min1.py`, Schema/Migration). cos φ damit über den Tag-Tooltip auswertbar.
- **Seiten-Schublade + Kalender-Navigation:** Neue ausklappbare Seitennavigation links (`static/js/nav-ui.js` + `static/css/nav-ui.css`); Zeit-Navigation bleibt oben. Datum-Labels öffnen einen Kalender (Tag/Monat/Jahr = Tageswahl, Gesamt = Monatswahl). Auf kleinen/Querformat-Displays ersetzt die Schublade die Inline-Links (Desktop unverändert).

### Fixes
- **Peak-Leistung Monat/Jahr/Gesamt korrigiert:** Bisher wurde `P_AC_Inv_max` (nur F1-Wechselrichter, HW-Limit ~12 kW) als System-Peak gezeigt. Neu: `daily_data.P_PV_total_max` = zeitgleicher Anlagen-Peak (DC1+DC2+F2+F3) aus data_1min (`collector/aggregate/daily.py`, Schema/Migration, Bestandsdaten gebackfillt).

### UI
- **Tooltips/Statistik:** Netzspannung/Frequenz/cos φ jetzt mit Datum/Uhrzeit; Extremwert-Zitate ohne Prozentvergleich („Größter/Kleinster Ertrag … im Monat"). Peak-Marker im Tag-Chart mit weißem Label-Hintergrund. Balkendiagramme ohne Hover-Ausblendung und ohne Einblend-Animation. Keine gemischten bunten/grauen Icons mehr in den Extremwert-Zeilen. Verbraucher-Legende um Klima/Gefriertruhe/Lüftung ergänzt.
- **Primärenergie:** Aktualitätshinweis mit Datenstand und Verfallstimer (3 Monate); Marker am Menüpunkt, wenn die manuell gepflegte Seite veraltet ist.

### Diagnos
- **RAW-Datenlücken verfallen in der Mail:** `integrity:gaps:raw_data` wird in der Sunset-Mail auf max. `warn` gedeckelt, einmal gemeldet und danach unterdrückt (kein 7-Tage-Reminder); Lücken bleiben in der Ausfallaufstellung sichtbar (`automation/engine/diagnos_alert_state.py`).
- **Daylight-aware Gap-Scan:** Lücken bei Dunkelheit/Dämmerung (WR-Standby am Tagesende) treiben die Alarmschwere nicht mehr, bleiben aber gelistet (`diagnos/integrity.py`, `solar_geometry.sun_position`).

---

## v1.3.5 — 2026-05-03

### Features
- **Klima Extern-Erkennung:** Manuelles Einschalten der Klimaanlage wird für `extern_respekt_s` (Standard 30 Min) respektiert. Zustandsbasierte Erkennung (OFF→ON ohne Engine-Beteiligung), analog zum HP-Muster. Während Respekt-Zeit greift nur die harte Sicherheit (Sunset+SOC).
- **Batterie-Zelltemperaturen:** BYD-Zelltemperaturen (min/max/avg) via HTTP in DataCollector integriert (30 s Rate-Limit).
- **Steuerbox Tages-Intent `afternoon_charge_request`:** Einmal-Trigger setzt einen Nachmittags-Ladewunsch bis Sunset. `respekt_s` wird serverseitig aus Sunset abgeleitet (Fallback 17:00) und als Policy-Hold geführt.
- **SOC/HP-Kooperation für Ladewunsch:** `RegelNachmittagSocMax` priorisiert bei aktivem Tages-Intent das Ziel `SOC_MAX=100` im adaptiven Startfenster 12–15 Uhr; `RegelHeizpatrone` pausiert HP bis Ziel-SOC erreicht ist.
- **HA-Read/Discovery ausgebaut:** Endpunkte `/api/ha/automation`, `/api/ha/device`, `/api/ha/entities` ergänzen `/api/ha/flow` und `/api/ha/wattpilot` für konsistente Geräte-/Entitätsabbildung.
- **HA MQTT Telemetrie-Bridge (read-only):** Adapter publiziert MQTT Discovery/State aus `/api/ha/*` (inkl. Wattpilot-Status, Session-/Gesamtenergie, Online/Alter/FRC), ohne Schreibpfad zur Steuerbox.

### Fixes
- **Klima Rapid-Shutdown behoben:** `RegelKlimaanlage` berücksichtigt Extern-Erkennung korrekt; sofortiges Zurückschalten nach manuellem EIN entfällt.
- **Verbrauchsformel Tageskopf (counter_totals):** Formel auf `ac_gesamt + bezug - einspeis` umgestellt; Batterieentladung wird im Tagesverbrauch korrekt berücksichtigt.
- **Steuerbox-Audit Stabilität:** Fehlender `time`-Import für Audit-Timestamp korrigiert.

### Operations / Infra
- **Steuerbox-Monitoring:** `pv-steuerbox.service` in zentrale Überwachung integriert (inkl. Keepalive-Checks).
- **Failover-Sync gehärtet:** `.state`-Initialisierung via Boot-Service und robusteres Error-Logging.
- **Safe Terminal Workflow:** `scripts/terminal_safe_run.sh` als zentraler Guard für Prompt-/Interaktiv-/Timeout-Sicherheit.
- **Pi5-Workspace-Backup:** `scripts/backup_workspace_pi5.sh` für datierte Snapshot-Archive ergänzt.

### Docs / Internal
- **LLM-Dokumentationssystem eingeführt:** `AGENTS.md`, `doc/llm/INDEX.md`, Domain-Cards, Drift-Engine und Pre-Commit-Doc-Check.
- **HA-Integrationsdokumentation ergänzt:** `doc/web/HA_INTEGRATION.md` mit Read-only-Migrationspfad für HA.
- **Audit-Altlasten bereinigt:** veraltete Deep-Audit-Dokumente entfernt/archiviert, Doku-Struktur konsolidiert.

---

## v1.3.4 — 2026-04-29

### Mail-Pfad — Sofortalarme komplettiert + NQ-Skelett

**(a) Health-Sofortpfad** ([automation/engine/event_notifier.py](automation/engine/event_notifier.py))
- Neu: `EventNotifier.pruefe_health_alarme()` — analoger 10-min-Slot zu
  `pruefe_integrity_alarme()`. Reagiert auf severity ∈ {crit, fail} bei:
  - `cpu_temp` (Hardware-Überhitzung)
  - `throttle` (Pi-Unterspannung aktiv)
  - `disk_root` (kein Plattenplatz)
  - `service:*` (wichtige systemd-Units down)
- WARN-Stufen bleiben bewusst beim Sunset-Diff-Filter — sie sind nicht
  zeitkritisch genug für einen Sofortalarm.
- Eingebunden in `automation_daemon._zyklus_aktoren` direkt nach dem
  Integrity-Alarm-Check, gleicher 10-min-Throttle.

**(b) Persistenter Dedup für Sofortalarme**
- Neu: `_dedup_load()` / `_dedup_save()` mit JSON-File
  `config/event_notifier_dedup.json`. EventNotifier lädt beim Start, räumt
  Tagesalt-Einträge auf und schreibt nach jedem Versand atomar zurück.
- Helper `_dedup_already_sent(key)` / `_dedup_mark(key)` ersetzen alle
  bisherigen In-Memory-Zugriffe auf `self._gesendet`. Folge:
  Daemon-Restart → keine Doppelmails mehr.
- Live-Schwellwerte (`prüfe_und_melde`), Sunset-Tagesbericht und
  Integrity-Sofortalarme sind alle umgestellt.
- Generischer Versand-Helper `_sende_diagnos_alarm(alarm_key, text,
  details, kategorie)` für künftige Sofortpfade.

**(c) NQ-Mail-Skelett** ([automation/engine/nq_notifier.py](automation/engine/nq_notifier.py))
- Vorbereitung für Mai-Inbetriebnahme PAC4200: `NQNotifier`-Klasse mit
  - `diff_nq_befunde()` — eigener State-File `config/nq_alert_state.json`,
    nutzt `diagnos_alert_state.filter_reportable()` (gleiche Diff-/
    Reminder-/Heilungslogik wie Diagnos).
  - `format_nq_summary()` — Sektion für Sunset-Mail-Anteil.
  - `pruefe_nq_sofortalarme()` — Trade-Switch / THDu-Hard / Asymmetrie-
    Hard via gemeinsamem Versand-Helper im EventNotifier.
- Aktivierungsschalter `ENABLED = False` (default). Wird gesetzt, sobald
  PAC4200 + Messwandler montiert sind und das `netzqualitaet`-Subsystem
  Check-Listen liefert. Bis dahin ruft `automation_daemon` den Notifier
  nicht auf.

**Mail-Pfad-Status (Stand 29.04.2026)**

| Pfad | Dedup | Filter | Aktivierung |
|---|---|---|---|
| Sunset-Tagesbericht | persistent 1×/Tag | Diff (Diagnos) | aktiv |
| Live-Schwellwerte (Batt-Temp/SOC, Netz/SLS) | persistent 1×/Tag/Key | sofort | aktiv |
| Integrity-Sofortalarme (Collector-Liveness) | persistent 1×/Tag/Key | 10 min | aktiv |
| Health-Sofortalarme (CPU/Disk/Service/Throttle) | persistent 1×/Tag/Key | 10 min | aktiv |
| NQ-Sunset-Anteil | persistent 1×/Tag, Diff | Diff (NQ) | Skelett (Mai) |
| NQ-Sofortalarme (Trade-Switch/THDu-Hard) | persistent 1×/Tag/Key | sofort | Skelett (Mai) |

Smoke-Tests (a/b/c) grün — neu/changed/reminder/heilung der NQ-Diff-
Logik verifiziert, Whitelist-Filter im Health-Pfad korrekt (mirror_sync,
RAM-WARN bewusst NICHT im Sofortpfad).

---

## v1.3.3 — 2026-04-27

### Diagnos — Mail-Diff-Filter & Subject-Severity-Suffix

**Problem:** Sunset-Mail wiederholte täglich identische WARN/KRIT-Listings,
auch wenn der Befund stabil war (z. B. alte raw_data-Lücken, die nicht
refilled werden). Folge: Mail-Inbox wurde laut, echte Verschlechterungen
gingen optisch unter.

**Lösung:**
- Neues Modul `automation/engine/diagnos_alert_state.py`:
  - Pro Diagnos-Check (health + integrity) wird ein **Fingerprint** aus
    severity + checkspezifischen Hauptfeldern gebildet (z. B. bei
    `integrity:gaps:*` zählen `gap_count` + `max_gap_s`; bei
    `cpu_temp` der gerundete °C-Wert; bei `daily_energy_balance` das
    100-Wh-gerundete `max_diff_wh`).
  - Persistenter State in `config/diagnos_alert_state.json`.
  - Befund wird in die Mail aufgenommen bei: **neu** | **changed**
    (Fingerprint anders) | **reminder** (≥ 7 Tage stumm).
  - **Heilung:** severity zurück auf `ok` löscht den State-Eintrag →
    der nächste erneute Befund wird wieder gemeldet.
- `event_notifier.sende_sunset_bericht()`:
  - filtert `bad_checks` beider Snapshots (Health + Integrity) gegen den
    persistenten State.
  - Sektion „Auffaelligkeiten" → „Auffaelligkeiten (neu/eskaliert)"
    inkl. Reason-Tag (`changed` / `reminder`).
  - Stabile Befunde werden mit Hinweis „N stabile Befund(e) unterdrueckt"
    ausgeblendet, nicht stillschweigend verschluckt.
  - Diff-Zusammenfassung am Mail-Ende:
    `neu= changed= reminder= unterdrueckt= geheilt=`.
- **Subject-Suffix:** `[PV-System] Tagesbericht 27.04.2026 — FAIL(n) KRIT(n) WARN(n)`
  — nur wenn diesmal frische Befunde existieren. Tag ohne neue Probleme
  → sauberer Betreff (Inbox-Sortierung erleichtert Nacharbeit).

**Architektur-Hinweis:** Filter-Modul ist generisch — `filter_reportable()`
nimmt eine beliebige Check-Liste und kann später für NQ-Befunde
(PAC4200-Bänder, THDu, Asymmetrie) wiederverwendet werden, mit
eigenem `path`-Argument für `config/nq_alert_state.json`.

**Mail-Pfad-Status (Stand 27.04.2026):**
- Sunset-Tagesbericht: 1×/Tag, jetzt mit Diff-Filter ✅
- Live-Schwellwerte (Batt-Temp, SOC, Netz/SLS-Überlast): sofort, 1×/Tag/Key ✅
- Integrity-Sofortalarme (Collector inaktiv, Fehlerstrang, Reconnect-Fail):
  alle 10 min, 1×/Tag/Key ✅
- **Offene Lücke:** Health-Befunde (CPU-Crit, Disk-Crit, Service-Down,
  Mirror-Stale) haben keinen Sofortpfad → warten bis Sunset.
- **Offene Schwachstelle:** In-Memory-Dedup bei Sofortalarmen
  (`self._gesendet`) verfällt bei Daemon-Restart.

Siehe [/memories/repo/diagnos-mail-diff-filter-2026-04-27.md](memories/repo/diagnos-mail-diff-filter-2026-04-27.md)
für Folge-ToDos (3. lauschende Instanz Pi5, Health-Sofortpfad, NQ-Adapter).

---

## v1.3.2 — 2026-04-26

### Automation — Tiefenprüfung & Härtung (A+B+E)

**A. SOC-Grenzen-Steuerbox: Root-Cause-Fix (D1+D2+D3)**
- **D1** `data_collector._collect_battery_soc_config`: Fehler beim Lesen der
  Fronius-SOC-Konfiguration werden jetzt als `LOG.warning` (300 s same-error
  throttle) sichtbar gemacht statt als `LOG.debug` zu verschwinden.
- **D2** `aktor_batterie._ensure_manual_mode()`: Neuer SOC-Mode-Guard. Vor
  jedem Schreiben auf `BAT_M0_SOC_MIN/MAX` wird `BAT_M0_SOC_MODE` gelesen
  (Cache-invalidiert); steht der Modus auf `auto`, wird automatisch auf
  `manual` umgestellt. Hintergrund: Bei `SOC_MODE='auto'` ignoriert die
  GEN24-Firmware SOC-MIN/MAX-Schreibvorgänge stillschweigend → Steuerbox-UI
  zeigte gespeichert, Hardware übernahm nicht.
- **D3** `actuator.ausfuehren_plan`: Bei `verifiziere().ok=False` wird jetzt
  `ergebnis['ok']=False` propagiert, der Dedup-Erfolgs-Timestamp
  zurückgenommen und der Fehler-Cooldown gesetzt. Damit beendet die
  Engine endlose Reapply-Schleifen bei nicht-wirksamen Schreibvorgängen.

**B. Respekt-Symmetrie (HP / Klima / Override-Layer)**
- `_cancel_conflicting_overrides(desired_state, geraet)`: generalisiert,
  cancelt Overrides der Gegenrichtung in beiden Richtungen und schreibt
  pro betroffenem Override einen `steuerbox_audit`-Eintrag.
- Erkennung von extern-EIN (HP, Klima) ruft jetzt symmetrisch
  `_cancel_conflicting_overrides('on', …)` — vorher nur AUS-Pfad.
- `operator_overrides._active_hold_needs_reapply`: spekulative
  „könnte-ja-extern-sein"-Branches entfernt; Idempotenz via Soll==Ist;
  Drift → Reapply.

**E. Konsistenz Code ↔ Matrix ↔ Doku**
- `extern_respekt_s` Code-Default 3600 → **1800 s** (HP/Klima),
  `start_h` `RegelWwAbsenkung` 23 → **22**, `ev_leistung_schwelle_w`
  `RegelWattpilotBattSchutz` 2000 → **5000**.
- `HP_TOGGLE_OVERRIDE_FLOW.md` von Repo-Wurzel → `doc/automation/`,
  Two-Layer-Verkopplung dokumentiert, alle `3600`-Beispiele auf `1800`
  korrigiert.
- Audit-Bericht: `doc/AUTOMATION_AUDIT_2026-04-26.md`.

### Projekt
- Version: 1.3.1 → 1.3.2

---

## v1.3.1 — 2026-04-19

### Automation — Deep Audit & Fixes (4 kritische Findings behoben)
- **K-01 AktorBatterie Verifikation:** `verifiziere()` war TODO-Stub (immer `ok=True`). Jetzt Read-Back via `BatteryConfig.get_values()` mit Cache-Invalidierung und `BAT_M0_SOC_MIN/MAX`-Abgleich.
- **K-02 engine_vorausschau() vervollständigt:** Web-API-Vorausschau hatte nur 8 von 17 Regeln. 9 fehlende Regeln (Klimaanlage, WP-Regeln) nachgetragen.
- **K-03 Klimaanlage Startup-Check:** `_hp_startup_check()` prüft jetzt alle Fritz!DECT `geraete[]` (HP + Klimaanlage) bei Daemon-(Neu-)Start. Verhindert unkontrollierten Weiterlauf nach Crash.
- **K-04 Matrix-Auto-Reload:** Engine prüft `os.path.getmtime()` der Parametermatrix in jedem Zyklus. pv-config-Änderungen wirken ohne SIGHUP/Restart (≤60s).

### Dateilayout & Housekeeping
- **14 Scripts nach `scripts/` verschoben:** `monitor_*.sh`, `stop_services.sh`, `restart_webserver.sh`, `check_single_instance.sh`, `logrotate.sh`.
- `.gitignore`, `crontab`, `install_services.sh`, `install_shutdown_persist_service.sh` auf neue Pfade angepasst.

### Dokumentation
- **`doc/TODO.md` konsolidiert:** 5 verstreute TODO-Dateien (meta, automation, steuerbox, netzqualitaet) in eine zentrale Datei zusammengeführt.
- **6 obsolete Docs gelöscht**, 3 archiviert (SYSTEM_AUDIT, SOC-VERIFY, ARBEITSFORTSCHRITT).
- **`doc/DEEP_AUDIT_ENGINE_2026-06.md`:** Vollständiger statischer Audit-Report (17 Regeln, 4 Aktoren, Parametermatrix, Score-Hierarchie).
- `SYSTEM_BRIEFING.md`, `GIT_WORKFLOW.md`, `VEROEFFENTLICHUNGSRICHTLINIE.md`, `KI_BEITRAGSANALYSE.md` aktualisiert.

### Projekt
- Version: 1.3.0 → 1.3.1

---

## v1.3.0 — 2026-04-04

### Features
- **Netzqualitäts-Modul (Phase 1):** Tagesprofil-API (`/api/netzqualitaet/tag`), 5min-Buckets aus raw_data mit Fallback auf data_1min, L-L-Spannungen und Frequenz-Charts.
- **Netzqualitäts-UI:** Eigene Seite mit Tagesprofilansicht, erreichbar über Maschinenraum-Header.
- **Netzqualitäts-Export:** CSV/JSON-Export der Tagesdaten.

### Dokumentation
- **Release-Bereinigung:** Entwicklungs-Journale, Audit-Prozessdokumentation und geklärte Fragen aus Fachdokus entfernt — nur IST-Zustand und Roadmap verbleiben.
- `TIEFENPRUEFUNG_2026-03-08.md` archiviert (→ `doc/archive/`).
- `SYSTEM_AUDIT_2026-03-24.md` auf Kernbefunde komprimiert (§3-5 gestrafft).
- `OFFENE_FRAGEN.md` auf tatsächlich offene Fragen reduziert (F1/F3/F4 entfernt).
- `DIAGNOS_KONZEPT.md` und `UMSETZUNGSPLAN.md` mit Status-Disclaimer versehen.
- `automation/README.md` Hardware-Narrative gestrafft.

### Projekt
- `pyproject.toml`: Fehlende Module ergänzt (`fritzdect_collector`, `netzqualitaet`, `diagnos`).
- `monitor.sh`: Deprecation-Hinweis (ersetzt durch `scripts/monitor_health.sh` + `diagnos/health.py`).

---

## v1.2.1 — 2026-03-24

### Features
- **Phase 1b Parametrisierung:** `batt_idle_toleranz_w` (default 800W) und `grid_ok_toleranz_w` (default 500W) neu in soc_param_matrix.json — alle Phase 1b Bedingungen jetzt via pv-config anpassbar.
- **Kurz-Burst-Schutz erweitert:** 
  - `kurz_burst_max_s`: Schwelle für "Kurz-Burst" von 300s (5 Min) auf **420s (7 Min)** erhöht
  - `kurz_burst_sperre_s`: EIN-Sperre nach Kurz-Burst-Limit von 420s (7 Min) auf **1800s (30 Min)** erhöht
  - Alle Kurz-Burst-Parameter (`kurz_burst_max_s`, `kurz_burst_limit`, `kurz_burst_sperre_s`) jetzt in soc_param_matrix.json und via pv-config editierbar

### Fixes
- **Chart Auto-Refresh bei Mitternacht:** Fehler behoben, bei dem Monitoring/Erzeuger-Charts nach Mitternacht stehen blieben. Charts erkennen jetzt automatisch Tageswechsel und fahren fort (`templates/erzeuger_view.html`, `templates/tag_view.html`)
- **Phase 1b Bouncing reduziert:** Erhöhte Toleranzen für Batterie-Idle (500W → 800W) und Netzbezug (300W → 500W) reduzieren falsche Probes bei dynamischen Haushaltlasten significantly

### Config
- **5 neue Parameter in soc_param_matrix.json** für HP-Automation:
  - `batt_idle_toleranz_w` (300–1500W, default 800W): Phase 1b Batterie-Idle-Schwelle
  - `grid_ok_toleranz_w` (200–1000W, default 500W): Phase 1b Netzbezug-Toleranz
  - `kurz_burst_max_s` (180–900s, default 420s): Definition "Kurz-Burst" (7 Min statt 5)
  - `kurz_burst_limit` (1–5 count, default 2): Schwelle für EIN-Sperre
  - `kurz_burst_sperre_s` (300–3600s, default 1800s): Dauer EIN-Sperre (30 Min statt 7 Min)

### Dokumentation
- doc/automation/WP_INTEGRATION.md: Parameter-Dokumentation aktualisiert
- doc/automation/STRATEGIEN.md: Phase 1b Logik dokumentiert
- Schaltprotokoll-Analyse dokumentiert (Ursachenbericht Phase 1b Überaktivität)

---

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
