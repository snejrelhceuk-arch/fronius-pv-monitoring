# Tagesdaten-Haltbarkeit & permanente 5-min-STATS-DB (IST-Zustand)

> **Status: UMGESETZT (2026-07-02).** Task C. Beschreibt den IST-Zustand.

## IST-Zustand (Kurzfassung)

- **Tag-Charts sind für den gesamten produktiven Zeitraum (ab 2026-01-01) verfügbar.**
- Quelle der Wahrheit für alte Tage: **`data_stats.db`** (SD, permanent), Tabelle
  **`data_5min_permanent`** (5-min-Downsample, Schema = `data_1min`).
- Die Web-API hängt `data_stats.db` **read-only** an (`db_utils.get_db_connection` →
  `ATTACH … AS stats`, `config.STATS_DB_PATH`). Die Tag-Endpunkte wählen die Tabelle
  über `routes/helpers.py:tag_table()`: `data_1min` (≤90 T) → `data_15min` →
  `stats.data_5min_permanent`.
- **Backfill** aus GFS-/Pi5-Backups: Jan 1 – Jul 2 (51 692 5-min-Zeilen; 5 Tage mit
  Lücken durch Collector-Ausfälle — bewusst toleriert). Werkzeug: `tools/build_stats_db.py`.
- **Fortschreibung:** Cron `20 0 * * *` → `scripts/stats_archive_daily.sh` archiviert den
  Vortag aus der RAM-DB und synct `data_stats.db` nach Pi5 + Failover.
- Die **RAM-DB bleibt klein** (unverändert 90 T Retention); die STATS-DB liegt auf SD
  und wird nur 1×/Tag beschrieben.

## Diagnose: Warum keine Tagesdarstellung vor April? (Ursprungsbefund)

**Belegt aus Code + Daten:**
- Tag-Chart-Quelle ist `data_1min` (1-min-Raster).
- Retention: `config.py:204 DATA_1MIN_RETENTION_DAYS = 90`. Gelöscht durch
  `collector/poller.py:cleanup_db()` → `DELETE FROM data_1min WHERE ts < now-90d`
  (läuft stündlich auf der RAM-DB `/dev/shm/fronius_data.db`, wird auf SD gespiegelt).
- Ältester `data_1min`-Datensatz (Messung 2026-07-02): **2026-04-03 19:34** — exakt
  „heute − 90 Tage". Der Chart-Cutoff „bis April" ist also **die 90-Tage-Retention**.

**Antworten auf die Fragen:**
- **Seit wann Tagesdarstellung möglich?** Rollierend die **letzten 90 Tage** (aktuell ab 2026-04-03).
- **Warum vorher nicht?** Die 1-min-Daten **verfallen** (Retention-Löschung) — sie sind **nicht** „nie vorhanden gewesen". Das System ist seit 1.1.26 produktiv, Jan–Mär existierten also, wurden aber nach 90 Tagen gelöscht.
- **Zeitlich begrenzt?** Ja, durch die Retention. `daily_data` (permanent, ~10 J) hat **keine Intraday-Auflösung** → daraus kein Tag-Chart.
- **Statistik/Analyse stabil & solarweb-abgeglichen:** stimmt — diese nutzen die permanenten Aggregate (`daily_data`, `monthly/yearly_statistics`), die **nicht** von der 90-Tage-Retention betroffen sind.
- **Haltbarkeit heute:** `data_1min`/`data_15min` = 90 T, `hourly_data` = 365 T, `daily_data`/`monthly`/`yearly` = permanent (`config.py:202-208`).

Solarweb zeigt Tag-Charts seit 5.11.2021 im **5-min-Raster**. Wir wollen die Tag-Darstellung **für die Zukunft permanent** — ohne die RAM-DB aufzublähen.

## Warum nicht einfach Retention hochsetzen?

`data_1min` = ~1440 Zeilen/Tag × ~34 Spalten. Bei permanent + RAM-DB (`/dev/shm`, tmpfs)
würde der aktive Speicher über Jahre stark wachsen → Ziel „RAM klein" verletzt. Deshalb
**Aufteilung** statt Retention-Verlängerung.

## Design: RAW-DB (RAM) + STATS-DB (SD)

