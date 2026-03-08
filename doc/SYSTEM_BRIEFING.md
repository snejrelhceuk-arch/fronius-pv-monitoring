# PV-System Briefing — LLM-Kontext

**Zweck:** Kompaktes Onboarding für jeden neuen Chat. Immer aktuell halten!
**Stand:** 2026-03-08 | **LOC:** ~28.200 Python, ~11.000 Doku

---

## 1. Hardware

| Komponente | Typ | Eckdaten |
|---|---|---|
| **Wechselrichter** | Fronius GEN24 12.0 | 12 kW, Hybrid (PV + Batterie), SunSpec Modbus + HTTP-API |
| **PV-Generator** | 3 Strings, 37.59 kWp | S1: 24×440W Süd30°, S2: 21×440W Nord15°, S3: 12×540W Süd10° |
| **Batterie** | BYD HVS 2×10.24 kWh (parallel) | 20.48 kWh netto, LFP, 1 BMS, max ~22 A (GEN24 DC-DC-Limit) |
| **WattPilot** | Fronius WattPilot Go 22J | 22 kW, 3×32A, WebSocket-API, Single-Client-Einschränkung |
| **Heizpatrone** | 2 kW im WW-Speicher | Schaltung via Fritz!DECT 200 Steckdose (AHA-HTTP-API) |
| **SmartMeter** | Fronius Smart Meter TS 65A-3 | Einspeisezähler, Nulleinspeisung aktiv |
| **Host (Primär)** | Raspberry Pi 4, 4 GB | Debian/Bookworm, SD-Karte, `/dev/shm/` tmpfs für RAM-DBs |
| **Host (Failover)** | Raspberry Pi 4, 8 GB | fronipi (.105), gleicher Code, `.role`-Datei steuert aktive Services |

**Standort:** 51.01°N, 12.95°E, 315 m (Erlau, Sachsen) — **Nulleinspeiser**

---

## 2. Architektur (3 Säulen)

```
┌─────────────────┐   ┌───────────────────────┐   ┌──────────────┐
│  A) Collector    │   │  B) Web-API (Flask)    │   │ C) Automation│
│  collector.py    │   │  web_api.py + routes/  │   │ engine/      │
│  wattpilot_*.py  │   │  10 HTML-Templates     │   │ 4 Schichten  │
│  → /dev/shm/    │   │  ≈ READ-ONLY auf DBs   │   │ S1→S2→S3→S4 │
│    fronius_data  │   │  Gunicorn (4 Worker)   │   │ Score-Regeln │
│    .db           │   │                        │   │ Param-Matrix │
└────────┬────────┘   └───────────┬────────────┘   └──────┬───────┘
         │                        │                        │
    ┌────┴────────────────────────┴────────────────────────┴────┐
    │                    SQLite-Datenbanken                      │
    │  /dev/shm/fronius_data.db    ← Collector-DB (RAM, 10s)    │
    │  /dev/shm/automation_obs.db  ← ObsState (RAM, WAL)        │
    │  data.db                     ← Persist (SD, stündlich)     │
    └───────────────────────────────────────────────────────────┘
```

**ABC-Trennung:** A schreibt DBs, B liest nur, C hat eigene RAM-DB + eigene Aktoren.
Config-Änderungen NUR via SSH (`pv-config.py` TUI) — Web ist read-only.

---

## 3. Automation-Engine (Schicht C)

**4 Schichten:**

| Schicht | Aufgabe | Kern-Modul |
|---|---|---|
| **S1 Config** | Parametermatrix laden | `param_matrix.py` → `config/soc_param_matrix.json` |
| **S2 Observer** | Sensordaten → ObsState | `observer.py` + `collectors/` (data, forecast, battery) |
| **S3 Engine** | Score-Bewertung → ActionPlan | `engine.py` + `regeln/` (8 aktive Regeln) |
| **S4 Actuator** | Aktionen ausführen | `actuator.py` + `aktoren/` (batterie, fritzdect, wattpilot[stub]) |

**8 aktive Regeln (Stand 2026-03-08):**

