"""collector.aggregate — Aggregations-Pipeline (Refactor 2026-05-16).

5-stufige Aggregation, wird per Cron aufgerufen:
  * * * * *      python3 -m collector.aggregate.min1        (raw_data -> data_1min, mit Backfill)
  0,15,30,45 *   python3 -m collector.aggregate.fifteen     (data_1min -> data_15min/hourly)
  5 * * * *      python3 -m collector.aggregate.daily       (hourly -> daily)
  8 * * * *      python3 -m collector.aggregate.monthly     (daily -> monthly)
  11 * * * *     python3 -m collector.aggregate.statistics  (monthly_statistics, yearly_statistics)

Vormals 5 lose Skripte im Repo-Root (aggregate*.py).
"""
