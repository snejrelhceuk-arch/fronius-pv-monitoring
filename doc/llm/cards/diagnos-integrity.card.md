---
title: Diagnos Integritaet (Bilanzen, Rollups, Gap-Scan)
domain: diagnos
role: D
applyTo: "diagnos/integrity.py,diagnos/gap_checks.py"
tags: [integritaet, gap-scan, rollup, balance, config-parse]
status: stable
last_review: 2026-08-10
---

# Diagnos Integritaet

## Zweck
Tiefe read-only Pruefung der Datenkonsistenz: Energiebilanz, Monats-/Jahresrollups, Zeitlueckenklassifikation und JSON-Konfigurationsparse.

## Code-Anchor
- **Hauptlauf:** `diagnos/integrity.py:run_all`
- **Tagesbilanz:** `diagnos/integrity.py:check_daily_energy_balance`
- **Rollups:** `diagnos/integrity.py:check_monthly_rollup`, `check_yearly_rollup`
- **Gap-Scan:** `diagnos/gap_checks.py:_run_gap_scan` + `check_*_gaps` (importiert in `diagnos/integrity.py`)
- **WR-Zustand:** `diagnos/integrity.py:check_fronius_attachment_state`
- **Config-Parse:** `diagnos/integrity.py:check_config_json_parse`
- **Status-Markdown:** `diagnos/status_report.py:write_status_reports` (schreibt RAW-Status.md + System-Status.md nach `logs/diagnos/`)

## Inputs / Outputs
- **Inputs:** read-only Daten aus `daily_data`, `data_1min`, `data_15min`, `hourly_data`, `monthly_statistics`, `yearly_statistics`, plus JSON-Konfigurationen unter `config/` und `config/fronius_attachment_state.json`.
- **Outputs:** JSON-Befund mit Severity je Check, Gap-Samples und Kontextnotizen; Exit-Code 0/1/2.

## Invarianten
- Integritaetschecks bleiben strikt read-only (SQLite URI `mode=ro`).
- Gap-Klassen sind fix: `micro`, `short`, `medium`, `long`; `medium/long` erzwingen mindestens `crit` — **aber nur für frische Lücken** (nicht Nacht-Standby, nicht „gesetzte" historische Lücken > `GAP_SETTLE_S`).
- `overall` entspricht immer der schlechtesten Einzelseverity.
- Gap-Annotationen geben Kontext, reparieren aber keine Daten.
- WR-Zustand: aktuelle Collector-Liveness schlägt eine ältere gespeicherte Vollprüfung (live + fehlerfrei ⇒ kein `crit`).

## No-Gos
- Keine Rekonstruktion/Interpolation technischer Zeitreihen in Diagnos.
- Keine stillen Datenkorrekturen in Produktivtabellen.
- Kein Triggern von Aktorik auf Basis einzelner Integritaetschecks.

## Häufige Aufgaben
- Schwellwerte nachziehen -> Konstanten (`*_WARN_*`, `*_CRIT_*`) in `diagnos/integrity.py` anpassen.
- Neue Tabelle in Gap-Scan aufnehmen -> neuer `check_<table>_gaps()` in `diagnos/gap_checks.py` ueber `_run_gap_scan`.
- Neue Konfigdatei in Parse-Check -> Glob oder expliziten Pfad in `diagnos/integrity.py` erweitern.

## Bekannte Fallstricke
- SQL-Rollups nutzen `localtime`; bei TZ-/DST-Sonderfaellen koennen Monatsgrenzen anders wirken als reine UTC-Auswertung.
- Ein fehlender/unvollständiger Attachment-State führt bei lebendem Collector nur zu `warn` (nicht `crit`); ohne lebenden Collector weiterhin `crit`.
- Konsistente Folgedaten koennen historische Gaps relativieren, aber nicht automatisch entkraeften.
- „Gesetzte" Lücken (> `GAP_SETTLE_S`) verschwinden aus der Alarmschwere, bleiben aber in `RAW-Status.md` und in `settled_gap_count` sichtbar — ein realer, frischer Ausfall darf so nicht übersehen werden (er bleibt < 25 h alarmrelevant).

## Verwandte Cards
- [`diagnos-health.card.md`](./diagnos-health.card.md)
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)

## Human-Doku
- `doc/diagnos/STATUS_BERICHTE.md`
- `doc/diagnos/CHECKKATALOG.md`
- `doc/diagnos/DIAGNOS_KONZEPT.md`
- `doc/diagnos/UMSETZUNGSPLAN.md`
