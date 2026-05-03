---
title: DB-Schema (Tabellen, Schlüssel, Retention)
domain: collector
role: A
applyTo: "db_init.py"
tags: [db, schema, raw-data, aggregat]
status: stable
last_review: 2026-05-03
---

# DB-Schema

## Zweck
Schema-Übersicht der zentralen `data.db` (SQLite). Pflichttabellen, Aggregat-Pipeline-Tabellen, Nebengeräte-Tabellen, Retention-Politik. Ausgangspunkt für jede Datenfrage.

## Code-Anchor
- **Schema-Init:** `db_init.py` (Pflicht-Tabellen: `REQUIRED_TABLES = {raw_data, data_1min, daily_data}`)
- **DB-Helper:** `db_utils.py`
- **Schema-Quelle (SQL):** `doc/collector/schema/db_schema_v4_tech.sql`, `doc/collector/schema/db_schema_wattpilot.sql`
- **Retention-Konstanten:** `config.py` (`DATA_1MIN_RETENTION_DAYS=90` u. a.)

## Inputs / Outputs
- **Inputs:** Modbus/HTTP-Werte vom Fronius-Collector (`raw_data`), FritzDECT (`fritzdect_readings`), Wattpilot (`wattpilot_readings`).
- **Outputs:** Aggregat-Tabellen für Web-API (Rolle B, read-only) und Reports.

## Tabellen (Stand 2026-05)
**Raw + Aggregat (PV-Kern):**
- `raw_data` — PK `ts`, ~96 Spalten, 3-s-Polling, ca. 20-min-Buffer im RAM.
- `data_1min` — PK `ts`, P×t-Integration, Batterieaufteilung; Retention 90 Tage (`DATA_1MIN_RETENTION_DAYS`).
- `data_15min` — Buckets + Forecast/Clear-Sky-Overlay.
- `hourly_data` — stündliche min/max/avg.
- `daily_data` — Tages-Aggregate (~96 Spalten) + `*_start`/`*_end` Counter-Fixpunkte.
- `data_monthly` — 76 Spalten min/max/avg (technisches Monitoring).
- `monthly_statistics` — 17 Spalten (kWh+Kosten, **permanent**).
- `yearly_statistics` — 18 Spalten (**permanent**).

**Nebengeräte:**
- `fritzdect_readings` — `ts`, `device_id`, `ain`, `name`, `power_mw`, `power_w`, `state`, `energy_total_wh`.
- `wattpilot_readings` — `ts`, `energy_total_wh` (`eto`), `power_w`, `car_state`, `session_wh`, `temp`, `phase_mode`, `amp`, `trx`, `lmo`, `frc`.
- `wattpilot_daily` — `energy_wh` = Delta(`eto` Tagesanfang→ende).

**Forecast:**
- `forecast_daily` — Tages-Prognose-Werte (`db_init.py:552–618`).

**Automation:**
- `automation_log` — Aktor-Resultate (geschrieben durch `automation/engine/actuator.py`).

## Invarianten
- Pflichttabellen müssen existieren — `db_init.py` legt sie an, prüft `REQUIRED_TABLES`.
- `monthly_statistics`/`yearly_statistics` sind **permanent** — kein Löschen, keine Retention.
- `data_1min` Retention 90 Tage; ältere Daten via Aggregat-Pipeline in `daily_data` archiviert.
- Counter-Felder (`*_start`/`*_end` in `daily_data`): Fixpunkte zur Drift-Korrektur.

## No-Gos
- Keine direkten Schreibzugriffe der Web-API (Rolle B) auf `data.db`.
- Keine `INSERT`s in `monthly_statistics`/`yearly_statistics` außerhalb der Statistik-Pipeline.
- Keine Schema-Änderung ohne Migration (siehe `db_init.py` Migrationspfade).

## Häufige Aufgaben
- Neue Spalte in `raw_data` → `db_init.py` Schema-Block + Migration + Collector-Producer.
- Retention prüfen → `config.py` Konstanten + Pipeline-Skripte.
- Schema-Vergleich → SQL-Dateien in `doc/collector/schema/`.

## Bekannte Fallstricke
- **`battery_control_log`:** Doku erwähnte historisch eine solche Tabelle, **existiert aber nicht in `db_init.py`/SQL**. Code (`pv-config.py`, `routes/system.py`) liest sie noch — Reader-Cleanup ist offene Tech-Debt (`doc/TODO.md`).
- **`automation_log` vs. `battery_control_log`:** `automation_log` ist die aktive Persist-Tabelle für Aktor-Resultate.
- `W_AC_Inv` ≠ PV-Erzeugung (siehe `collector-feldnamen-referenz.card.md`) — beim Schema lesen die Semantik beachten.
- WAL-Modus: `db_utils.py` aktiviert WAL; lange Schreibvorgänge können Lese-Locks verlängern.

## Verwandte Cards
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md)
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)
- [`collector-fronius-collector.card.md`](./collector-fronius-collector.card.md)
- [`collector-wattpilot-collector.card.md`](./collector-wattpilot-collector.card.md)
- [`collector-fritzdect-collector.card.md`](./collector-fritzdect-collector.card.md)

## Human-Doku
- `doc/collector/DB_SCHEMA.md`
- `doc/collector/schema/*.sql`
