---
title: FritzDECT-Collector (AHA-API, AIN-Mapping)
domain: collector
role: A
applyTo: "collector/fritzdect.py"
tags: [fritzdect, collector, aha-api, ain]
status: stable
last_review: 2026-08-04
---

# FritzDECT-Collector

## Zweck
Liest Fritz!DECT-Steckdosen (z. B. Heizpatrone, Klimaanlage, WP-Schaltdose) via AHA-HTTP-Interface der Fritz!Box. Persistiert in `fritzdect_readings`.

## Code-Anchor
- **Hauptdatei:** `collector/fritzdect.py`
- **Config:** `config/fritz_config.json` (Fritz!Box-IP, Geräteliste mit `device_id`, `ain`, `name`, `active`-Flag, `polling_interval_s`)
- **Schema:** `db_init.py` Tabelle `fritzdect_readings`

## Inputs / Outputs
- **Inputs:** AHA-HTTP-Endpunkte (`getswitchpower`, `getswitchstate`, `getswitchenergy`), Session-ID (Cache 15 min).
- **Outputs:** `fritzdect_readings` — `ts`, `device_id`, `ain`, `name`, `power_mw`, `power_w`, `state`, `energy_total_wh`.

## Invarianten
- **Polling-Intervall** typisch 10 s (`polling_interval_s` in `fritz_config.json`).
- **Session-Cache:** 15 min, danach Reauth.
- **AIN-Mapping** ist aus `fritz_config.json` zu lesen — Single Source.
- Bei <10 aufeinanderfolgenden Fehlern: Log; danach quiet (`collector/fritzdect.py`).
- **Retention 7 Tage** (`config.FRITZDECT_RETENTION_DAYS`). Autoritativer Prune-Pfad ist `cleanup_db()` im Poller (`collector/poller.py`, stündlich im dauerhaft laufenden `pv-collector`) — unabhängig vom fritzdect-Collector-Loop. `cleanup_old_readings()` im Collector ist nur ein redundanter Fallback (greift nur, wenn der Collector-Loop ≥1 h durchläuft).
- **Indizes:** nur PK `(ts, device_id)`. Keine Zusatz-Indizes — alle Abfragen sind `ts`-begrenzt und nutzen den PK-Prefix. Frühere `idx_fritzdect_ts` (redundant) und `idx_fritzdect_device_id` (ungenutzt) wurden 2026-05-29 entfernt, um Schreib-Overhead auf der schreibstarken 10s-Tabelle zu senken.

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
- Energie-Counter (`energy_total_wh`) springt bei Steckdosen-Reset → Tagesdeltas könnten negativ werden; Daily-Aggregation guarded mit `max(0, ...)`.
- **Zähler-Freeze:** Steckdosen aktualisieren `energy_total_wh` zeitweise nur ~1×/Tag → Intraday-Delta 0 **oder zu klein** (Partial-Freeze, z. B. 36 Wh statt 1200 Wh). Abgesichert in `collector/aggregate/daily.py`: Interday-Fallback (Delta<0.1) **und** `getbasicdevicestats`-Fallback (`_fill_fritzdect_daily_from_devstats`, ~31 Tage Box-Tagesenergie). Seit 2026-08-04 ist der Box-Tageswert **autoritativ**: er überschreibt Auto-Quellen (`counter_auto`/`counter_interday`) nicht nur bei 0, sondern auch bei erkennbarer Untererfassung (Box-Wert > Delta + max(50 Wh, 15%)). Manual/recon-Quellen bleiben geschützt.
- **Stale-Steckdose:** Ist eine Steckdose >1 h ohne frischen `fritzdect_readings`-Eintrag (Box/Steckdose nicht erreichbar), meldet `diagnos/health.py:check_fritzdect_freshness` „Stale FritzSD-<Name>“ (erscheint im Sunset-Tagesbericht). Der fehlende Tag wird automatisch aus der Box-Tagesstatistik nachgezogen, sobald wieder erreichbar.
- **Status-only-Geräte:** `fussbodenheizung` ist ein DECT-Thermostat ohne Leistungsmessung (`power_w`=0, `energy_total_wh` konstanter Garbage-Wert). Nicht als Energieverbraucher aggregieren/auswerten.
- **Metering-Geräte mit Daily-Tabelle:** heizpatrone, klimaanlage, lueftung, gefriertruhe (`*_daily`/`*_monthly`). Mapping `FRITZDECT_DAILY_DEVICES` in `daily.py`.

## Verwandte Cards
- [`collector-db-schema.card.md`](./collector-db-schema.card.md)
- [`automation-regel-heizpatrone.card.md`](./automation-regel-heizpatrone.card.md) — Aktor-Pfad (Rolle C)

## Human-Doku
- `doc/collector/DB_SCHEMA.md`
