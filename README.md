# Fronius PV-Monitoring System

Production-ready Monitoring für Fronius Gen24 Hybrid PV-Anlage (37,59 kWp) mit BYD Battery Storage.

> **Systemdokumentation**: [doc/SYSTEM_ARCHITECTURE.md](doc/SYSTEM_ARCHITECTURE.md) — Energiefluss, Counter-Semantik, DB-Schema

## Produktionsstart
**01.01.2026 00:00 Uhr** | Pi4 (192.168.2.181) | CLI-Boot

## Schnellstart

System läuft als systemd-Services (pv-collector, pv-web). Kein manueller Start nötig.

```bash
# Status prüfen
sudo systemctl status pv-collector pv-web

# Browser
http://192.168.2.181:8000

# Logs
tail -f /tmp/modbus_v3.log
tail -f /tmp/aggregate_1min.log
```

## Komponenten

- **modbus_v3.py** — Modbus-Collector (3s Polling, Persist-Thread)
- **collector.py** — Thin Wrapper, startet poller_loop()
- **web_api.py** — Flask/Gunicorn Web-API (Port 8000)
- **aggregate_*.py** — 5-stufige Aggregation (via Cron)
- **modbus_quellen.py** — SunSpec Register-Definitionen
- **config.py** — Alle Konfiguration

## Architektur

```
 Fronius Gen24 (192.168.2.122:502)     Pi4 (192.168.2.181)
 ┌─────────────────────────┐           ┌──────────────────────────┐
 │ Unit 1: Inverter F1     │  Modbus   │ modbus_v3.py (Collector) │
 │ Unit 2: SM Netz         │◄────────► │   → RAM-Buffer           │
 │ Unit 3: SM F2           │   TCP     │   → /dev/shm/data.db     │
 │ Unit 4: SM WP (Wärmepumpe)│           │   → Persist → SD-Card    │
 │ Unit 6: SM F3           │           ├──────────────────────────┤
 └─────────────────────────┘           │ Cron: 5 Aggregations-    │
                                       │   Scripts (1min→yearly)  │
                                       ├──────────────────────────┤
                                       │ web_api.py (Port 8000)   │
                                       └──────────────────────────┘
```

### ⚠️ Wichtig: W_AC_Inv ≠ PV-Erzeugung

W_AC_Inv ist der AC-Zähler des Hybrid-WR und inkludiert Batterie-Lade/Entladung.
Reine PV-Erzeugung = W_DC1 + W_DC2 + W_Exp_F2 + W_Exp_F3.
Siehe [doc/SYSTEM_ARCHITECTURE.md](doc/SYSTEM_ARCHITECTURE.md) Abschnitt 2.

## Datenfluss

1. **Polling:** Alle 3s Modbus-Read → RAM-Buffer → raw_data (Flush 60s)
2. **Aggregation:** 5 Stufen via Cron (1min / 15min / hourly / daily / monthly)
3. **Persist:** tmpfs-DB → SD-Card (Stunde/Tag konfigurierbar)
4. **Cleanup:** raw_data 7d, data_1min 90d, hourly 365d, daily 10y

## Technische Spezifikation

- **Polling-Intervall:** 3 Sekunden
- **DB:** SQLite 3.45.1 WAL-Mode in tmpfs (/dev/shm/)
- **Retention:** 7d raw, 90d 1min/15min, 365d hourly, 10y daily/monthly
- **Spalten:** ~96 (raw_data)
- **Namenskonvention:** P_ (W), W_ (Wh), U_ (V), I_ (A), f_ (Hz)
- **Battery:** P_Batt = P_DC_Inv - (P_DC1 + P_DC2), kein Modbus-Register

### ⚠️ WP ≠ Wattpilot — Namenskonvention

| Kürzel | Bedeutung | Quelle |
|--------|-----------|--------|
| **WP**, P_WP, W_Imp_WP | **Wärmepumpe** (Heat Pump) | SmartMeter Unit 4 (Modbus) |
| **Wattpilot** | **Wallbox / E-Auto-Lader** | Fronius Wattpilot WebSocket API |

**WP steht IMMER für Wärmepumpe, NIE für Wattpilot!**
Variablen: `wp_` → Wärmepumpe, `wattpilot_` → Wallbox.
Siehe auch [doc/WATTPILOT_ARCHITECTURE.md](doc/WATTPILOT_ARCHITECTURE.md#wp-wattpilot-namenskonvention).

## Monitoring

```bash
# Prozess-Status
ps aux | grep modbus_v3

# Logs prüfen
tail -f /tmp/modbus_v3.log
tail -f /tmp/aggregate.log

# Datenbank-Größe
ls -lh data.db

# Zeilen-Count
sqlite3 data.db "SELECT COUNT(*) FROM raw_data;"
```

## Wartung

```bash
# Production-Version wiederherstellen
git checkout v1.0-production

# Entwicklungsversion
git checkout development

# Datenbank-Backup
cp data.db data_backup_$(date +%Y%m%d_%H%M).db
```

## Cron-Jobs

```cron
# === PV-System Aggregation (Pi4 Produktion) ===
* * * * *        aggregate_1min.py      # raw → 1min
0,15,30,45 * * * aggregate.py           # raw → 15min → hourly
2,17,32,47 * * * aggregate_daily.py     # hourly → daily
6,21,36,51 * * * aggregate_monthly.py   # 15min → monthly
8,23,38,53 * * * aggregate_statistics.py # daily → monthly_stats → yearly
```

## API-Endpunkte

- `GET /` - Dashboard (HTML)
- `GET /aggregates` - Min/Max-Ansicht (HTML)
- `GET /api/dashboard` - Summary (JSON)
- `GET /api/live` - Rohdaten (JSON)
- `GET /api/energy` - Energie-Akkumulatoren (JSON)
- `GET /api/15min` - 15min-Aggregate (JSON)
- `GET /api/hourly` - Stunden-Aggregate (JSON)
- `GET /api/daily` - Tages-Aggregate (JSON)

## Hardware

- **Inverter:** Fronius Symo Hybrid (192.168.2.122:502)
- **Units:** 1=Inv, 2=Netz, 3=F2, 4=WP, 6=F3
- **Battery:** BYD (via Fronius Storage API)
- **Protokoll:** SunSpec Modbus TCP

## Troubleshooting

**Problem:** Port 8000 bereits belegt
```bash
lsof -i :8000
pkill -f modbus_v3
```

**Problem:** Keine Daten
```bash
# Modbus-Connection testen
curl -s http://192.168.2.122/solar_api/v1/GetInverterRealtimeData.cgi
```

**Problem:** Aggregation läuft nicht
```bash
# Cron-Job prüfen
crontab -l
# Manuell ausführen
cd /home/admin/Documents/PVAnlage/pv-system && python3 aggregate.py
```

## Version

- **v6.1.0** (19.02.2026) - Solarweb-Import, Counter-Strategie, Frequenz-Infozeile, Scroll-Legende
- **v6.0.0** (16.02.2026) - Workspace-Cleanup, Solar-Forecast-Scaffold-Dokumentation
- **v5.0.0** (14.02.2026) - UI-Redesign, minimalistisches Design, Analysen
- **v4.0.0** - Batterie-Management, Aggregation-Pipeline
- **v3.0.0** - Blueprint-Refactoring, Wattpilot-Integration
- **v1.0-production** (30.12.2025) - Initial Production

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

> Detaillierte Beitragsanalyse: [doc/LEISTUNGSANTEILE_KI_BEDIENER.md](doc/LEISTUNGSANTEILE_KI_BEDIENER.md)