| Regel | Zyklus | Prio | Funktion |
|---|---|---|---|
| `RegelSlsSchutz` | fast (60s) | P1 | SLS Phasenstromschutz — proportionale Wattpilot-Abregelung (30–63A konfigurierbar) |
| `RegelWattpilotBattSchutz` | fast | P1 | SOC-Schutz bei EV-Ladung |
| `RegelKomfortReset` | fast | P2 | Täglicher SOC 25–75% Reset, Früh-Reset mit Hysterese |
| `RegelMorgenSocMin` | strategic (15m) | P2 | SOC_MIN-Öffnung nach Sunrise+PV-Prognose |
| `RegelNachmittagSocMax` | strategic | P2 | SOC_MAX→100% ab Clear-Sky-Peak |
| `RegelHeizpatrone` | fast | P2 | 6-Phasen HP-Steuerung via Fritz!DECT |
| `RegelZellausgleich` | strategic | P3 | Monatl. BYD-Vollzyklus |
| `RegelForecastPlausi` | strategic | P3 | IST/SOLL-Abweichung → SOC anpassen |

**Entfernt (2026-03-07):** RegelSocSchutz, RegelTempSchutz, RegelAbendEntladerate,
RegelLaderateDynamisch — GEN24 HW-Limit macht Software-Ratenlimits obsolet.

**Steuerungsinstrument:** SOC_MIN / SOC_MAX via Fronius HTTP-API (`/config/batteries`).

---

## 4. Datenbanken

| DB | Pfad | Zweck | Schreiber |
|---|---|---|---|
| **Collector-DB** | `/dev/shm/fronius_data.db` | Rohdaten 10s, Aggregationen 1min→monthly | collector.py |
| **Automation-DB** | `/dev/shm/automation_obs.db` | ObsState (1 Zeile), automation_log | automation_daemon |
| **Persist-DB** | `data.db` (SD-Karte) | Stündl. Backup, forecast_daily, automation_log | aggregate_*.py, engine |

**Wichtig:** RAM-DBs gehen bei Reboot verloren → Collector + Automation starten clean.
Persist-DB ist die langfristige Quelle.

**Backup:** Stündlich tmpfs → SD auf Pi4 Primary (`SQLite .backup()`),
täglich SD → Pi5 (.195, NVMe) per rsync + GFS-Rotation
(Sohn 3d / Vater 1w / Großvater 1m / Urgroßvater 1y).

---

## 5. Services (systemd)

| Service | Prozess | Funktion |
|---|---|---|
| `pv-automation.service` | `automation_daemon.py` | Engine + Observer + Actuator (Hauptprozess) |
| `pv-observer.service` | `collector.py` | Fronius-Daten → Collector-DB (10s Polling) |
| `pv-wattpilot.service` | `wattpilot_collector.py` | WattPilot → Collector-DB (WebSocket, 30s Polling) |
| Gunicorn (manuell) | `web_api.py` | Flask Web-UI + REST-API (Port 8000) |
| Cron | `aggregate_*.py` | Aggregation 1min/15min/hourly/daily/monthly |

---

## 6. Dateisystem-Übersicht

```
pv-system/
├── config.py                 ← Zentrale Konstanten (DB-Pfade, PV_KWP, etc.)
├── collector.py              ← Fronius-Polling (Säule A)
├── web_api.py + routes/      ← Flask-App (Säule B)
├── automation/               
│   └── engine/               ← Gesamte Automation (Säule C)
│       ├── automation_daemon.py   ← Hauptprozess
│       ├── engine.py              ← Score-Engine
│       ├── observer.py            ← Observer-Loop
│       ├── actuator.py            ← Action-Dispatcher
│       ├── obs_state.py           ← ObsState-Datenmodell
│       ├── param_matrix.py        ← Matrix-Loader
│       ├── regeln/                ← 4 Module, 8 Regeln
│       ├── collectors/            ← data, forecast, battery
│       └── aktoren/               ← batterie, fritzdect, wattpilot
├── config/
│   ├── soc_param_matrix.json ← HAUPT-Config (alle Regel-Parameter)
│   ├── fritz_config.json     ← Fritz!Box Credentials
│   ├── solar_calibration.json← PV-Kalibrierung
│   └── ...
├── doc/                      ← Gesamte Dokumentation
│   ├── SYSTEM_BRIEFING.md    ← DIESES DOKUMENT
│   ├── system/               ← Infra, Hosts, Git, Security
│   ├── automation/           ← Engine, Strategien, Algorithmen
│   ├── collector/            ← DB-Schema, Felder, Pipeline
│   ├── web/                  ← Display-Konventionen
│   ├── meta/                 ← Referenzsystem, Richtlinien
│   └── archive/              ← Abgeschlossene Analysen
├── templates/                ← 10 Jinja2-Templates
├── static/                   ← CSS, JS, Icons
└── scripts/, tools/          ← Hilfsskripte
```

