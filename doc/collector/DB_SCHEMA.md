# Datenbank-Schema (Stand: 1. März 2026)

> **Energiefluss-Modell und Counter-Semantik**: Siehe [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) Abschnitt 2.
> **⚠️ W_AC_Inv ≠ PV-Erzeugung!** W_AC_Inv inkludiert Batterie-Lade/Entladung.
> PV-Erzeugung = W_DC1 + W_DC2 + W_Exp_F2 + W_Exp_F3.

## Architektur

- **Primäre DB**: `/dev/shm/fronius_data.db` (tmpfs/RAM) — Echtzeit-R/W ohne Disk-I/O
- **Persist-Kopie**: `data.db` im Projektverzeichnis — zeitbasiert via `db_init.persist_to_disk()`
- **Forecast-Cache**: `solar_cache.db` — API-Antworten mit TTL (separat, nicht tmpfs)
- **Modus**: WAL (Write-Ahead Log), NORMAL sync, 64 MB Cache

## Tabellen-Übersicht

| Tabelle | Zeilen | Retention | Beschreibung |
|---------|--------|-----------|--------------|
| `raw_data` | ~180k | 7 Tage | 3s-Rohdaten (Modbus/API) |
| `data_1min` | ~52k | 90 Tage | 1-min-Aggregate (Tag-Chart) |
| `data_15min` | ~3.500 | 90 Tage | 15-min-Aggregate |
| `hourly_data` | ~870 | 365 Tage | Stunden-Aggregate |
| `daily_data` | ~44 | 10 Jahre | Tages-Aggregate |
| `data_monthly` | 3 | 10 Jahre | Monats-Aggregate (technisch) |
| `monthly_statistics` | 52 | permanent | Monatsstatistik (Kosten/Autarkie) |
| `yearly_statistics` | 6 | permanent | Jahres-Aggregate |
| `energy_checkpoints` | 33 | permanent | Absolute Zählerstände zu Rasterpunkten |
| `energy_state` | 14 | permanent | Key-Value-Store für Energiezähler |
| `forecast_daily` | — | 365 Tage | Tages-Prognose + Clear-Sky |
| `automation_log` | — | permanent | Automations-Protokoll (alle Aktoren) |
| `battery_control_log` | 16 | 90 Tage | Batterie-Steuerungsprotokoll (Legacy) |
| `system_info` | 1 | permanent | System-Metadaten |
| `wattpilot_readings` | ~5.300 | 90 Tage | Wallbox-Einzelmessungen |
| `wattpilot_daily` | 2 | 10 Jahre | Wallbox-Tagesaggregate |
| `price_history` | 3 | permanent | Stromtarife (ergänzend zu config.py) |
| `v_statistics_overview` | 58 | — | View: Monats+Jahresstatistiken |

## Aggregations-Pipeline

```
raw_data (3s, Modbus)
    │
    ├─► data_1min    (aggregate_1min.py, jede Minute)
    │       │
    │       ├─► data_15min      (aggregate.py, alle 15 min)
    │       │       │
    │       │       └─► hourly_data     (aggregate.py)
    │       │
    │       └─► daily_data      (aggregate_daily.py, Min 2/17/32/47)
    │               │
    │               ├─► data_monthly           (aggregate_monthly.py, 1. des Monats)
    │               └─► monthly_statistics     (aggregate_statistics.py)
    │                       │
    │                       └─► yearly_statistics
    │
    └─► energy_checkpoints  (33 Altdaten, wird NICHT aktiv befüllt)
```

## Schlüssel-Tabellen im Detail

### raw_data (96 Spalten)
Primärschlüssel `ts` (Unix-Timestamp). Alle Modbus-Register + API-Werte im 3s-Takt:
- Inverter: P_AC, I_L1–L3, U_L1–L3, P_DC, P_DC1/DC2
- Batterie: SOC, U_Batt, I_Batt
- Netz (SmartMeter): P_Netz, f_Netz, U_L1–L3
- Strings: P_F2, P_F3 (Fronius SmartMeter Unit 2/3)
- Wärmepumpe: P_WP (SmartMeter Unit 4)
- Energiezähler: W_AC_Inv, W_DC1, W_DC2, W_Exp/Imp_Netz, W_Exp/Imp_F2/F3, W_Imp_WP

### data_1min
Wie raw_data, aber aggregiert auf 1 min: `_avg`, `_min`, `_max` pro Messwert, ergänzt um:
- Energie-Deltas: W_Ertrag, W_Einspeis, W_Bezug, W_inBatt, W_outBatt, W_Direct, W_Verbrauch
- Leistungsaufteilung: P_Exp, P_Imp, P_inBatt, P_outBatt, P_Direct, P_inBatt_PV, P_inBatt_Grid
- Zählerstandsgrenzen: W_*_start, W_*_end

### data_15min (Forecast/ Clear-Sky)
Zusatzspalten fuer Prognose-Overlays (90 Tage Retention):
- `P_PV_FC_avg`, `W_PV_FC_delta` (Forecast-Leistung/15min-Energie)
- `P_PV_CS_avg`, `W_PV_CS_delta` (Clear-Sky-Leistung/15min-Energie)

### forecast_daily
Persistiert Tages-Prognosen und Clear-Sky für historischen Vergleich im Tag-Chart:
- `date` (PK): YYYY-MM-DD
- Zusammenfassung: expected_kwh, clearsky_kwh, quality, weather, Temperatur
- Stündliche Profile als JSON: hourly_profile, clearsky_profile
- Nachträglich: actual_kwh (für Accuracy-Tracking)

### energy_checkpoints
Absolute Zählerstände zu definierten Zeitpunkten (Stunde, Tag, Monat, Jahr).
Ermöglicht exakte Delta-Berechnung auch über Lücken hinweg.

## Datenquellen je Tabelle

| Tabelle | Schreiber | Leser |
|---------|-----------|-------|
| `raw_data` | collector.py (Modbus) | aggregate_1min.py |
| `data_1min` | aggregate_1min.py | web_api.py (Tag-Chart), aggregate_daily.py |
| `daily_data` | aggregate_daily.py | web_api.py, aggregate_monthly.py |
| `forecast_daily` | web_api.py (lazy), Cron | web_api.py (Tag-Chart) |
| `monthly_statistics` | aggregate_statistics.py | web_api.py (Analyse) |
| `automation_log` | actuator.py (Engine) | web_api.py (Dashboard) |
| `wattpilot_readings` | wattpilot_collector.py | web_api.py |

## Externe Datenquellen

- **Open-Meteo API** → `solar_cache.db` (TTL-Cache) → `forecast_daily` (persistent)
- **Solar-Geometrie-Engine** → Clear-Sky auf Basis von String-Konfiguration (on-the-fly + persistent)

## Automation RAM-DB

**Pfad:** `/dev/shm/automation_obs.db` (tmpfs)

Genutzt von `pv-automation.service` für flüchtigen Zustand:

| Tabelle | Inhalt |
|---------|--------|
| `obs_state` | Aktueller System-Snapshot (1 Zeile) |
| `obs_history` | Ring-Puffer vergangener Snapshots (max 1000) |
| `param_matrix` | Aktive Parametermatrix |
| `action_plan` | Letzter Engine-Aktionsplan |
| `heartbeat` | Service-Heartbeat |

## Dateien

- `db_init.py` — tmpfs-DB Initialisierung, Persist-Thread
- `db_utils.py` — `get_db_connection()` mit WAL-Modus
- `config.py` — Pfade, Retention Policies
