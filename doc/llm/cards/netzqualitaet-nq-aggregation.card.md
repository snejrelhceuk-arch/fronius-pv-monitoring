---
title: NQ Transfer + Aggregationskaskade (Tech -> Primary)
domain: netzqualitaet
role: N
applyTo: "nq/transfer/**,nq/aggregate/**"
tags: [netzqualitaet, nq, transfer, aggregation, primary, rolle-n]
status: stable
last_review: 2026-08-10
---

# NQ Transfer + Aggregation

## Zweck
Übernahme der NQ-Daten von **Tech** (tmpfs) nach **Primary** (`192.0.2.204`, SD,
sparsam) und Aggregationskaskade analog zur Produktions-Pipeline. Tech exportiert
das **5-min-Skalaraggregat** + **Event/Harmonik-RAW-Segmente**; Primary
fächert zu `hourly → daily` auf und hält Event-RAW dauerhaft.

## Code-Anchor
- **5-min-Transfer (Primary):** `nq/transfer/nq_agg_transfer.py:transfer` — SSH-Fetch Fenster, INSERT OR REPLACE, Tech-Delete nach Quittung, nq_ingest_log; triggert + übernimmt `nq_transient_5min`
- **Aggregationskaskade (Primary):** `nq/aggregate/nq_aggregate.py:run` (stage: `5min`|`hourly`|`daily`|`all`)
- **Transienten (Tech):** `nq/aggregate/nq_transients.py:run_tech` / `detect_transients_in_window` / `analyze_jumps`
- **Event-Schnipsel-Pipeline (Primary):** `nq/transfer/nq_event_transfer.py:transfer_events` / `derive_event` / `ingest_snippets` / `_cap_event_log`
- **GFS-Backup NQ-DB:** `scripts/backup_nq_gfs.sh` (daily/weekly/monthly, Integrität, Offsite rsync)
- **Energie-Rollup (Primary):** `nq/transfer/nq_energy_rollup.py:rollup` (tägl. 00:05, randscharf via `compute_daily_boundary`) / `rollup_month` / `rollup_year` / `master_sm_day` (autoritativer `daily_data`-Fixpunkt)
- **Energie-Fixpunkt-Recompute (rückwirkend, Primary):** `nq/transfer/nq_energy_recompute.py:recompute` (aufeinanderfolgende day_start-Differenz, `--apply`/Dry-Run)
- **SM-Korrektur Altlasten (einmalig Dev, Primary):** `nq/transfer/nq_energy_sm_correct.py:correct` (überschreibt PAC-Werte mit SM, `--threshold-pct`/`--min-abs-kwh`, `--apply`/Dry-Run, `src='sm_corrected'`)
- **Fixpunkt-Backfill (einmalig, Primary):** `nq/transfer/nq_energy_backfill.py:backfill` (PV-DB `daily_data` → NQ-Fixpunkte, `src='pv_backfill'`, Dry-Run-Default)
- **SM-Netzqualitaets-Backfill (einmalig, Primary):** `nq/transfer/nq_sm_backfill.py:backfill` (Backup-`data_15min` → `nq_sm_15min`, L-N→L-L ×√3, Merge Live→Archiv→Backups, `--commit`/Dry-Run-Default)
- **Speicher-Reclaim eingefrorener Monate (Primary):** `nq/aggregate/nq_prune_months.py:prune` (drop `nq_agg_10s`, delete `nq_raw_slow`, bedarfs-`VACUUM`; `--commit`/Dry-Run; taeglich via `nq_primary_cap`)
- **Schema (Primary):** `nq/schema/nq_primary_schema.sql`
- **Konfig (Retention/Transfer):** `config/nq_config.json`
- **Muster/Vorbild:** `collector/aggregate/`, Legacy `nq/legacy/nq_export.py`

## Inputs / Outputs
- **Inputs:** Tech-`nq_5min` (Skalare) + `nq_raw_*` mit `event=1`.
- **Outputs (Primary `nq/db/nq_YYYY-MM.db`):** `nq_5min` (~90 d), `nq_hourly` (~365 d), `nq_daily` (~10 a), `nq_transient_5min` (5-min-Transienten), `nq_energy_daily`/`nq_energy_monthly`/`nq_energy_yearly` (Fixpunkt-Zähler), `nq_sm_15min` (permanente SM-Netzqualitaets-Historie Vor-PAC, retention-frei), `nq_event_fast/medium/slow` + `nq_events` (Katalog, `has_snippet`/`peak_*`), Logs `nq_transfer_log`/`nq_ingest_log`.

## Invarianten
- **At-least-once:** Löschen der tmpfs-Zeilen auf Tech **erst nach Ingest-Quittung**.
- **Idempotenter Ingest:** doppelte Übernahme verändert das Ergebnis nicht (PKs, `INSERT OR REPLACE`/`ON CONFLICT`).
- NQ schreibt ausschließlich in `nq/db/` — **niemals** in `data.db`/Produktionstabellen.
- **Event-RAW wird nicht aggregiert** und dauerhaft aufbewahrt (Transienten-Rekonstruktion).
- Bucket-Grenzen über `localtime`; Monats-DB-Rotation wie Legacy `nq/legacy/db/`.

## No-Gos
- Kein Löschen nicht-quittierter Daten auf Tech.
- Kein voller RAW-Strom nach Primary (nur Aggregat + Events → SD-Schonung).
- Kein Refactor der Produktions-Aggregate; Muster nur nachbilden.

## Häufige Aufgaben
- Retention ändern → `config/nq_config.json` (`retention.primary_*`).
- Neue Stufe/Kennzahl → `nq_aggregate.py:run` + Tabelle in `nq/schema/nq_primary_schema.sql` (z. B. `vstd`).
- Transfer-Rhythmus ändern → `transfer.mode` + Cron-Staffelung (analog Produktion).

## Bekannte Fallstricke
- Ohne Idempotenz führen wiederholte Transfers zu Doppelzählung → immer PK-basiert upserten.
- Fehlt der tägliche Export/Ingest, bleiben Primary-Aggregate leer trotz Tech-Daten.
- Std/Spread nur berechnen, wo genug Samples (`n`) vorliegen.

## Verwandte Cards
- [`netzqualitaet-nq-collector.card.md`](./netzqualitaet-nq-collector.card.md)
- [`netzqualitaet-nq-analysis-events.card.md`](./netzqualitaet-nq-analysis-events.card.md)
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)

## Human-Doku
- `doc/netzqualitaet/NQ_MODUL.md` (§6)
- `.github/prompts/nq-2-transfer-aggregation.prompt.md`