**Prinzip:** aktive Hochfrequenz-Daten klein im RAM, permanente Analyse-/Tagesdaten getrennt auf SD, seltenes Schreiben.

```
/dev/shm/fronius_data.db   (RAW-DB, tmpfs)
   raw_data (7 T), data_1min (z.B. 14–90 T), data_15min …   → klein, schnell
        │  1×/Tag Archiv-Job (nachts, nach daily-Aggregation)
        ▼
<SD>/data_stats.db         (STATS-DB, permanent)
   data_5min_permanent  (5-min-Downsample wie solarweb, ~288 Zeilen/Tag)
   daily_data, monthly/yearly_statistics  (permanente Aggregate)
```

**Kernpunkte:**
1. **Neue Tabelle `data_5min_permanent`** in einer STATS-DB auf SD. Speist sich täglich aus `data_1min` (Downsample 1→5 min: Ø/min/max). ~288 Z/Tag × 10 J ≈ 1 Mio Zeilen → klein & permanent.
2. **Archiv-Job** (Rolle A) 1×/Tag nach der daily-Aggregation: gestrigen Tag aus `data_1min` → `data_5min_permanent` (idempotent, INSERT OR REPLACE je 5-min-Bucket). Damit **seltenes SD-Schreiben** (1×/Tag) statt Dauerlast.
3. **RAM klein halten:** `DATA_1MIN_RETENTION_DAYS` kann sogar **gesenkt** werden (z.B. 14–30 T), sobald der Tag-Chart für ältere Tage aus der STATS-DB liest.
4. **Web-Tag-Chart (Rolle B, read-only):** liest ≤ (Retention) Tage aus `data_1min` (1-min, feinsten), ältere Tage aus `data_5min_permanent` (5-min). Ein Fallback-Select, kein Schema-Bruch.
5. **Backup/Failsafe:** STATS-DB wird **parallel** zu den bestehenden Verfahren nach Pi5 (`PI5_BACKUP_*`) und zum Failover (`scripts/failover_sync_db.sh`) gesynct — additiv, ohne die bestehende `data.db`-Kette zu ändern.

**Umsetzung (IST, 2026-07-02):**
- S1 ✅ STATS-DB `data_stats.db` + `data_5min_permanent` (Schema=`data_1min`) via `tools/build_stats_db.py` (`_ensure_target`, WAL).
- S2 ✅ Backfill Jan 1 – Jul 2 aus Pi5-Backups (Feb-08-Snapshot `data_1min_old`+`data_1min`, monatlich 2026-04/2026-06, Live) → 51 692 Buckets. Täglicher Archiv-Job `scripts/stats_archive_daily.sh` (Cron `20 0 * * *`).
- S3 ✅ Web-Fallback: `db_utils.get_db_connection` ATTACH read-only, `routes/helpers.py:tag_table()`; verdrahtet in `routes/erzeuger.py`, `routes/verbraucher.py`, `routes/visualization.py` (Tag-Endpunkte).
- S4 ✅ Sync nach Pi5 + Failover im Archiv-Job (rsync, best-effort).
- S5 ⏳ optional: `DATA_1MIN_RETENTION_DAYS` senken (RAM entlasten) — bewusst offen, aktuell 90 T (siehe `doc/TODO.md`).

Rekonstruktion in die Vergangenheit (vor 2026-01-01) ist bewusst **nicht** vorgesehen (System erst ab 1.1.26 produktiv). Verbleibende Lücken (5 Tage) durch damalige Collector-Ausfälle sind toleriert.

## Pi4-Failover — Einsatzbereitschaft (IST 2026-07-02)

- **Erreichbar** (passwortloses SSH), **DB-Mirror aktuell** (`pv-mirror-sync`, data.db frisch), `.role=failover`, gleiche HW/Python (aarch64 / 3.13.5).
- **`data_stats.db` liegt auf dem Failover** (per Archiv-Job gesynct) → serviert nach Aktivierung ebenfalls die Tag-Charts.
- Werkzeuge: `scripts/failover_health_check.sh`, `failover_activate.sh`, `failover_set_mode.sh`, `routes/system/failover.py`.
- Weitere Einrichtungsschritte (venv-Provisionierung offline, Code-Sync) siehe eigener Abschnitt in `doc/TODO.md` bzw. `doc/system/FAILOVER_STATUS.md`.