---

## 7. Wichtige Konventionen

- **Sprache:** Code englisch, Kommentare/Logs/Docs deutsch
- **Config-Tool:** `pv-config.py` (whiptail TUI via SSH) — NICHT Web-UI
- **ABC-Policy:** Web darf KEINE Automation-Daten schreiben
- **Param-Matrix:** `config/soc_param_matrix.json` ist die Single Source of Truth
  für alle Regelkreis-Parameter (Schwellen, Zeiten, Scores)
- **Git:** Single-Branch (`main`), 2 Hosts (Pi4 primary, Pi4 failover) + Online-Repo
- **Logging:** Alles nach `/tmp/*.log` (tmpfs) — Details siehe **§9 Logging-Konvention**
- **.role-Datei:** Im Workspace-Root, steuert ob Host `primary` oder `failover` ist
- **Dedup-Sperre:** Actuator verhindert identische Befehle innerhalb 45 s
- **Extern-Erkennung:** SocExternTracker erkennt manuelle SOC-Änderungen → 30 min Toleranz
- **Nulleinspeiser:** Anlage darf NICHT ins Netz einspeisen (SmartMeter-Regelung)
- **⚠️ Namenskonvention WP:** `WP` = **Wärmepumpe** (immer!), `wp_`/`P_WP`/`W_Imp_WP` → Wärmepumpe. Wattpilot = `wattpilot_` / ausgeschrieben. Niemals `WP` für Wattpilot verwenden!

---

## 8. WattPilot WebSocket-Zugriffsmatrix

**Constraint:** WattPilot erlaubt nur **1 WebSocket-Verbindung** gleichzeitig.

### Lesend (WebSocket zum WattPilot)

| Quelle | Trigger | Intervall | Dauer | Freigabe |
|--------|---------|-----------|-------|----------|
| `wattpilot_collector.py` (pv-wattpilot.service) | Timer-Loop | **30s** | ~2–3s | sofort nach `get_status_summary()` |
| `/api/wattpilot/status` (routes/system.py) | HTTP-Request | on-demand, **30s Cache** | ~2–3s | sofort nach Response |

→ WebSocket-Belegung: ~8% (2–3s/30s). Externe Clients (go-e App, Fronius App, Solar.web) können zusätzlich belegen.

### Lesend (nur DB — kein WebSocket)

| Quelle | Liest aus | Trigger |
|--------|-----------|---------|
| `routes/realtime.py` | `wattpilot_readings` | HTTP-Request (Dashboard) |
| `routes/verbraucher.py` | `wattpilot_daily` | HTTP-Request |
| `routes/visualization.py` | `wattpilot_daily` | HTTP-Request |
| `/api/wattpilot/history` | `wattpilot_daily` | HTTP-Request |
| `data_collector.py` (Automation) | `wattpilot_readings` | Engine-Zyklus |

### Schreibend (WebSocket — securedMsg, nur Notfall)

| Quelle | Trigger | Dauer | Retry |
|--------|---------|-------|-------|
| `aktor_wattpilot.py` (SLS-Schutz, manuell) | Netzüberlast >SLS-Schwelle | ~3–5s | **3×, je 3s Pause** |
| `aktor_wattpilot.py` `verifiziere()` | nach Schreibbefehl (Read-Back) | ~2–3s | nein (lesend) |

Schreibzugriffe verwenden `securedMsg` (HMAC-SHA256). Bei WebSocket-Kollision automatischer Retry (konfigurierbar: `WATTPILOT_WRITE_RETRIES`, `WATTPILOT_WRITE_RETRY_PAUSE`). Collector-Pause ist bei 30s Polling + Retry nicht nötig (Kollisionsrisiko <0.1%).

---

## 9. Logging-Konvention (tmpfs)

### Grundregel

**Alle Logdateien → `/tmp/*.log`** (tmpfs, 256 MB, geteilt mit DBs auf `/dev/shm`).

Es gibt **keinen zentralen Mechanismus**, der neue Komponenten automatisch nach `/tmp` loggen lässt. Jede Komponente muss ihre Log-Ausgabe **explizit** konfigurieren — über eine der drei Methoden unten.

### Drei Log-Methoden

