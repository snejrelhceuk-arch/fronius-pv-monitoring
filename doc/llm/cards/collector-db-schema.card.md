---
title: DB-Schema (Tabellen, Schlüssel, Retention)
domain: collector
role: A
applyTo: "db_init.py"
tags: [db, schema, raw-data, aggregat]
status: stable
last_review: 2026-10-18
---

# DB-Schema

## Zweck
Schema-Übersicht der zentralen `data.db` (SQLite). Pflichttabellen, Aggregat-Pipeline-Tabellen, Nebengeräte-Tabellen, Retention-Politik. Ausgangspunkt für jede Datenfrage.

## Code-Anchor
- **Schema-Init:** `db_init.py` (Pflicht-Tabellen: `REQUIRED_TABLES = {raw_data, data_1min, daily_data}`)
- **DB-Helper:** `db_utils.py`
- **Schema-Quelle (SQL):** `doc/collector/schema/db_schema_v4_tech.sql`, `doc/collector/schema/db_schema_wattpilot.sql`
- **Retention-Konstanten:** `config.py` (`DATA_1MIN_RETENTION_DAYS=90` u. a.)
- **Stats-DB (permanent, separat):** `config.STATS_DB_PATH` (`data_stats.db`), Producer `tools/build_stats_db.py`, Tages-Archiv `scripts/stats_archive_daily.sh`, ATTACH via `db_utils.py`

## Inputs / Outputs
- **Inputs:** Modbus/HTTP-Werte vom Fronius-Collector (`raw_data`), FritzDECT (`fritzdect_readings`), Wattpilot (`wattpilot_readings`).
- **Outputs:** Aggregat-Tabellen für Web-API (Rolle B, read-only) und Reports.

## Tabellen (Stand 2026-05)
**Raw + Aggregat (PV-Kern):**
- `raw_data` — PK `ts`, ~96 Spalten, 3-s-Polling, ca. 20-min-Buffer im RAM; Retention **30 Tage** (`RAW_DATA_RETENTION_DAYS`, Pi5).
- `data_1min` — PK `ts`, P×t-Integration, Batterieaufteilung; Retention 90 Tage (`DATA_1MIN_RETENTION_DAYS`).
- `data_15min` — Buckets + Forecast/Clear-Sky-Overlay.
- `hourly_data` — stündliche min/max/avg.
- `daily_data` — Tages-Aggregate (~96 Spalten) + `*_start`/`*_end` Counter-Fixpunkte. Permanente Tages-WR-Aufteilung (netto, Wh): `W_PV_F1_total` (DC1+DC2), `W_PV_F2_total`, `W_PV_F3_total` — Quelle der Erzeuger-Ansicht (`/api/erzeuger/*`) unabhängig von der 90-T-Retention von `data_1min`/`data_15min`.
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

**Batterie-Gesundheit:**
- `battery_health_daily` — `day_ts` PK, `soh_pct`, `capacity_kwh`, `charge_kwh`, `discharge_kwh`, `full_cycles`, `updated_ts`. SOH-Historie (best-effort BMS-Live, träge fortgeschrieben) + intervallbezogene Vollzyklen (Σ Tagesladung / Nominal-Kapazität der Ausbaustufe). Producer `collector/aggregate/battery_health.py` (im Statistik-Cron-Takt).

**3-Stufen-Datenhaltung (Stufe 2 = `monitoring.db`, Stufe 3 = `analysis.db`, SD, permanent):**
- **Stufe 1 (RAM):** rollierende Hot-Tabellen (`raw_data` 30 T, `data_1min`/`data_15min` 90 T, `*_readings`, `hourly_data`) + Prognose +5 T. Permanente Tabellen (`daily_data`, `*_daily`, `forecast_daily`, `battery_health_daily`, `wattpilot_daily`) auf **120 T** begrenzt (`config.TIERED_*_RETENTION_DAYS`, `collector/poller.py:_cleanup_tiered`, korrelierter Delete gegen `analysis.db`). → RAM **konstant**.
- **Stufe 2 `monitoring.db`** (`config.STATS_DB_PATH`, `stats`-ATTACH): `data_5min_permanent` (5-min, Schema = `data_1min`), `fritzdect_5min_permanent` `(ts,device_id)`, `wattpilot_5min_permanent` `(ts)`. Tag-Charts/Lasten-Verlauf dauerhaft. Producer `tools/build_stats_db.py`; früher `data_stats.db` (jetzt eingefroren).
- **Stufe 3 `analysis.db`** (`ana`-ATTACH): `daily_data`, `data_monthly`, `monthly/yearly_statistics`, `*_daily`/`*_monthly`, `wattpilot_daily`, `battery_health_daily`, `forecast_daily`, `price_history` — volle Historie seit 2021. Producer/Sync `tools/build_tiered_dbs.py` (`--sync` Upsert bewahrt Historie), täglich via `scripts/sync_tiered_daily.sh`.
- **Read-Routing** (`config.TIERED_READS`): `db_utils._attach_tiered_ro` legt Shadow-Views an (`RAM ∪ analysis-nicht-in-RAM`) → API liest volle Historie aus `analysis.db`, laufender Tag aus RAM. Null Änderungen an den API-Lesestellen. Konsument Gerätetabellen: `routes/verbraucher.py:/api/verbraucher/tag`.
- Backup-Gleichbehandlung: `scripts/backup_tiered_dbs_gfs.sh` (GFS für beide SD-DBs). Human-Doku: `doc/system/TAGESDATEN_HALTBARKEIT.md`.

## Invarianten
- Pflichttabellen müssen existieren — `db_init.py` **prüft** `REQUIRED_TABLES` (kein CREATE der Kern-Tabellen); die Anlage erfolgt aus dem SQL-Schema (`doc/collector/schema/db_schema_v4_tech.sql`, `db_schema_1min.sql`). `db_init.py` legt nur Neben-/Forecast-Tabellen via `CREATE TABLE IF NOT EXISTS` an.
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
- **`battery_control_log`:** Doku erwähnte historisch eine solche Tabelle, **existiert aber nicht in `db_init.py`/SQL** und wird seit 2026-03 nicht mehr beschrieben. Der frühere Lese-Fallback in `pv-config.py`/`routes/system/` wurde 2026-05-29 entfernt.
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
