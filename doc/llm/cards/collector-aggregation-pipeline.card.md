---
title: Aggregation-Pipeline (raw → 1min → 15min → daily → monthly)
domain: collector
role: A
applyTo: "collector/aggregate/**"
tags: [aggregation, pipeline, cron, retention]
status: stable
last_review: 2026-08-04
---

# Aggregation-Pipeline

## Changes
- 2026-06-20 (b): `collector/aggregate/daily.py` schreibt neu `daily_data.P_PV_total_max` = zeitgleicher System-Peak `MAX(P_DC1_avg+P_DC2_avg+P_F2_avg+P_F3_avg)` aus data_1min (Fallback data_15min) via additivem UPDATE nach dem INSERT (Schritt 7b). Grund: `P_AC_Inv_max` ist nur F1 (HW-Limit ~12 kW), nicht der Anlagen-Peak. Backfill der Bestandsdaten erfolgte einmalig.
- 2026-06-20: `collector/aggregate/min1.py` aggregiert jetzt Leistungsfaktor (cos φ): `PF_Netz_avg/min/max` + `PF_Inv_avg/min/max` in `data_1min` (aus `raw_data.PF_Netz`/`PF_Inv`). SELECT-Spaltenzahl 83→89 (PF an Index 83–88 angehängt, bestehende Indizes unverändert), Count-Check + INSERT erweitert. Schema: `doc/collector/schema/db_schema_1min.sql` + Migration in `db_init.py`. Kein Backfill (raw_data ≤7 Tage); wirkt ab nächstem Collector-Lauf. Downstream-Rollup (15min/daily/monthly) noch offen.

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
- **PV-Netto-Bilanz (2026-05-25):** `daily.py` rechnet `W_PV_total = DC1+DC2 + (Exp_F2−Imp_F2) + (Exp_F3−Imp_F3)`. Imp_F2/F3 = AC-Standby der WR (~0,2 % von Exp).
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
- **Fritz!DECT-Zähler-Freeze & generische Daily-Aggregation** (`daily.py` `_aggregate_fritzdect_device_daily`, Liste `FRITZDECT_DAILY_DEVICES`): Eine generische, abgesicherte Tagesaggregation schreibt `<gerät>_daily` (heizpatrone, klimaanlage, lueftung, gefriertruhe). Absicherungen: (a) Negativ-Guard `max(0, MAX−MIN)`; (b) Interday-Fallback bei Zähler-Freeze — nutzt den START-Zähler des Folgetags (`source='counter_interday'`), isolierte Freezes neben Normaltagen ergeben korrekt 0; (c) Zähler-basierter Fallback `_fill_fritzdect_daily_from_devstats` via Fritz-AHA `getbasicdevicestats` (~31 Tage Box-eigene Tagesenergie). Seit 2026-08-04 ist der Box-Tageswert **autoritativ**: er füllt 0/fehlende Tage **und korrigiert Partial-Freezes** (überschreibt `counter_auto`/`counter_interday`, wenn Box-Wert > Delta + max(50 Wh, 15%); `source='fritz_devstats'`). Geschützte Quellen (`manual`, `counter_interday_recon`) werden nicht überschrieben. Status-only-Geräte (fussbodenheizung: Thermostat ohne Leistungsmessung, `energy_total_wh` = konstanter Garbage-Wert) sind ausgeschlossen. Historische Freeze-Tage innerhalb der ~31-Tage-Box-Statistik werden vom autoritativen devstats-Fallback automatisch korrigiert; ältere Lücken (Box-Statistik weg) bleiben. Schreibziel ist die RAM-DB `/dev/shm/fronius_data.db`, danach `.backup data.db`.
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
