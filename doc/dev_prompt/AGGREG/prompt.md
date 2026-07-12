# Prompt: NQ-Aggregationskaskade (Tech → Primary, analog pv-system)

**Kontext:** Du arbeitest am pv-system (repo `{REPO_DIR}`,
branch `feat/reformation-wp-bridge`). Lies zuerst AGENTS.md vollständig. Dann:
- `doc/netzqualitaet/NQ_MODUL.md` §6 (Transfer + Kaskade)
- `doc/netzqualitaet/NQ_TESTS_UND_DB.md` §3–§8 (DB-Aufbau, Härtung, Status)
- `nq/schema/nq_tech_schema.sql` — Tech-Tabellen (nq_agg_10s, nq_raw_*)
- `nq/schema/nq_primary_schema.sql` — Primary-Tabellen (nq_5min, hourly, daily, energy)
- `nq/collector/nq_poller.py` — was bereits läuft und in nq_agg_10s schreibt
- `nq/transfer/nq_energy_rollup.py` — Vorbild: SSH-Fetch + Tages-Rollup (läuft)
- `nq/tech_read.py` — SSH-Fetch Tech→Primary read-only (läuft)
- `collector/aggregate/` — **Vorbild**: Produktions-Aggregationskaskade raw→1min→daily
- `aggregate_1min.py`, `aggregate_daily.py` — Produktions-Muster für Aggregate
- `scripts/backup_db_gfs.sh` — GFS-Backup-Muster (son/vater/großvater)
- `config/nq_config.json` — Retention-Parameter (agg10s_hours, 5min_days, ...)
- `doc/llm/cards/netzqualitaet-nq-aggregation.card.md`

---

## Was bereits läuft (2026-07-12)
- **Tech**: `pv-nq-poller.service` schreibt `nq_agg_10s` (35 Größen, min/avg/max,
  10-s-Raster) + `nq_raw_fast/medium` in `/dev/shm/nq_cache.db` (RAM-first)
- **Tech**: `pv-nq-energy.service` schreibt `nq_energy_raw` (Energiezähler, 60 s)
- **Primary**: `pv-nq-energy-rollup.timer` (00:05 täglich) → `nq_energy_daily` +
  `nq_energy_checkpoint` + `nq_energy_compare`
- **Primary**: `/api/nq/realtime_smart` liest Tech-`nq_agg_10s` live via SSH
  (Wide-Format wie `/api/realtime_smart`)

## Was noch fehlt — das ist deine Aufgabe

### 1. Täglicher Transfer nq_agg_10s: Tech tmpfs → Primary SD
Datei: `nq/transfer/nq_agg_transfer.py` (analog `nq_energy_rollup.py`)
- SSH-Fetch der `nq_agg_10s`-Zeilen des Vortags von Tech
- INSERT OR REPLACE in Primary-`nq_agg_10s` (Retention: 72 h)
- Löschen auf Tech erst nach Primary-Quittung (at-least-once)
- Protokoll: `nq_ingest_log` auf Primary
- Start: `python3 -m nq.transfer.nq_agg_transfer [--day YYYY-MM-DD]`
- Systemd-Timer: `pv-nq-agg-transfer.timer` (täglich 00:10, Persistent)
  → in `.gitignore` (real Betreiber-Pfad)

### 2. Aggregationskaskade auf Primary (analog Produktion)
Datei: `nq/aggregate/nq_aggregate.py` (Skelett → Implementierung)
Funktion: `run(stage)` für `5min` | `hourly` | `daily`

Regeln (wie Produktionskaskade `collector/aggregate/`):
- **5min** (`nq_5min`, Retention ~90 d):
  `nq_agg_10s → GROUP BY CAST(ts/300 AS INT)*300, quantity`
  → min(vmin), avg(vavg), max(vmax), sqrt(avg(vavg²)-avg(vavg)²) als vstd, sum(n)
