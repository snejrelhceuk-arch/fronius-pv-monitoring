---
title: Netzqualitaet Analyse (Export, DFD, API)
domain: netzqualitaet
role: B
applyTo: "netzqualitaet/**"
tags: [netzqualitaet, dfd, export, analyse, api]
status: stable
last_review: 2026-05-03
---

# Netzqualitaet Analyse

## Zweck
Separates NQ-Teilprojekt im PV-System: Export netzrelevanter Rohdaten, 15min-DFD-Analyse und read-only API fuer Tages-/Analyseansicht.

## Code-Anchor
- **Tag-API:** `routes/netzqualitaet.py:api_netzqualitaet_tag`
- **Analyse-API:** `routes/netzqualitaet.py:api_netzqualitaet_analyse`
- **Exportlauf:** `netzqualitaet/nq_export.py:run_export`
- **Analyse-Lauf:** `netzqualitaet/nq_analysis.py:run_analysis`
- **Trade-Switch-Detektion:** `netzqualitaet/nq_trade_switch_detect.py:run_day`
- **NQ-DB-Pfad:** `netzqualitaet/db/nq_YYYY-MM.db`

## Inputs / Outputs
- **Inputs:** `raw_data`-Felder (`f_Netz`, `U_L*_L*_Netz`, `I_L*_Netz`) aus Haupt-DB, Tagesparameter `date=YYYY-MM-DD`.
- **Outputs:** Monatsdatenbanken mit `nq_samples` und Analyse-Tabellen (`nq_15min_blocks`, `nq_boundary_events`, `nq_daily_summary`) sowie JSON fuer `/api/netzqualitaet/*`.

## Invarianten
- NQ schreibt ausschliesslich in eigene DBs unter `netzqualitaet/db/`.
- Haupt-DB wird von NQ-Skripten nur read-only gelesen (`mode=ro` in Export).
- Tages-API liefert 5min-Buckets aus `raw_data` (keine Aktorik, keine Schreibpfade).
- Analyse-API liefert `available=false`, wenn die Monats-DB fuer den Tag fehlt.

## No-Gos
- Keine Rueckschreibungen in Collector-/Automation-Produktivtabellen.
- Keine Hardwarezugriffe oder Polling-Verschaerfung im Collector nur fuer NQ.
- Keine Vermischung von NQ-Schema und Haupt-DB-Schema ohne Migration.

## Häufige Aufgaben
- Neues Signal aufnehmen -> `nq_export.py:RAW_COLUMNS` + `NQ_SCHEMA` + API-Response in `routes/netzqualitaet.py` erweitern.
- Historischen Backfill fahren -> `python netzqualitaet/nq_export.py --full` und anschliessend Analyse laufen lassen.
- DFD-Parameter kalibrieren -> Konstanten in `nq_analysis.py` (`BOUNDARY_WINDOW_S`, `MIN_SAMPLES_*`) anpassen.

## Bekannte Fallstricke
- Datumsgrenzen laufen ueber `localtime`; UTC-Interpretationen koennen abweichen.
- Fehlt der taegliche Export/Analyse-Lauf, bleibt `/api/netzqualitaet/analyse` leer trotz vorhandener Rohdaten.
- Sparse Tage unterschreiten `MIN_SAMPLES_*` und werden in der Analyse bewusst verworfen.

## Verwandte Cards
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md)
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)
- [`web-display-api.card.md`](./web-display-api.card.md)

## Human-Doku
- `doc/netzqualitaet/README.md`
- `doc/netzqualitaet/METHODEN.md`
- `doc/netzqualitaet/TRADE_SWITCH_DETECTION.md`
