---
title: Dynamischer Börsentarif — Spot-Erfassung + Kostenaggregation
domain: collector
role: A
applyTo: "collector/dynamic_price.py"
tags: [tarif, strompreis, spot, epex, day-ahead, tibber, netzentgelt, energy-charts]
status: stable
last_review: 2026-11-16
---

# Dynamischer Börsentarif — Collector + Kostenmodell

## Zweck
Erfasst die realen **EPEX Day-Ahead Spot-Preise** (DE-LU, 15-min) und verrechnet
sie mit dem gemessenen 15-min-Netzbezug zu den **realen Gesamtkosten einer kWh**
(verbrauchsgewichtet, Tag/Monat/Jahr). Grundlage für den Tarifvergleich
„dynamisch (Tibber-Schiene) vs. Fixtarif" (Analyse-Seite, Rolle B).

## Kostenmodell (`dynamic_tariff.py`, cross-role)
`Gesamt_brutto(ct/kWh) = (Börse_ct + Σ feste_netto_adder_ct) × (1 + MwSt.)`.
Börse = einziger variabler Anteil (EUR/MWh ÷ 10 = ct/kWh). Feste Netto-Adder aus
`config.DYN_TARIF` (Stand 2026): Netzentgelt MITNETZ NS SLP 6,31 ct · Konzession
1,32 · KWKG 0,446 · Offshore 0,941 · §19 StromNEV 1,559 · Stromsteuer 2,05 ·
Tibber-Aufschlag 2,15 → 14,776 ct/kWh netto; MwSt 19 %. Fixkosten (Grundgebühren,
Messstellenbetrieb) separat via `dyn_fixkosten_eur_monat()`.

## Datenquelle
`api.energy-charts.info/price?bzn=DE-LU` (Fraunhofer ISE, CC BY 4.0, kein Key),
96×15-min/Tag, EUR/MWh. Rate-Limit: 1,5 s/Block + Retry-Backoff (HTTP 429).
Ganz 2026 liegt in 15-min-Auflösung vor.

## Code-Anchor
- **Kostenmodell:** `dynamic_tariff.py:total_price_ct`,
  `dynamic_tariff.py:components_breakdown_ct`, `dynamic_tariff.py:dyn_fixkosten_eur_monat`,
  `dynamic_tariff.py:fixtarif_ct`
- **Spot-Collector:** `collector/dynamic_price.py:fetch_prices`,
  `collector/dynamic_price.py:store`, `collector/dynamic_price.py:run`
- **Aggregation:** `collector/aggregate/tariff_cost.py:aggregate_day`,
  `collector/aggregate/tariff_cost.py:rebuild_monthly`,
  `collector/aggregate/tariff_cost.py:rebuild_yearly`
- **Rückrekonstruktion:** `tools/backfill_dynamic_price.py`
- **Config:** `config.py` (`DYN_TARIF`, `DYN_TARIF_START`)
- **Schema:** `db_init.py` (`spot_price_15min`, `tariff_cost_daily/monthly/yearly`),
  `doc/collector/schema/db_schema_v4_tech.sql`
- **Scheduling:** `scripts/dynamic_price_update.sh`,
  `config/systemd/pv-dynamic-price.timer`, `scripts/install_maintenance_timers.sh`

## Inputs / Outputs
- **Inputs:** energy-charts HTTP (Spot); `monitoring.db.data_5min_permanent.W_Bezug`
  (gemessener 15-min-Netzbezug, read-only); `config.DYN_TARIF`.
- **Outputs:** `spot_price_15min` (EUR/MWh, permanent) + `tariff_cost_{daily,monthly,yearly}`
  in `config.DB_PATH` (RAM) → nächtlicher Tiered-Sync nach `analysis.db`.

## Invarianten
- Rolle A: schreibt NUR die eigenen Tarif-Tabellen. Kein Hardware-/Aktor-Zugriff,
  read-only ggü. Messdaten (`W_Bezug`).
- `dyn_avg_ct` = Σ(Bezug×Gesamtpreis)/Σ Bezug (verbrauchsgewichtet, brutto);
  `dyn_simple_avg_ct` = Zeit-Mittel. Bei Bezug=0 fällt `dyn_avg_ct` auf das Zeit-Mittel.
- Idempotent/self-healing: Tage & Roll-ups werden bei jedem Lauf neu berechnet
  (INSERT OR REPLACE / ON CONFLICT upsert).
- `coverage_pct` < 100 ⇒ Bezug-kWh ohne Spot-Preis (Datenlücke) — Kosten nur über
  belegte Buckets gerechnet.

## No-Gos
- Keine Ratenlimit-/Steuerlogik ableiten (No-Go #3 bleibt: SOC_MIN/MAX only).
- Spot-Preis NICHT als Verkaufs-/Einspeiseerlös interpretieren (Nulleinspeiser).
- Keine `config.DYN_TARIF`-Werte hart in Collector/Web duplizieren — einzige Wahrheit
  ist `config.DYN_TARIF`.

## Häufige Aufgaben
- Komponenten/Preise pflegen → `config.DYN_TARIF` (danach `--days-back`-Reaggregation).
- 2026 neu rekonstruieren → `python -m tools.backfill_dynamic_price`.
- Einzeltag prüfen → `python -m collector.aggregate.tariff_cost --from YYYY-MM-DD --to …`.
- Täglicher Lauf → `scripts/dynamic_price_update.sh` (Timer `pv-dynamic-price`).

## Bekannte Fallstricke
- energy-charts 429 bei zu vielen schnellen Requests → Blöcke ≤31 Tage + Sleep;
  Backfill-Lücken per gezieltem `--from/--to` nachholen.
- `data_5min_permanent` hat ~1 Tag Lag (nächtlicher Build) → Aggregation läuft für
  abgeschlossene Tage; `--days-back 3` fängt den Lag ab.
- Neue `config.DYN_TARIF`-Attribute brauchen `systemctl restart pv-web.service`
  (HUP zieht Modulattribute nicht).

## Verwandte Cards
- [`web-analyse-strompreis.card.md`](./web-analyse-strompreis.card.md) — Analyse-Seite + Chart-Overlay
- [`collector-db-schema.card.md`](./collector-db-schema.card.md) — `spot_price_15min`, `tariff_cost_*`
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)

## Human-Doku
- `doc/web/STROMPREIS_ANALYSE.md`
