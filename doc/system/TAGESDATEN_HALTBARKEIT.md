# Tagesdaten-Haltbarkeit & DB-Aufteilung (RAW / STATS)

> **Status: DIAGNOSE + DESIGN (2026-07-02).** Antwort auf Task C.
> Kein Eingriff in die (stabile) Produktions-Pipeline ohne Freigabe.

## Diagnose: Warum keine Tagesdarstellung vor April?

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

**Migrationsschritte (empfohlen, gated):**
- S1: STATS-DB + Schema `data_5min_permanent` anlegen (`db_init.py`), Producer `collector/aggregate/`.
- S2: Archiv-Job + einmaliger Backfill der aktuell noch vorhandenen 90 Tage (bevor sie verfallen!) → sichert den heutigen Bestand ab 2026-04-03 dauerhaft.
- S3: Web-Endpunkt Tag-Chart um STATS-Fallback erweitern (`routes/`).
- S4: Backup/Failover-Sync um STATS-DB ergänzen.
- S5: erst danach `DATA_1MIN_RETENTION_DAYS` senken (RAM entlasten).

**Wichtig:** S2-Backfill zeitkritisch — jeder Tag Verzögerung verliert einen weiteren Tag der ältesten 1-min-Daten (rollierend). Rekonstruktion in die Vergangenheit (vor 2026-04-03) ist bewusst **nicht** vorgesehen (User-Entscheid).

## Pi4-Failover — Einsatzbereitschaft

Werkzeuge vorhanden: `scripts/failover_health_check.sh` (ping+API+Mirror-Age),
`scripts/failover_activate.sh`, `scripts/failover_set_mode.sh`, `routes/system/failover.py`.
Der Health-Check läuft **vom Failover Richtung Primary** — eine belastbare Aussage zu
„update-/neustart-/process-verified-sicher" erfordert eine **On-Host-Prüfung auf dem
Failover** (SSH, bewusst und verifiziert). Das ist eine Aktion auf einem zweiten
Produktionshost und wurde hier **nicht autonom** ausgeführt. Als eigener, verifizierter
Schritt in `doc/TODO.md` aufgenommen.
