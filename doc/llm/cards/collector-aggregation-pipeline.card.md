---
title: Aggregation-Pipeline (raw → 1min → 15min → daily → monthly)
domain: collector
role: A
applyTo: "collector/aggregate/**"
tags: [aggregation, pipeline, cron, retention]
status: stable
last_review: 2026-05-16
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
- **Permanenz:** `monthly_statistics`, `yearly_statistics` werden nicht überschrieben (Korrekturen nur additiv).

## No-Gos
- Keine direkten `INSERT`s in spätere Stufen außerhalb der Pipeline.
- Keine Vorzeichen-Inversionen in den Aggregat-Skripten ohne Test.

## Häufige Aufgaben
- Neue Bilanzgroesse in 1-min-Aggregat aufnehmen → `collector/aggregate/min1.py` (Bilanz-Block) + Schema-Spalte.
- Daily-Spalte hinzufuegen → `collector/aggregate/daily.py` + `daily_data`-Schema in `db_init.py`.
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
