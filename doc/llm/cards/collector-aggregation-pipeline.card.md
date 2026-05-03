---
title: Aggregation-Pipeline (raw → 1min → 15min → daily → monthly)
domain: collector
role: A
applyTo: "aggregate*.py"
tags: [aggregation, pipeline, cron, retention]
status: stable
last_review: 2026-05-03
---

# Aggregation-Pipeline

## Zweck
Verdichtet `raw_data` (3-s-Polling) in mehrere Aggregat-Stufen mit unterschiedlichen Retention-Strategien. Quelle für Web-API, Reports und Statistik-Korrekturen.

## Code-Anchor
- **1-Min-Aggregat:** `aggregate_1min.py` (jede Minute)
- **15-Min + Hourly:** `aggregate.py` (cron, 15-min-Tick)
- **Daily:** `aggregate_daily.py` (cron, gestaffelt nach `aggregate.py`)
- **Monthly (technisch):** `aggregate_monthly.py` (cron, gestaffelt nach `aggregate_daily.py`)
- **Statistik (kWh+Kosten):** `aggregate_statistics.py` (cron, gestaffelt nach `aggregate_monthly.py`)
- **Korrekturen:** `statistics_corrections.py` + `config/statistics_corrections.json`

## Pipeline-Reihenfolge
```
raw_data (3 s, RAM-Buffer)
   ↓ aggregate_1min.py (jede Minute)
data_1min  (Retention 90 d)
   ↓ aggregate.py (15-min-Tick)
data_15min  →  hourly_data
   ↓ aggregate_daily.py
daily_data (96 Spalten + *_start/*_end)
   ↓ aggregate_monthly.py
data_monthly (technisch, 76 Spalten min/max/avg)
   ↓ aggregate_statistics.py
monthly_statistics (permanent, kWh+Kosten)
   ↓
yearly_statistics (permanent)
```

_Konkrete Cron-Minuten liegen in der User-Crontab (nicht im Repo)._

## Inputs / Outputs
- **Inputs:** `raw_data`, vorhergehende Aggregat-Stufe.
- **Outputs:** jeweils nächste Stufe + Statistik-Korrekturen.

## Invarianten
- **Cron-Staffelung:** Skripte laufen zeitlich versetzt (Reihenfolge `aggregate_1min` → `aggregate` → `aggregate_daily` → `aggregate_monthly` → `aggregate_statistics`), damit jede Stufe auf konsistenten Vorgängerdaten arbeitet.
- **Backfill:** `aggregate_1min.py` prüft die letzten 10 min auf Lücken (`aggregate_1min.py:30–40`).
- **Counter-Fixpunkte:** `daily_data.*_start`/`*_end` für Drift-Korrektur (Vergleich mit Counter-Differenzen).
- **Permanenz:** `monthly_statistics`, `yearly_statistics` werden nicht überschrieben (Korrekturen nur additiv).

## No-Gos
- Keine direkten `INSERT`s in spätere Stufen außerhalb der Pipeline.
- Keine Vorzeichen-Inversionen in den Aggregat-Skripten ohne Test.

## Häufige Aufgaben
- Neue Bilanzgröße in 1-min-Aggregat aufnehmen → `aggregate_1min.py:Bilanz-Block` + Schema-Spalte.
- Daily-Spalte hinzufügen → `aggregate_daily.py` + `daily_data`-Schema in `db_init.py`.
- Statistik-Korrektur einrichten → `config/statistics_corrections.json` (Modi `fixed` für abgeschlossene Monate, `offset` für laufende).

## Bekannte Fallstricke
- **Statistics-Corrections** (`statistics_corrections.py`): Quellen sind `daily_data` (WP/Heizpatrone) und `wattpilot_daily` (Wallbox); falsche Schreibweise/Spaltennamen führen stillschweigend zu fehlenden Korrekturen (`statistics-corrections-note`).
- Backfill nur über die letzten 10 min — größere Lücken brauchen dedizierte Skripte (z. B. `scripts/backfill_forecast_15min.py`, `scripts/backfill_sunshine_hours.py`).
- Sunrise/Sunset-Forecast saisonal: ForecastCollector nutzt einen festen Bezug, der saisonal driften kann (offene Tech-Debt, `doc/TODO.md`).

## Verwandte Cards
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md)
- [`collector-fronius-collector.card.md`](./collector-fronius-collector.card.md)

## Human-Doku
- `doc/collector/AGGREGATION_PIPELINE.md`
- `doc/collector/STATISTICS_CORRECTIONS.md`
