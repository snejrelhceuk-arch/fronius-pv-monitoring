# Fronius PV-Monitoring System

Production-ready Monitoring und Automatisierung für Fronius Gen24 Hybrid PV-Anlage (37,59 kWp) mit BYD Battery Storage und Dimplex Wärmepumpe.

> Interne Betriebs- und Infrastrukturdokumentation wird lokal gehalten und ist im öffentlichen Repo bewusst nicht enthalten.

> **Doku-Tracks:** Menschen lesen `doc/<bereich>/` (ausführliche Manuals) und `doc/TODO.md`. **Agenten/LLMs starten bei [`AGENTS.md`](AGENTS.md)** und folgen der dort beschriebenen Lade-Hierarchie zu `doc/llm/INDEX.md` → konkrete Card.

## Produktionsstart
Produktivbetrieb seit **01.01.2026 00:00 Uhr**

## Rollen-Architektur (ABCDEN)

| Rolle | Modul | Aufgabe |
|---|---|---|
| **A** Collector | `collector/` | Modbus-Read + Aggregation, RAM-Buffer, Persist |
| **B** Web-API | `web_api.py`, `routes/` | Lesende Flask-API + Visualisierung (Port 8000) |
| **C** Automation | `automation/` | Schreibzugriff: Inverter, WP, Wattpilot, Fritz!DECT |
| **D** Diagnos | `diagnos/` | Monitoring, Integritätsprüfung, Tagesmail |
| **E** Steuerbox | `steuerbox/` | Operator-Intent-API (eigener Port), Intents an C |
| **N** Netzqualität | `nq/` | PAC4200 Modbus read-only, eigene NQ-DBs |

Rollentrennung ist die oberste Architekturpriorität. Code-Dupletten zum Absichern der Trennung sind gewollt.

## Schnellstart

System läuft vollständig über systemd-Services. Kein manueller Start nötig.

```bash
# Status prüfen
sudo systemctl status pv-collector pv-web pv-automation pv-steuerbox pv-wattpilot

# Web-Interface
http://localhost:8000

# Logs (journald)
journalctl -u pv-collector -f
journalctl -u pv-web -f
journalctl -u pv-automation -f
```

## Komponenten

