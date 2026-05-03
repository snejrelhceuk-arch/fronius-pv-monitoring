---
title: Wattpilot-Collector (WS-Polling, eto, Sessions)
domain: collector
role: A
applyTo: "wattpilot_collector.py"
tags: [wattpilot, collector, websocket, eto]
status: stable
last_review: 2026-05-03
---

# Wattpilot-Collector

## Zweck
Liest die Fronius-Wattpilot (go-e basiert) zyklisch via WebSocket-API und persistiert Status, Energie-Counter (`eto`) und Session-Werte. Schreibt `wattpilot_readings` und Tagesaggregat `wattpilot_daily`.

## Code-Anchor
- **Hauptdatei:** `wattpilot_collector.py` (Daemon-Loop, ~L15–75)
- **API-Client:** `wattpilot_api.py`
- **Schema:** `doc/collector/schema/db_schema_wattpilot.sql`, `db_init.py`

## Inputs / Outputs
- **Inputs:** Wattpilot-WebSocket (`setValue`/`getStatus`-Events).
- **Outputs:**
  - `wattpilot_readings` — `ts`, `energy_total_wh` (`eto`), `power_w`, `car_state`, `session_wh`, `temp`, `phase_mode`, `amp`, `trx`, `lmo`, `frc`.
  - `wattpilot_daily` — `energy_wh = Δ(eto)` über den Tag.

## Invarianten
- **Polling-Intervall** ca. 30 s (`WATTPILOT_POLL_INTERVAL` in `config.py`).
- **`eto` ist Gesamt-Counter** — Tageswert nur über Differenz.
- **WS-Konflikt-Tolerance:** Bei Verdrängung durch Fronius-/go-e-App bis zu 3 Retries (`wattpilot_collector.py:150–180`).
- **PID-Lock:** `wattpilot_collector.pid`.

## No-Gos
- Keine Schreibwege Richtung Wattpilot in der A-Rolle (Steuern = Rolle C über `automation/engine/aktoren/aktor_wattpilot.py`).
- Keine `eto`-Manipulation (Counter ist Hardware-Wahrheit, nur lesen).
- Solarweb-Statistik nicht als Wallbox-Quelle nutzen (zeigt nur PV-Anteil).

## Häufige Aufgaben
- Neues WS-Feld persistieren → `wattpilot_collector.py` + Schema-Spalte in `wattpilot_readings` (`db_init.py`).
- Tagesdelta debuggen → `wattpilot_daily.energy_wh` aus `eto`-Diff Tagesanfang/-ende; bei Hardware-Reset entstehen Sprünge.

## Bekannte Fallstricke
- **`eto`-Sprünge** bei Wattpilot-Reset/Hardwaretausch — Tagesaggregat kann negativ werden.
- **WS-Verdrängung** durch parallele go-e-App — keine harte Fehlfunktion, aber Lücken in `wattpilot_readings`.
- **Wattpilot-`rbt`-Reset** ist sensibler Recovery-Pfad in der Engine — Collector ist davon nicht betroffen, aber Logs darauf prüfen (`reminders.md`, 2026-04-06).

## Verwandte Cards
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md)
- [`automation-regel-wattpilot.card.md`](./automation-regel-wattpilot.card.md) — Steuerpfad

## Human-Doku
- `doc/collector/DB_SCHEMA.md`
- `doc/collector/schema/db_schema_wattpilot.sql`
