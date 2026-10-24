---
title: Aggregation-Pipeline (raw → 1min → 15min → daily → monthly)
domain: collector
role: A
applyTo: "collector/aggregate/**"
tags: [aggregation, pipeline, cron, retention]
status: stable
last_review: 2026-10-24
---

# Aggregation-Pipeline

## Zweck
Verdichtet `raw_data` (3-s-Polling) in mehrere Aggregat-Stufen mit unterschiedlichen Retention-Strategien. Quelle für Web-API, Reports und Statistik-Korrekturen.

## Code-Anchor
Alle Aggregate liegen seit Refactor 2026-05-16 im Paket `collector/aggregate/` und werden via `python3 -m collector.aggregate.<modul>` aufgerufen.
- **1-Min-Aggregat:** `collector/aggregate/min1.py` (jede Minute, inkl. 10-min-Backfill)
- **15-Min + Hourly:** `collector/aggregate/fifteen.py` (cron, 15-min-Tick)
- **Daily:** `collector/aggregate/daily.py`
- **Monthly (technisch):** `collector/aggregate/monthly.py`
- **Statistik (kWh+Kosten):** `collector/aggregate/statistics.py`
- **Batterie-Gesundheit (SOH + Vollzyklen):** `collector/aggregate/battery_health.py` (aus `statistics.py`-`__main__` mitgerufen; schreibt `battery_health_daily`)
- **Korrekturen:** `statistics_corrections.py` + `config/statistics_corrections.json`

## Pipeline-Reihenfolge
```
raw_data (3 s, RAM-Buffer)
   ↓ collector.aggregate.min1 (jede Minute)
data_1min  (Retention 90 d)
   ↓ collector.aggregate.fifteen (15-min-Tick)
data_15min  →  hourly_data
   ↓ collector.aggregate.daily
daily_data (96 Spalten + *_start/*_end)
   ↓ collector.aggregate.monthly
data_monthly (technisch, 76 Spalten min/max/avg)
   ↓ collector.aggregate.statistics
monthly_statistics (permanent, kWh+Kosten)
   ↓
yearly_statistics (permanent)
```

_Konkrete Cron-Minuten liegen in der User-Crontab (nicht im Repo)._

## Inputs / Outputs
- **Inputs:** `raw_data`, vorhergehende Aggregat-Stufe.
- **Outputs:** jeweils nächste Stufe + Statistik-Korrekturen.

## Invarianten
- **Cron-Staffelung:** Skripte laufen zeitlich versetzt (Reihenfolge `collector.aggregate.min1` → `fifteen` → `daily` → `monthly` → `statistics`), damit jede Stufe auf konsistenten Vorgaengerdaten arbeitet.
- **Backfill:** `collector/aggregate/min1.py` prueft die letzten 10 min auf Luecken.
- **Counter-Fixpunkte:** `daily_data.*_start`/`*_end` für Drift-Korrektur (Vergleich mit Counter-Differenzen).
- **Netzzähler ≥ 0:** `daily.py` normalisiert `W_Imp_Netz`/`W_Exp_Netz` nach dem Counter/Fallback-Schritt explizit auf `max(0.0, …)` — ein negatives Delta (Zähler-Reset/Init) darf `W_Consumption = PV + Imp − Exp` und `W_PV_Direct` nicht verfälschen (beide setzen positive Netzmengen voraus).
- **PV-Netto-Bilanz (2026-05-25):** `daily.py` rechnet `W_PV_total = DC1+DC2 + (Exp_F2−Imp_F2) + (Exp_F3−Imp_F3)`. Imp_F2/F3 = AC-Standby der WR (~0,2 % von Exp).
- **Permanente Tages-WR-Aufteilung:** `daily.py` schreibt zusätzlich `daily_data.W_PV_F1/F2/F3_total` (netto, Wh) aus dem besten Delta-Raster (`data_1min`→`data_15min`). Nicht-destruktiv: fehlt das Raster (alte Tage), bleiben bestehende Werte erhalten. Historie wird aus der permanenten `stats.data_5min_permanent` rekonstruiert (`tools/reconstruct_erzeuger_daily.py`, füllt nur NULL-Tage). Konsumenten: `/api/erzeuger/monat|jahr|gesamt`.
- **3-Stufen-Datenhaltung (RAM konstant):** Permanente Aggregat-Tabellen (`daily_data`, `*_daily`, `forecast_daily`, `battery_health_daily`, `wattpilot_daily`) liegen voll in `analysis.db` (SD, Stufe 3) und werden in der RAM-DB auf **120 T** begrenzt (`collector/poller.py:_cleanup_tiered`, korrelierter Delete gegen `analysis.db`). Im Tiered-Mode trimmt **ausschliesslich** dieser korrelierte Delete die `daily_data` (der nicht-korrelierte `RETENTION`-Pfad wird dann übersprungen) — es werden nur Zeilen gelöscht, die nachweislich in `analysis.db` gespiegelt sind. Täglicher spalten-selektiver Upsert `tools/build_tiered_dbs.py --sync` (`ON CONFLICT(pk) DO UPDATE` bei natürlichem PK → bewahrt Historie UND analysis-only-Spalten; `INSERT OR REPLACE` nur für `*_statistics` mit Surrogat-PK) via `scripts/sync_tiered_daily.sh` (mit WAL-Checkpoint vor dem rsync). 5-min-Verlauf → `monitoring.db` (Stufe 2). Shadow-Views (`db_utils.py:_attach_tiered_ro`) unionieren RAM- und analysis-Daten **spaltennamentlich** (nicht `SELECT *`) → schema-drift-sicher. **Leser mit Monats-/Jahr-/Gesamt-Horizont müssen `db_utils.get_db_connection_ro()` nutzen** (Shadow-Views), sonst sehen sie nur das 120-T-RAM-Fenster (stiller Minderausweis). **Aggregatoren** schreiben per RW (nur RAM, ohne Shadow-Views) → das `statistics.py`-3-Monats-Fenster muss `< TIERED_DAILY_RETENTION_DAYS` (120 T) bleiben. „RAM konstant" gilt für die hochfrequenten Aggregate; kleine Monats-/Statistik-Tabellen (`data_monthly`, `*_statistics`, `*_monthly`, `price_history`) werden im RAM nicht getrimmt (monatlich/klein, unkritisch). Details: `doc/system/TAGESDATEN_HALTBARKEIT.md`.
- **Counter-Konsistenz Monat (2026-05-25):** `statistics.py` speist `monthly_statistics` vorrangig aus `data_monthly`-Counter-Diffs (eichgenau); Fallback auf `SUM(daily_data)` bei Drift > 3 %/5 kWh oder bei Reset-verdacht (Sanity-Schwelle 5000 kWh/Monat).
- **Permanenz:** `monthly_statistics`, `yearly_statistics` werden nicht überschrieben (Korrekturen nur additiv).