### Collector (Rolle A)
- **collector/** — Modbus-Collector als Package (3 s Polling, RAM-Buffer, Persist-Thread)
- **collector/aggregate/** — 5-stufige Aggregations-Pipeline (`min1`, `fifteen`, `daily`, `monthly`, `statistics`)
- **collector/wattpilot.py** — Wattpilot-Collector (WebSocket, `wattpilot_daily`)
- **collector/fritzdect.py** — FritzDECT-Collector (AHA-HTTP, Schaltstatus)
- **collector/aggregate/wp_thermal.py** — Dimplex-Wärmemengenzähler → COP/SCOP (`wp_thermal_daily`)

### Web-API (Rolle B)
- **web_api.py** — Flask/Gunicorn App mit Blueprint-Registration (Port 8000)
- **routes/** — Blueprints: `pages`, `data`, `realtime`, `visualization`, `verbraucher`, `erzeuger`, `system`, `forecast`, `netzqualitaet`, `pac4200`, `analyse_speicher`

### Automation (Rolle C)
- **automation/engine/** — Tick-Loop, Regel-Registry, Observer→Engine→Actuator
- **automation/battery_control.py** — SOC_MIN/SOC_MAX via Fronius HTTP-API

### Diagnos (Rolle D)
- **diagnos/health.py** — Host-Health, Service-Freshness, Mirror/Backup-Alter
- **diagnos/integrity.py** — Energiebilanz-Rollups, Gap-Scan
- **diagnos/status_report.py** — Tagesbericht + Alarm-Mails (SMTP)

### Steuerbox (Rolle E)
- **steuerbox/** — Operator-Intent-API, zeitlich begrenzte Overrides, validiert, kein Hardware-Zugriff

### Netzqualität (Rolle N)
- **nq/collector/** — PAC4200 Modbus TCP read-only (RAM-first auf Pi4-Tech, tmpfs)
- **nq/aggregate/** — Transfer + Aggregation auf Pi5-Primary
- **nq/analysis/** — Spektralanalyse, Netzereignisse, Harmonische (HF/NF/VLF)

### Querschnitt
- **config.py** — Zentrale Konfiguration
- **scripts/** — GFS-Backup, monatlicher PDF-Versand, Install-Skripte

## Architektur (Vier-Host-Topologie)

```
 Feldgeräte                    Pi5-Primary (192.0.2.204)
 ┌──────────────────┐          ┌─────────────────────────────────┐
 │ Fronius GEN24    │ Modbus   │ Rolle A: pv-collector           │
 │ (Inv + 3× SM)   │◄────────►│ Rolle B: pv-web (Port 8000)     │
 └──────────────────┘   TCP   │ Rolle C: pv-automation          │
                               │ Rolle D: diagnos (Cron)         │
 ┌──────────────────┐          │ Rolle E: pv-steuerbox           │
 │ Fronius Wattpilot│   WS    │ Rolle N: NQ-Aggregation/Analyse  │
 │ (EV-Lader)       │◄────────►└─────────────────────────────────┘
 └──────────────────┘               │ rsync + Dienst-Sync
                                    │
 ┌──────────────────┐          ┌────┴────────────┬──────────────────┐
 │ Dimplex WP       │ Modbus   │ Pi4-Tech        │ Pi5-FB           │
 │ (Wärmepumpe)     │◄────────►│ WP/HW-Bridge    │ Failover +       │
 └──────────────────┘   RS485  │ NQ-Collector    │ Backup-Empfänger │
                               │ (pv-nq-*)       │ (read-only)      │
 ┌──────────────────┐          └─────────────────┴──────────────────┘
 │ PAC4200          │ Modbus        Pi4-Küche: Kiosk-Display + Longterm-GFS
 │ (Netzqualität)   │◄────────► Pi4-Tech
 └──────────────────┘
```

### ⚠️ Wichtig: W_AC_Inv ≠ PV-Erzeugung

W_AC_Inv ist der AC-Zähler des Hybrid-WR und inkludiert Batterie-Lade/Entladung.
Reine PV-Erzeugung = W_DC1 + W_DC2 + W_Exp_F2 + W_Exp_F3.

## Datenfluss

1. **Polling:** Alle 3 s Modbus-Read → RAM-Buffer → `raw_data` (Flush 60 s)
2. **Aggregation:** 5 Stufen via Cron (1 min / 15 min / hourly / daily / monthly)
3. **Persist:** tmpfs-DB → SD-Card (stündlich) + GFS-Backup-Host (täglich 03:00)
4. **NQ:** PAC4200-RAM-Collector (Pi4-Tech) → Transfer alle 4 h → Aggregation + Analyse (Pi5-Primary)
5. **Cleanup:** raw_data 7 d, data_1min/15min 90 d, hourly 365 d, daily/monthly 10 y

## Technische Spezifikation

- **Polling-Intervall:** 3 Sekunden
- **DB:** SQLite WAL-Mode in tmpfs (`/dev/shm/`)
- **Retention:** 7 d raw, 90 d 1 min/15 min, 365 d hourly, 10 y daily/monthly
- **Spalten:** ~96 (raw_data)
- **Namenskonvention:** `P_` (W), `W_` (Wh), `U_` (V), `I_` (A), `f_` (Hz)
- **Battery:** `P_Batt = P_DC_Inv - (P_DC1 + P_DC2)`, kein eigenes Modbus-Register

### ⚠️ WP ≠ Wattpilot — Namenskonvention

| Kürzel | Bedeutung | Quelle |
|--------|-----------|--------|
| **WP**, `P_WP`, `W_Imp_WP` | **Wärmepumpe** (Dimplex Heat Pump) | SmartMeter Unit 4 (Modbus) + Wärmemengenzähler |
| **Wattpilot** | **Wallbox / E-Auto-Lader** (Fronius) | Wattpilot WebSocket API |

`wp_` → Wärmepumpe, `wattpilot_` → Wallbox. Die Trennung ist im Code strikt eingehalten.

## Aggregations-Pipeline (Cron, Pi5-Primary)

```cron
* * * * *        python3 -m collector.aggregate.min1       # raw → 1min
0,15,30,45 * * * python3 -m collector.aggregate.fifteen    # raw → 15min → hourly
2,17,32,47 * * * python3 -m collector.aggregate.daily      # hourly → daily
6,21,36,51 * * * python3 -m collector.aggregate.monthly    # 15min → monthly
8,23,38,53 * * * python3 -m collector.aggregate.statistics # daily → monthly_stats → yearly
```

NQ-Aggregation, -Analyse und GFS-Backups laufen via systemd-Timer (`pv-nq-*.timer`, `pv-backup-gfs.timer`).

## API-Endpunkte (Auswahl)

**Seiten (HTML)**
- `GET /` — Flow-Dashboard
- `GET /monitoring` — Maschinenraum / Echtzeit
- `GET /verbraucher` — Verbraucher-Analyse
- `GET /erzeuger` — Erzeuger-Analyse
- `GET /netzqualitaet` — NQ-Dashboard
- `GET /analyse/batterie` — Batterie-Analyse
- `GET /analyse/pv` — PV-Analyse

**JSON-API**
- `GET /api/flow_realtime` — Live-Leistungsfluss (Flow-View)
- `GET /api/realtime_smart` — Zoom/Zeitreihen-Daten
- `GET /api/verbraucher` — Verbraucher-Tagesübersicht
- `GET /api/battery_status` — SOC + Automation-State
- `GET /api/wattpilot/status` — Wattpilot Live-State
- `GET /api/nq/energy/<period_type>/<period_key>` — NQ-Energiedaten
- `GET /api/system_info` — Host-Info + Service-Status
- `GET /api/failover_status` — Failover/Mirror-Status

## Monatlicher PDF-Bericht

`scripts/monthly_pdf_report.py` erzeugt und versendet automatisch einen PDF-Monatsbericht:

```bash
# Timer installieren
./scripts/install_monthly_pdf_timer.sh

# Manueller Test (kein Versand)
python3 scripts/monthly_pdf_report.py --dry-run --verbose
```

## Hardware

- **Inverter:** Fronius GEN24 12.0 (Modbus TCP, SunSpec + Fronius HTTP-API)
- **PV:** 37,59 kWp (3 Strings: S1 Süd 30°, S2 Nord 15°, S3 Süd 10°)
- **Battery:** BYD HVS 2×12,8 kWh parallel (25,6 kWh netto, LFP, 10 Module à 2,56 kWh)
- **Wärmepumpe:** Dimplex WP (Modbus RS485 via Pi4-Tech-Bridge, Wärmemengenzähler aktiv)
- **EV-Lader:** Fronius Wattpilot 22 kW (WebSocket)
- **Schaltsteckdosen:** Fritz!DECT (AHA-HTTP, Heizpatrone 2 kW, Klimaanlage)
- **Netzqualität:** Siemens PAC4200 (Modbus TCP, Pi4-Tech, Rolle N)

## Monitoring

```bash
# Service-Status
sudo systemctl status pv-collector pv-web pv-automation pv-steuerbox pv-wattpilot

# Logs
journalctl -u pv-collector -f
journalctl -u pv-automation -f

# Datenbank
ls -lh /dev/shm/data.db
sqlite3 /dev/shm/data.db "SELECT COUNT(*) FROM raw_data;"
```

## Wartung

```bash
# Single-Branch Workflow (nur main)
git pull origin main

# Datenbank-Backup (manuell)
cp /dev/shm/data.db data_backup_$(date +%Y%m%d_%H%M).db

# Multi-Host-Sync und Betriebsabläufe werden lokal dokumentiert.
```

## Recht & Compliance

Dokumentation und Schnittstellenbeschreibungen im Repo sind als eigene technische
Darstellung gedacht und dürfen keine kopierten Hersteller-Originalinhalte enthalten.
Vor externer Veröffentlichung gilt die Checkliste in
[doc/meta/VEROEFFENTLICHUNGSRICHTLINIE.md](doc/meta/VEROEFFENTLICHUNGSRICHTLINIE.md).

## Troubleshooting

**Problem:** Port 8000 bereits belegt
```bash
lsof -i :8000
sudo systemctl restart pv-web
```

**Problem:** Keine Daten / Collector hängt
```bash
journalctl -u pv-collector --since "5 min ago"
sudo systemctl restart pv-collector
```

**Problem:** Modbus-Verbindung prüfen
```bash
curl -s http://<inverter-host>/solar_api/v1/GetInverterRealtimeData.cgi
```

**Problem:** Aggregation läuft nicht
```bash
# Cron-Job prüfen
crontab -l
# Manuell ausfuehren
python3 -m collector.aggregate.fifteen
```

## Version

Siehe [CHANGELOG.md](CHANGELOG.md) für die vollständige Versionshistorie.

## Urheberschaft & KI-Einsatz

Dieses Projekt wurde als **Mensch-KI-Kollaboration** entwickelt. Der überwiegende Teil
des Codes (~85%) wurde von KI-Modellen generiert, gesteuert und validiert durch den Projektleiter.

| Phase | Modell | Beitrag |
|-------|--------|---------|
| Dez 2025 | **Google Gemini 2.0 Flash** | Basis-Modbus, erste DB-Schemata, Grundstruktur |
| Jan 2026 | **Anthropic Claude 3.5 Sonnet** | Aggregation-Pipeline, Web-API, UI-Grundlagen |
| Feb 2026 | **Anthropic Claude Opus 4** | Solar-Forecast/Geometry-Engine, Wattpilot, Architektur-Refactoring |
| Durchgehend | **GitHub Copilot** (Agent-Modus) | IDE-Integration, Multi-File-Edits, Git-Workflow |

**Projektleiter (Mensch):** System-Architektur, Hardware-Integration, Domänenwissen PV/Elektrotechnik,
Datenmodell-Design, Batterie-Strategien, UI/UX-Konzept, Qualitätssicherung, Betrieb.

> Detaillierte Beitragsanalyse (gepflegt): [doc/meta/KI_BEITRAGSANALYSE.md](doc/meta/KI_BEITRAGSANALYSE.md)
