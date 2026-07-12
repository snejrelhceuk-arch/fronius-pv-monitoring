---
title: NQ Transfer + Aggregationskaskade (Tech -> Primary)
domain: netzqualitaet
role: N
applyTo: "nq/transfer/**,nq/aggregate/**"
tags: [netzqualitaet, nq, transfer, aggregation, primary, rolle-n]
status: experimental
last_review: 2026-07-12
changes:
	- 2026-07-11: Modul NQ (Rolle N) angelegt; Transfer- + Aggregations-Skelette + Primary-Schema dokumentiert (Implementierung Phase 2).
	- 2026-07-11 (b): Energie-Differenzmethode + Zählervergleich ergänzt: `nq_energy_daily` (start/end/delta, Reset), `nq_energy_checkpoint`, `nq_ims_reading`, `nq_energy_compare` (PAC↔Master-SM↔iMS). GFS-Backup konsistent mit `scripts/backup_db_gfs.sh`. Doku: `doc/netzqualitaet/NQ_TESTS_UND_DB.md`.
---

# NQ Transfer + Aggregation

## Zweck
Übernahme der NQ-Daten von **Tech** (tmpfs) nach **Primary** (`192.0.2.204`, SD,
sparsam) und Aggregationskaskade analog zur Produktions-Pipeline. Tech exportiert
täglich nur das **3–10 s-Aggregat** + **Event-markierte RAW-Segmente**; Primary
fächert zu `5min → hourly → daily` auf und hält Event-RAW dauerhaft.

## Code-Anchor
- **Tech-Export:** `nq/transfer/nq_export_tech.py:run_export`
- **Primary-Ingest:** `nq/transfer/nq_ingest_primary.py:run_ingest`
- **Aggregationskaskade:** `nq/aggregate/nq_aggregate.py:run` (stage: `5min`|`hourly`|`daily`)
- **Schema (Primary):** `nq/schema/nq_primary_schema.sql`
- **Konfig (Retention/Transfer):** `config/nq_config.json`
- **Muster/Vorbild:** `collector/aggregate/`, Legacy `netzqualitaet/nq_export.py`

## Inputs / Outputs
- **Inputs:** Tech-`nq_agg_10s` (Vortag) + `nq_raw_*` mit `event=1`.
- **Outputs (Primary `nq/db/nq_YYYY-MM.db`):** `nq_agg_10s` (72 h), `nq_5min` (~90 d), `nq_hourly` (~365 d), `nq_daily` (~10 a), `nq_event_fast/medium/slow` (Originalauflösung, dauerhaft), Logs `nq_transfer_log`/`nq_ingest_log`.

## Invarianten
- **At-least-once:** Löschen der tmpfs-Zeilen auf Tech **erst nach Ingest-Quittung**.
- **Idempotenter Ingest:** doppelte Übernahme verändert das Ergebnis nicht (PKs, `INSERT OR REPLACE`/`ON CONFLICT`).
- NQ schreibt ausschließlich in `nq/db/` — **niemals** in `data.db`/Produktionstabellen.
- **Event-RAW wird nicht aggregiert** und dauerhaft aufbewahrt (Transienten-Rekonstruktion).
- Bucket-Grenzen über `localtime`; Monats-DB-Rotation wie Legacy `netzqualitaet/db/`.

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