## No-Gos
- Keine direkten `INSERT`s in spätere Stufen außerhalb der Pipeline.
- Keine Vorzeichen-Inversionen in den Aggregat-Skripten ohne Test.

## Häufige Aufgaben
- Neue Bilanzgroesse in 1-min-Aggregat aufnehmen → `collector/aggregate/min1.py` (Bilanz-Block) + Schema-Spalte.
- Daily-Spalte hinzufuegen → `collector/aggregate/daily.py` + `daily_data`-Schema in `db_init.py`.
- Statistik-Korrektur einrichten → `config/statistics_corrections.json` (Modi `fixed` für abgeschlossene Monate, `offset` für laufende).

## Bekannte Fallstricke
- **Fritz!DECT-Zähler-Freeze & generische Daily-Aggregation** (`daily.py` `_aggregate_fritzdect_device_daily`, Liste `FRITZDECT_DAILY_DEVICES`): Eine generische, abgesicherte Tagesaggregation schreibt `<gerät>_daily` (heizpatrone, klimaanlage, lueftung, gefriertruhe). Absicherungen: (a) Negativ-Guard `max(0, MAX−MIN)`; (b) Interday-Fallback bei Zähler-Freeze — nutzt den START-Zähler des Folgetags (`source='counter_interday'`), isolierte Freezes neben Normaltagen ergeben korrekt 0; (c) Zähler-basierter Fallback `_fill_fritzdect_daily_from_devstats` via Fritz-AHA `getbasicdevicestats` (~31 Tage Box-eigene Tagesenergie) ueber den neutralen Read-Helper `fritzdect_read.py`. Seit 2026-08-04 ist der Box-Tageswert **autoritativ**: er füllt 0/fehlende Tage **und korrigiert Partial-Freezes** (überschreibt `counter_auto`/`counter_interday`, wenn Box-Wert > Delta + max(50 Wh, 15%); `source='fritz_devstats'`). Geschützte Quellen (`manual`, `counter_interday_recon`) werden nicht überschrieben. Status-only-Geräte (fussbodenheizung: Thermostat ohne Leistungsmessung, `energy_total_wh` = konstanter Garbage-Wert) sind ausgeschlossen. Historische Freeze-Tage innerhalb der ~31-Tage-Box-Statistik werden vom autoritativen devstats-Fallback automatisch korrigiert; ältere Lücken (Box-Statistik weg) bleiben. Schreibziel ist die RAM-DB `/dev/shm/fronius_data.db`, danach `.backup data.db`.
- **Statistics-Corrections** (`statistics_corrections.py`): Quellen sind `daily_data` (WP/Heizpatrone) und `wattpilot_daily` (Wallbox); falsche Schreibweise/Spaltennamen führen stillschweigend zu fehlenden Korrekturen (`statistics-corrections-note`).
- Backfill nur über die letzten 10 min — größere Lücken brauchen dedizierte Backfill-Skripte (`tools/`/`scripts/`).
- Sunrise/Sunset-Forecast saisonal: ForecastCollector nutzt einen festen Bezug, der saisonal driften kann (offene Tech-Debt, `doc/TODO.md`).

## Verwandte Cards
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md)
- [`collector-fronius-collector.card.md`](./collector-fronius-collector.card.md)

## Human-Doku
- `doc/collector/AGGREGATION_PIPELINE.md`
- `doc/collector/STATISTICS_CORRECTIONS.md`
