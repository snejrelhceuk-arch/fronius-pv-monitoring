# Changelog — PV-System Erlau

Alle wesentlichen Änderungen am System, chronologisch absteigend.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/).

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

## [Unreleased]

### Features
- **Klima Extern-Erkennung:** Manuelles Einschalten der Klimaanlage wird für `extern_respekt_s` (Standard 30 Min) respektiert. Zustandsbasierte Erkennung (OFF→ON ohne Engine-Beteiligung), analog zum HP-Muster. Während Respekt-Zeit greift nur die harte Sicherheit (Sunset+SOC).
- **Batterie-Zelltemperaturen:** BYD-Zelltemperaturen (min/max/avg) via HTTP in DataCollector integriert (30 s Rate-Limit).
- **Steuerbox Tages-Intent `afternoon_charge_request`:** Einmal-Trigger (z. B. aus HA) setzt einen Nachmittags-Ladewunsch bis Sunset. `respekt_s` wird serverseitig aus Sunset abgeleitet (Fallback 17:00) und als Policy-Hold geführt.
- **SOC/HP-Kooperation für Ladewunsch:** `RegelNachmittagSocMax` priorisiert bei aktivem Tages-Intent das Ziel `SOC_MAX=100` im adaptiven Startfenster 12–15 Uhr; `RegelHeizpatrone` pausiert HP bis Ziel-SOC erreicht ist.
- **Optionale HA MQTT Bridge:** Neuer Adapter `steuerbox/ha_mqtt_bridge.py` publiziert read-only MQTT Discovery/State aus `/api/ha/*` für HA-Entitäten ohne Steuerpfad.

### System
- **Steuerbox-Monitoring:** `pv-steuerbox.service` in zentrale Überwachung integriert (diagnos, Cron-Keepalive via `monitor_steuerbox.sh`).
- **Failover-Sync gehärtet:** `.state`-Verzeichnis-Initialisierung über Boot-Service (`pv-failover-init.service`), Error-Logging in `failover_sync_db.sh`.
- **HA-Read/Discovery ausgebaut:** Neue Endpunkte `/api/ha/automation`, `/api/ha/device`, `/api/ha/entities` ergänzen den bestehenden HA-Export (`/api/ha/flow`, `/api/ha/wattpilot`) für einfachere Entitäts- und Geräteabbildung.

### Fixes
- **Klima Rapid-Shutdown behoben:** Klimaanlage wurde nach manuellem Einschalten sofort wieder abgeschaltet, weil `RegelKlimaanlage` keine Extern-Erkennung hatte. `_uses_respekt_hold()` gibt für Klima `False` zurück → DB-basierter Ansatz war wirkungslos. Lösung: Zustandsübergangs-Erkennung (wie HP).
- **Verbrauchsformel Tageskopf (counter_totals):** `routes/visualization.py` — Formel von `ertrag + bezug - einspeis` (reiner PV-DC-Ertrag) auf `ac_gesamt + bezug - einspeis` (mit `ac_gesamt = W_AC_Inv + F2 + F3`) umgestellt. `W_AC_Inv` bildet den gesamten AC-Ausgang des Wechselrichters ab (PV + Batterieentladung − Batterieladung), sodass die Batterieentladung korrekt im Tagesverbrauch erscheint.

### Projektankündigungen
- MEGA-BAS Rollout: I2C-HAT-Inbetriebnahme mit zusätzlicher Temperatur-Sensorik und vorbereiteter Aktorik für kommende Hardware-Phasen.
- 3-Phasen-Heizpatrone (Zukunftsphase): Konzept für stufenweise Zuschaltung und Schützstrategie als nächster Ausbauschritt.

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
