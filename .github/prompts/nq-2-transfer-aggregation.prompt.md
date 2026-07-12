---
mode: agent
description: "NQ Phase 2 — Transfer Tech→Primary (Event-RAW + 3-10s) + Aggregationskaskade auf Primary"
---

# NQ Phase 2 — Transfer + Aggregationskaskade (Tech → Primary)

Du bist Senior-Entwickler am **PV-System**, Rolle **N**. Hosts: **Tech** (Export) + **Primary** (Ingest/Aggregation).

## Pflichtlektüre zuerst
1. [`AGENTS.md`](../../AGENTS.md) — Rollen, No-Gos (Rolle N read-only ggü. Produktion; SD sparsam).
2. [`doc/netzqualitaet/NQ_MODUL.md`](../../doc/netzqualitaet/NQ_MODUL.md) — §6 (Transfer + Kaskade), §3 (Retention).
3. [`doc/llm/cards/netzqualitaet-nq-aggregation.card.md`](../../doc/llm/cards/netzqualitaet-nq-aggregation.card.md) — Invarianten, Anchor.
4. **Vorbild-Code (Muster übernehmen):**
   - [`collector/aggregate/`](../../collector/aggregate) — Kaskade raw → 1min → daily → monthly, Cron-Staffelung, min/avg/max.
   - Legacy [`netzqualitaet/nq_export.py`](../../netzqualitaet/nq_export.py) — read-only Monats-DB-Export-Muster.

## Ziel
1. **Tech-Export (1×/Tag):** nur `nq_agg_10s` (Vortag) + **Event-markierte RAW-Segmente** nach Primary transferieren. Löschen aus tmpfs **erst nach quittiertem Transfer** (At-least-once).
2. **Primary-Ingest:** Empfang in Monats-DB `nq/db/nq_YYYY-MM.db` (Schema [`nq/schema/nq_primary_schema.sql`](../../nq/schema/nq_primary_schema.sql)).
3. **Aggregationskaskade auf Primary:** `nq_agg_10s` → `nq_5min` → `nq_hourly` → `nq_daily`, jeweils min/avg/max(/std), Retention gem. [`config/nq_config.json`](../../config/nq_config.json). **Event-RAW** bleibt in Originalauflösung (`nq_event_*`).

## Zu implementierende Skelette (vorhanden, jetzt füllen)
- [`nq/transfer/nq_export_tech.py`](../../nq/transfer/nq_export_tech.py) — `run_export`.
- [`nq/transfer/nq_ingest_primary.py`](../../nq/transfer/nq_ingest_primary.py) — `run_ingest`.
- [`nq/aggregate/nq_aggregate.py`](../../nq/aggregate/nq_aggregate.py) — `run(stage)` für `5min`/`hourly`/`daily`.
- Nutze [`nq/nq_common.py`](../../nq/nq_common.py) für Config/DB.

## Fachliche Vorgaben
- **Transport über LAN** (Tech↔Primary). Batch klein (~1–2 MB/Tag Aggregat; Events selten). Kein Streaming nötig.
- **At-least-once + Idempotenz:** Ingest muss doppelte Übernahme tolerieren (PKs, `INSERT OR REPLACE`/`ON CONFLICT`). Erst nach Ingest-Quittung löscht Tech die transferierten tmpfs-Zeilen. Protokoll: `nq_transfer_log` (Tech) / `nq_ingest_log` (Primary).
- **Zeitbasis:** Bucket-Grenzen über `localtime` (konsistent mit Produktion). Daily-Key `YYYY-MM-DD`.
- **Monats-DB-Rotation:** neue Datei je Monat, Muster wie Legacy `netzqualitaet/db/`.
- **Retention-Enforcement** je Stufe (`primary_agg10s_hours`, `primary_5min_days`, `primary_hourly_days`, `primary_daily_days`).
- **Energie / Differenzmethode:** täglich `nq_energy_daily` aus den Tech-`nq_energy_raw`-Snapshots via `nq/collector/nq_energy.py:compute_daily` (start/end/delta + Reset-Erkennung) schreiben; `nq_energy_checkpoint` am day_start fixieren. Aggregation = **Summe der Deltas** (nicht min/avg/max). Siehe [`doc/netzqualitaet/NQ_TESTS_UND_DB.md`](../../doc/netzqualitaet/NQ_TESTS_UND_DB.md) §4.
- **Zählervergleich:** `nq_energy_compare` je Tag aus PAC (`nq_energy_daily`), Master-SM (Fronius Primär-SM `W_Imp/Exp_Netz`, **read-only** aus Produktions-DB) und iMS (`nq_ims_reading`, manuell). Abweichungen PAC−MasterSM / PAC−iMS ablegen (§5). **Wh_exp=0-Befund** im Blick behalten.
- **GFS-Backup** konsistent mit [`../../scripts/backup_db_gfs.sh`](../../scripts/backup_db_gfs.sh): `backup/db/nq/{daily,weekly,monthly,yearly}`, Retention 7/5/12, gzip + `integrity_check` (Kerntabellen `nq_daily`,`nq_energy_daily`,`nq_agg_10s`), Offsite-Kopie Pi5-FB, Cron 03:00 nach Ingest. Härtung s. NQ_TESTS_UND_DB §7.
- **Cron-Staffelung** analog Produktions-Aggregate (Ingest → 5min → hourly → daily → energy → compare → GFS nacheinander, nachts).

## Harte No-Gos
- Kein Schreibpfad in `data.db`/Produktionstabellen. NQ schreibt nur in `nq/db/`.
- Kein Löschen nicht-quittierter Daten auf Tech.
- Kein Verwerfen von Event-RAW (dauerhaft aufbewahren).
- Kein Refactor der Produktions-Aggregate; Muster nur nachbilden.

## Definition of Done
- `python3 -m nq.transfer.nq_export_tech` (Tech) + `python3 -m nq.transfer.nq_ingest_primary` (Primary) funktionieren End-to-End (lokaler Mock-Transfer im Test).
- `python3 -m nq.aggregate.nq_aggregate 5min|hourly|daily` erzeugt korrekte min/avg/max(/std)-Buckets, Retention greift.
- `nq_energy_daily` + `nq_energy_compare` werden täglich befüllt (Differenzmethode, Reset-Erkennung, Delta-Konsistenz `Σ(deltas)==end−start`).
- GFS-Backup läuft, integritätsgeprüft + Offsite-Kopie.
- Idempotenz + At-least-once nachgewiesen (Doppel-Ingest verändert Ergebnis nicht).
- Card [`netzqualitaet-nq-aggregation.card.md`](../../doc/llm/cards/netzqualitaet-nq-aggregation.card.md) aktualisiert (`last_review` heute, reale Anchor).
- Cron-Vorschläge dokumentiert (nicht scharf schalten ohne Freigabe).
