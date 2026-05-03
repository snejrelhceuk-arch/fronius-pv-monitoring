---
title: Fronius-Collector (Modbus + Solar-API)
domain: collector
role: A
applyTo: "modbus_v3.py"
tags: [collector, fronius, modbus, solar-api]
status: stable
last_review: 2026-05-03
---

# Fronius-Collector

## Zweck
Liest Fronius GEN24 zyklisch (3 s) via Modbus + ergänzt Solar-API-Werte (HTTP). Schreibt in `raw_data`. Einziger A-Schicht-Pfad für PV-/Batterie-Sensorik.

## Code-Anchor
- **Hauptdatei:** `modbus_v3.py` (Daemon-Loop, RAM-Buffer, Batch-Write)
- **API-Helper:** `fronius_api.py` (HTTP-Read + `BatteryConfig`-Schreibpfad)
- **Read-only-Variante für Web-API (Rolle B):** `routes/helpers.py:FroniusReadOnly`
- **Quellen-Map:** `modbus_quellen.py`
- **Init/Schema:** `db_init.py`
- **Config:** `config.py` (`POLL_INTERVAL`, …)

## Inputs / Outputs
- **Inputs:** Modbus-TCP-Verbindung zum WR, HTTP-Endpunkte der Solar-API (z. B. `/solar_api/v1/GetInverterRealtimeData`, `BatteryConfig`).
- **Outputs:** `raw_data`-Inserts (Batch alle 60 s), Tier-1-Eingangswerte.

## Invarianten
- **Polling-Intervall:** typisch 3 s (`POLL_INTERVAL`).
- **RAM-Buffer:** `deque maxlen=400` (~20 min @ 3 s), Batch-Write alle 60 s (`modbus_v3.py:110–120`).
- **PID-Lock:** `collector.pid` verhindert Doppelstart.
- **Read-only-Trennung:** Web-API nutzt `routes/helpers.py:FroniusReadOnly` — keine Schreibwege Richtung GEN24 (Rolle B = read-only). Bewusste Code-Duplette zur Absicherung der ABCDE-Rollentrennung.
- **Persist-Sicherheit:** Bei DB-Fehler bleibt der RAM-Buffer erhalten und wird beim nächsten Tick erneut geschrieben.

## No-Gos
- Keine Modbus-Schreibzugriffe an die Batterie-Register (40309/40311/40316/40317/40321) im Collector.
- Keine zweite parallel laufende Collector-Instanz (PID-Lock).
- Keine Polling-Frequenz-Änderung ohne Modbus-Last-Test (GEN24-WR wird bei <1 s instabil).

## Häufige Aufgaben
- Neues Modbus-Register lesen → `modbus_quellen.py` + Schema-Spalte (`db_init.py`) + Producer-Block in `modbus_v3.py`.
- Solar-API-Endpunkt ergänzen → `fronius_api.py` + Aufruf in `modbus_v3.py` (selten, da meiste Werte über Modbus).
- Retry-Verhalten ändern → `modbus_v3.py` (Loop-Section), Persist-Sicherheit prüfen.

## Bekannte Fallstricke
- **`modbus-register-map`** als zentrale Übersicht fehlt (offen, Audit-TODO `doc/TODO.md`) — Register-Bedeutungen sind über mehrere Dateien verstreut.
- WR-Reboot/Firmware-Update: Modbus reagiert sekundenlang nicht — Buffer hält das aus, aber Tier-1 darf hier nicht falsch alarmieren.
- Smart-Meter (Fronius Smart Meter) hat eigene Modbus-Adresse — Verwechslung mit WR möglich.
- `megabas-rs485` (Steuerbox-Hardware) nutzt RS485, **nicht** Modbus-TCP — eigener Pfad (`megabas-rs485-note`).

## Verwandte Cards
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md)
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)
- [`automation-battery-algorithm.card.md`](./automation-battery-algorithm.card.md) — Schreibpfad zum WR (Rolle C)

## Human-Doku
- `doc/collector/DB_SCHEMA.md`
- `doc/collector/AGGREGATION_PIPELINE.md`
