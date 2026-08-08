---
title: NQ Transfer + Aggregationskaskade (Tech -> Primary)
domain: netzqualitaet
role: N
applyTo: "nq/transfer/**,nq/aggregate/**"
tags: [netzqualitaet, nq, transfer, aggregation, primary, rolle-n]
status: stable
last_review: 2026-08-08
changes:
	- 2026-08-08 (SM-Korrektur Altlasten): Alle 8 PAC-Tage mit Abweichungen durch **SM-Werte überschrieben** (`nq/transfer/nq_energy_sm_correct.py`, einmaliges Dev-Tool): 2026-07-12/13 (Anlaufphase Export=0), 07-14 (96% Abweichung), 07-15 (2,2%), 08-04 (98%, Collector-Ausfall?), 08-05 (1,1%), 08-06 (0,2%), 08-07 (7,5% Export). Alle Tage jetzt `src='sm_corrected'`, Vergleich zeigt 0,0% Abweichung. **Ziel:** Baseline für zukünftige Beobachtung — neue Abweichungen >0,5% sind kritisch und weisen auf systematische Messfehler hin.
	- 2026-08-08 (Energie-Rollup randscharf + Rückwirkende Korrektur): `nq/transfer/nq_energy_rollup.py:rollup` nutzt jetzt `compute_daily_boundary` (Randwert-Interpolation auf Mitternacht, energieerhaltend); `fetch_tech_rows` holt mit `boundary_margin_s`-Rand (Bracketing); `master_sm_day` liest den **autoritativen** `daily_data`-Tagesfixpunkt (statt `data_1min`-Summe). Neu **`nq/transfer/nq_energy_recompute.py`**: korrigiert bestehende Fixpunkte rückwirkend per **aufeinanderfolgender day_start-Differenz** (`delta(D)=start(D+1)−start(D)`, produktionskonform wie `energy_checkpoints`), nur PAC-Zählertage (`src≠pv_backfill`), Reset-/Gültigkeits-Guard (0-Register-Anlaufphase), idempotent, Dry-Run-Default. Ausgeführt 2026-08-08 (Backup `backup/db/nq_pre_recompute_2026-08-08/`): 2026-07-13 Imp 883→2357 Wh (+1474 zurückgewonnen), Monats-/Jahres-Rollup neu. Validierung: saubere Tage PAC↔SM <1 %. Doku `doc/netzqualitaet/ENERGIE_FEHLERANALYSE_2026-08-08.md`.
	- 2026-08-06 (Musteranalyse-Datensatz-Tabelle): Neue Primary-Tabelle `nq_pattern_5min` (`nq/schema/nq_primary_schema.sql`) — residual-bereinigter Netz-Signaldatensatz (u_clean/u_meas je Phase, freq, pf, phi, i, du_int_max, origin). Erzeuger `nq/analysis/nq_pattern.py`.
	- 2026-08-06 (Fixpunkt-Backfill): Neues Einmal-Werkzeug `nq/transfer/nq_energy_backfill.py:backfill` — füllt die NQ-Energie-Fixpunkte (`nq_energy_daily`/`nq_energy_checkpoint` + Monats-/Jahres-Rollup) für den Zeitraum VOR PAC-Start read-only aus der Produktions-`daily_data` (`W_Imp/Exp_Netz_*` → `wh_imp/wh_exp`, `src='pv_backfill'`). Idempotent, Dry-Run-Default, echte PAC-Zeilen (`counter`) werden nie überschrieben. Ausgeführt 2026-08-06: 189 Tage (2026-01-01…07-11), Monate 01–07 + Jahr 2026.
	- 2026-08-06: Legacy-Verweis auf `nq/legacy/nq_export.py` umgestellt (Modul `netzqualitaet/` → `nq/legacy/` konsolidiert).
	- 2026-07-25 (Read-Seite 10s/5min): `nq/tech_read.py:fetch_agg` mergt jetzt Primary-`nq_5min` (vollständige Historie) + Techs Live-Rand statt entweder/oder — Techs `nq_5min` wird nach jedem Transfer geleert und deckt nur den Rand ab (`source=nq_5min_merged`). Neu `fetch_agg_fast`: 10-s-Aggregat direkt aus Techs `nq_raw_fast`/`nq_raw_medium` (~12 h RAM-Retention) via SSH-SQL + 5-min-Baseline aus Primary davor (`hires_start` markiert den 10-s-Beginn). Kein neuer Schreibpfad; Rolle N bleibt read-only.
	- 2026-07-14 (l): **10s-Architektur entfernt.** `nq/transfer/nq_agg_transfer.py` übernimmt jetzt `nq_5min` (Tech) statt `nq_agg_10s`; Primary-Retention auf `nq_5min` (`primary_5min_days`). `nq/aggregate/nq_aggregate.py` aggregiert bei Stage `5min` nur noch Harmonische (`nq_raw_slow -> nq_5min`), Skalare kommen bereits als 5-min-Buckets vom Tech-Collector.
	- 2026-07-14 (k): **NQ2 WP2 + WP4.** Fixpunkt-Zähler `nq_energy_monthly`/`nq_energy_yearly` + `nq_energy_rollup.rollup_month`/`rollup_year` (aus Tages-Deltas, idempotent) + Timer `pv-nq-energy-rollup-month`(1.§00:10)/`-year`(1.1.§00:10). **Transienten:** `nq/aggregate/nq_transients.py` (5-min-Fenster aus `nq_raw_fast` auf Tech → `nq_transient_5min`), `nq_agg_transfer` triggert Berechnung + übernimmt Zeilen. **Event-Pipeline** `nq/transfer/nq_event_transfer.py`: Sofort-Transfer der `event=1`-Schnipsel (pre/post-Window, max_duration_s=300), `derive_event`/`ingest_snippets` setzen `has_snippet`/`peak_*`/`severity`, Cooldown 120s + Ähnlichkeits-Dedup (<24h → kein Snippet), Log-Cap `event_max_count`=10000. Retention 72h→12h angeglichen.
	- 2026-07-12 (i): **Bugfix Harmonik-Pipeline + Prozess-Deployment.** `nq_raw_slow` fehlte im Primary-Schema → `nq_agg_transfer.transfer()` (INSERT) und `nq_aggregate._run_harm_5min()` (SELECT) brachen mit „no such table" ab; Tabelle in `nq_primary_schema.sql` ergänzt + Retention `primary_rawslow_hours` (12 h) in `_enforce_retention`. Doppelt einkopierten Alt-Block (tages-basierter Transfer nach dem `__main__`-Guard) aus `nq_agg_transfer.py` entfernt. Neue Timer `pv-nq-analysis` (Netzereignis-Analyse tägl. 00:30) + `pv-nq-primary-cap` (Event-Kappung 00:40) + rollenbewusster Installer `scripts/install_nq_services.sh`. Befund: auf Primary waren bisher nur `pv-nq-energy-rollup` installiert — Transfer/Aggregation liefen nie (nq_agg_10s leer trotz lebendem Tech-Collector).
	- 2026-07-13 (j): **NQ-Pipeline aktiviert + verifiziert.** `_tech_host` in `nq_agg_transfer.py` + `nq_energy_rollup.py` fällt jetzt auf `config.NQ_TECH_IP` zurück (wie `tech_read`), damit CLI-Läufe ohne `.infra.local`-Env den echten Tech-Host treffen. Alle 5 Primary-Timer via Installer enabled; Tech-Poller-Code war veraltet (kein `_slow_thread`) → `nq/`+`nq_config.json` per rsync deployt, `pv-nq-poller` neu gestartet; veraltete tmpfs-Tabellen `nq_raw_medium`/`nq_raw_slow` (`ts`→`ts_ms`) verworfen + neu angelegt (`nq_energy_raw` erhalten). End-to-end grün inkl. Harmonische (`nq_5min` meas≠'' = 144).
	- 2026-07-11: Modul NQ (Rolle N) angelegt; Transfer- + Aggregations-Skelette + Primary-Schema dokumentiert (Implementierung Phase 2).
	- 2026-07-11 (b): Energie-Differenzmethode + Zählervergleich ergänzt: `nq_energy_daily` (start/end/delta, Reset), `nq_energy_checkpoint`, `nq_ims_reading`, `nq_energy_compare` (PAC↔Master-SM↔iMS). GFS-Backup konsistent mit `scripts/backup_db_gfs.sh`. Doku: `doc/netzqualitaet/NQ_TESTS_UND_DB.md`.
	- 2026-07-12: **Phase 2 implementiert.** `nq/transfer/nq_agg_transfer.py` (SSH-Fetch nq_agg_10s Vortag → Primary, at-least-once, Retention 72 h, nq_ingest_log). `nq/aggregate/nq_aggregate.py:run(stage)` (5min/hourly/daily/all, min/avg/max/std, Retention gem. config, idempotent via INSERT OR REPLACE). `scripts/backup_nq_gfs.sh` (GFS daily/weekly/monthly, Integrität, Offsite Pi5-FB). Systemd-Timer pv-nq-agg-transfer (00:10) + pv-nq-aggregate (00:15) angelegt + .gitignore. Feldtest Block A 5 min dokumentiert (MESSTECHNIK.md §Feldtest-Ergebnisse).
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
- **Schema (Primary):** `nq/schema/nq_primary_schema.sql`
- **Konfig (Retention/Transfer):** `config/nq_config.json`
- **Muster/Vorbild:** `collector/aggregate/`, Legacy `nq/legacy/nq_export.py`

## Inputs / Outputs
- **Inputs:** Tech-`nq_5min` (Skalare) + `nq_raw_*` mit `event=1`.
- **Outputs (Primary `nq/db/nq_YYYY-MM.db`):** `nq_5min` (~90 d), `nq_hourly` (~365 d), `nq_daily` (~10 a), `nq_transient_5min` (5-min-Transienten), `nq_energy_daily`/`nq_energy_monthly`/`nq_energy_yearly` (Fixpunkt-Zähler), `nq_event_fast/medium/slow` + `nq_events` (Katalog, `has_snippet`/`peak_*`), Logs `nq_transfer_log`/`nq_ingest_log`.

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
