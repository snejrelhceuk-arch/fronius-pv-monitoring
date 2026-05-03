---
title: FritzDECT-Collector (AHA-API, AIN-Mapping)
domain: collector
role: A
applyTo: "fritzdect_collector.py"
tags: [fritzdect, collector, aha-api, ain]
status: stable
last_review: 2026-05-03
---

# FritzDECT-Collector

## Zweck
Liest Fritz!DECT-Steckdosen (z. B. Heizpatrone, Klimaanlage, WP-Schaltdose) via AHA-HTTP-Interface der Fritz!Box. Persistiert in `fritzdect_readings`.

## Code-Anchor
- **Hauptdatei:** `fritzdect_collector.py` (~L30–80)
- **Config:** `config/fritz_config.json` (Fritz!Box-IP, Geräteliste mit `device_id`, `ain`, `name`, `active`-Flag, `polling_interval_s`)
- **Schema:** `db_init.py` Tabelle `fritzdect_readings`

## Inputs / Outputs
- **Inputs:** AHA-HTTP-Endpunkte (`getswitchpower`, `getswitchstate`, `getswitchenergy`), Session-ID (Cache 15 min).
- **Outputs:** `fritzdect_readings` — `ts`, `device_id`, `ain`, `name`, `power_mw`, `power_w`, `state`, `energy_total_wh`.

## Invarianten
- **Polling-Intervall** typisch 10 s (`polling_interval_s` in `fritz_config.json`).
- **Session-Cache:** 15 min, danach Reauth.
- **AIN-Mapping** ist aus `fritz_config.json` zu lesen — Single Source.
- Bei <10 aufeinanderfolgenden Fehlern: Log; danach quiet (`fritzdect_collector.py:52–100`).

## No-Gos
- Keine Schaltbefehle aus dem Collector — Schalten ist Rolle C (`automation/engine/aktoren/aktor_fritzdect.py`).
- Keine AIN-Hartcodierung im Code.
- Keine Schwellen-Logik im Collector (gehört in die Engine).

## Häufige Aufgaben
- Neues Gerät hinzufügen → `config/fritz_config.json` (`device_id`, `ain`, `name`, `active: true`).
- AIN-Mapping prüfen → Geräteliste mit Fritz!Box-Oberfläche abgleichen (häufige Fehlerquelle).

## Bekannte Fallstricke
- **AIN-Vertauschung** ist eine häufige stille Fehlerquelle — Heizpatrone schaltet, aber Klimaanlage geht ein/aus (`fritzdect-ain-mapping-note`).
- Fritz!Box-Reboot → Session ungültig → Reauth nötig.
- Energie-Counter (`energy_total_wh`) springt bei Steckdosen-Reset → Tagesdeltas können negativ werden.

## Verwandte Cards
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)
- [`automation-regel-heizpatrone.card.md`](./automation-regel-heizpatrone.card.md) — Aktor-Pfad (Rolle C)

## Human-Doku
- `doc/collector/DB_SCHEMA.md`