- **hourly** (`nq_hourly`, Retention ~365 d): aus `nq_5min`
- **daily** (`nq_daily`, Retention ~10 a): aus `nq_hourly`
- **Energie**: Summe der `wh_imp_delta` / `wh_exp_delta` je Stufe aus `nq_energy_daily`
- Zeitbasis: `localtime` (wie Produktion), day-Key `YYYY-MM-DD`
- Retention-Enforcement: DELETE WHERE ts < now - X (nach config.json)
- Systemd-Service + Timer: `pv-nq-aggregate.service/.timer` (00:15 täglich)
  → gitignored

### 3. GFS-Backup der Primary-NQ-DB
Datei: `scripts/backup_nq_gfs.sh` (analog `backup_db_gfs.sh`)
- Quelle: `nq/db/nq_YYYY-MM.db` (aktuelle Monats-DB)
- Ziel: `backup/db/nq/{daily,weekly,monthly,yearly}/`
- Retention: DAILY_KEEP=7, WEEKLY_KEEP=5, MONTHLY_KEEP=12
- Integrität: gzip + `sqlite3 PRAGMA integrity_check` + Kerntabellen-Check
  (`nq_daily`, `nq_energy_daily`, `nq_agg_10s`)
- Offsite-Kopie: analog `rsync` nach Pi5-FB (wie bestehende GFS)
- Cron (Primary 03:00): nach Transfer + Aggregation

### 4. Fließender Übergang — „Aggregationen nachreichen vor Verfall"
Kritische Anforderung des Nutzers: Die `nq_agg_10s`-Daten auf Tech haben nur 72 h
Retention. Der tägliche Transfer muss deshalb **vor Ablauf** der 72 h geschehen.
Der Timer läuft täglich um 00:10 → deckt den Vortag ab (< 24 h alt, also sicher).
Für den initialen Auffüllbetrieb: `nq_agg_transfer.py --day YYYY-MM-DD` lässt
sich auch für frühere Tage aufrufen (solange in Tech-tmpfs noch Daten vorhanden).
Beim Primary-Start: `nq_aggregate.py daily` kann auch für mehrere Tage rückwirkend
laufen (idempotent via INSERT OR REPLACE).

### 5. Schema-Konsistenz (nq_agg_10s Skalare)
Der Poller schreibt Skalare mit `meas=''`, `phase=0`, `ord=0` (NOT-NULL-Pflicht
in WITHOUT-ROWID-Tabelle). Der Transfer und alle Aggregat-Queries müssen mit
diesem Muster filtern: `WHERE meas='' AND phase=0 AND ord=0` für Skalar-Abfragen.

---

## Architektur-Grenzen (Rolle N, nie verletzen)
- Kein Schreibpfad in `data.db`/Produktionstabellen
- Tech-SD nicht dauerhaft beschreiben (NQ-Nutzdaten immer tmpfs-only)
- Alle neuen systemd-Units mit real Betreiber-Pfad → `.gitignore` (wie pv-nq-energy)
- Alle Python-Module ohne hardkodierte Hostadressen
  (über ENV `PV_TECH_IP` / `config.NQ_TECH_IP`, wie bereits in `nq_energy_rollup.py`)

## Definition of Done
- `nq_agg_transfer.py` überträgt Vortags-`nq_agg_10s` Tech→Primary, idempotent
- `nq_aggregate.py run('5min'/'hourly'/'daily')` erzeugt korrekte Aggregate
  (min/avg/max/std), Retention greift, Energie-Summen konsistent
- `backup_nq_gfs.sh` läuft, Integrität geprüft, Offsite-Kopie vorhanden
- Systemd-Timers eingerichtet + enabled (00:10 Transfer, 00:15 Aggregat, 03:00 GFS)
- `python3 -m py_compile nq/aggregate/nq_aggregate.py` ok
- Doc-Check exit 0 (Cards `nq-aggregation` aktualisiert, last_review=heute)
- Kein Datenverlust: Agg-Transfer läuft < 72 h nach Poll-Zeitpunkt