| Methode | Beispiel | Wann |
|---------|----------|------|
| **systemd → journald** | `logging.basicConfig()` → stdout → journald | Python-Services (`collector.py`, `wattpilot_collector.py`, `automation_daemon.py`) |
| **Cron-Redirect** | `>> /tmp/aggregate.log 2>&1` | Crontab-Einträge für Aggregation, Forecast, Backup |
| **Shell LOG_FILE** | `LOG_FILE="/tmp/collector_monitor.log"` | Monitor-Scripts, Bash-Hilfsskripte |

### Checkliste für neue Komponenten

1. **Python-Service (systemd):** `logging.basicConfig()` reicht — journald rotiert selbst (7 Tage).
2. **Cron-Job:** Output nach `/tmp/<name>.log` umleiten: `>> /tmp/<name>.log 2>&1`
3. **Shell-Script:** `LOG_FILE="/tmp/<name>.log"` setzen — **nicht** auf SD (`${BASE_DIR}/`).
4. **Dateiendung:** Immer `.log` verwenden — `logrotate.sh` erkennt Dateien per Glob `${LOG_DIR}/*.log`.

### Automatische Rotation

`logrotate.sh` (Cron 02:30) erkennt **alle** `/tmp/*.log` dynamisch (Glob, keine Liste).

| Trigger | Schwelle |
|---------|----------|
| Größe | ≥ 10 MB → rotieren + gzip |
| Alter | ≥ 7 Tage (>100 Bytes) → rotieren + gzip |
| Archiv-Löschung | `.gz` älter 7 Tage → löschen |
| Gunicorn | USR1-Signal nach Rotation (FD-Reopen) |
| tmpfs-Warnung | >80% Belegung → Log-Warnung |

### Nicht auf tmpfs loggen

- `schaltlog.txt` (SD, `logs/`) — bewusste Ausnahme (persistentes Schaltprotokoll, eigene Truncate-Logik >10k Zeilen)

---

## 10. Bekannte Einschränkungen / TODOs

| Bereich | Status | Detail |
|---|---|---|
| **WattPilot-Aktor** | IMPLEMENTIERT | securedMsg (HMAC-SHA256): amp (6–32A), psm (1/3-phasig), frc (Start/Stop). Proportionale SLS-Abregelung. Retry 3×3s bei Kollision. |
| **WW-Temperatursensor** | FEHLT | Kein Sensor → HP-Übertemperaturschutz (≥78°C) kann nicht greifen |
| **AktorBatterie.verifiziere()** | NO-OP | HTTP-API Read-Back noch nicht implementiert |
| **RegelHeizpatrone** | MONOLITH | 903 LOC, Refactoring zu Phase-Objekten geplant (W1) |

---

## 11. Quick-Reference: Häufige Aufgaben

| Aufgabe | Befehl / Datei |
|---|---|
| Regel-Parameter ändern | `pv-config.py` → Regelkreise → [Name] |
| Matrix direkt editieren | `config/soc_param_matrix.json` |
| Automation-Log prüfen | `journalctl -u pv-automation -f` |
| ObsState inspizieren | `sqlite3 /dev/shm/automation_obs.db "SELECT * FROM obs_state"` |
| Vorausschau (Web) | `http://<host>:8000/api/vorausschau` |
| Service neustarten | `sudo systemctl restart pv-automation` |
| Webserver neustarten | `./restart_webserver.sh` |
| Alle Services stoppen | `./stop_services.sh` |
| Collector-DB prüfen | `sqlite3 /dev/shm/fronius_data.db ".tables"` |

---

## 12. Dokumentations-Struktur

| Ordner | Inhalt | Wichtigste Dateien |
|---|---|---|
| `doc/system/` | Infrastruktur, Hosts, Security | SYSTEM_ARCHITECTURE, DUAL_HOST, ABC_POLICY |
| `doc/automation/` | Engine, Regeln, Strategien | AUTOMATION_ARCHITEKTUR, BATTERY_ALGORITHM, SCHUTZREGELN |
| `doc/collector/` | Datenbank, Felder, Pipeline | DB_SCHEMA, FELDNAMEN_REFERENZ, AGGREGATION_PIPELINE |
| `doc/web/` | Frontend-Konventionen | DISPLAY_CONVENTIONS |
| `doc/meta/` | Projekt-Übergreifend | PV_REFERENZSYSTEM, VEROEFFENTLICHUNGSRICHTLINIE |
| `doc/archive/` | Abgeschlossene Analysen | BATTERY_COUNTER_DISCOVERY, SYSTEMVERLUSTE, etc. |
