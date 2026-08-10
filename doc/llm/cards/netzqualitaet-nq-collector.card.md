---
title: NQ Tech-Collector (PAC4200, tmpfs, RAM-first)
domain: netzqualitaet
role: N
applyTo: "nq/collector/**"
tags: [netzqualitaet, nq, pac4200, collector, tmpfs, tech, rolle-n]
status: stable
last_review: 2026-08-10
---

# NQ Tech-Collector

## Zweck
Dedizierter **PAC4200**-Netzqualitäts-Collector am PCC (Rolle N), läuft **RAM-first
auf Pi4-Tech** (`192.0.2.181`). Pollt drei Registerblöcke (Fast/Medium/Slow),
schreibt in eine tmpfs-DB und hält den RAM per Ring-Buffer-Kappung stabil.
Abgrenzung: `nq/` (PAC4200, Rolle N) ≠ Legacy `netzqualitaet/` (Smart-Meter, Rolle B).

## Code-Anchor
- **Verifizierte Registerkarte + Snapshots (read-only):** `nq/pac_live.py` (`FLOAT_MAP`, `FLOAT2_MAP`, `FLOAT3_MAP`, `DOUBLE_MAP`, `HARM_*_MAP`, `read_fast_snapshot`, `read_max_snapshot`, `read_harm_snapshot`, `read_snapshot`, `_build_screens`)
- **Block-Poller/Orchestrator (fast + medium-Thread + LimitMonitor):** `nq/collector/nq_poller.py:poller_loop` / `_medium_thread` / `LimitMonitor`
- **Grenzwert-Alarm-Mail (best-effort):** `nq/collector/nq_limit_mail.py:send_limit_mail`
- **Energie-Differenzmethode:** `nq/collector/nq_energy.py:compute_daily` (within-day, Legacy) / **`compute_daily_boundary`** (randscharf auf Mitternacht, energieerhaltend) / `append_snapshot`
- **Feldtest Phase 0 (Refresh-Raten):** `nq/fieldtest/pac_refresh_probe.py:probe`
- **Read-only Web-Anzeige (Rolle B):** `routes/pac4200.py:api_pac4200_live`, `templates/pac4200_view.html`
- **Block-Poller/Orchestrator:** `nq/collector/nq_poller.py:poller_loop`
- **Kappung/Ring-Buffer:** `nq/collector/nq_capping.py:enforce_retention`
- **Gemeinsame Helfer:** `nq/nq_common.py` (`load_config`, `open_db`, `db_size_mb`, `tmpfs_free_mb`)
- **Schema (tmpfs):** `nq/schema/nq_tech_schema.sql`
- **Konfig:** `config/nq_config.json`
- **Muster/Vorbild:** `collector/poller.py`, `collector/buffer.py`, `collector/modbus_client.py`, `collector/pid_lock.py`

## Inputs / Outputs
- **Inputs:** PAC4200 Modbus TCP **read** (FLOAT32, 2 Register/Wert); Poll-Raten + Budgets aus `config/nq_config.json`.
- **Outputs (tmpfs `/dev/shm/nq_cache.db`):** `nq_raw_fast` (PK `ts_ms`, inkl. `s_lx`/`q_lx`/`uavg_ln`/`uavg_ll`/`isum`), `nq_raw_medium` (PK `ts_ms`), `nq_raw_slow` (Long-Format PK `ts,meas,phase,ord`), `nq_raw_max` (Block C, 300-s-Poll, jüngste Zeile), `nq_5min` (min/avg/max/std, Transfer-Basis), Logs `nq_capping_log` / `nq_transfer_log`.

## Invarianten
- **Nur Modbus `read`.** Kein Schreibpfad zum PAC4200, zu `data.db` oder Aktoren (Rolle N read-only ggü. Produktion).
- **RAM-first:** Nutzdaten liegen im tmpfs; die SD-Karte wird für NQ nicht dauerhaft beschrieben.
- **RAW-Retention = 12 h** Ring-Buffer (`retention.raw_hours`); Kappung greift spätestens bei `tmpfs.cap_mb` (1200 MB von 1500 MB Budget). Speicherwarnung bei >80 % Budget oder <`warn_free_mb` freiem Platz auf stderr.
- **Stale-Event-Kappung:** event=1-Zeilen ohne bestätigte Transfer-Quittung werden nach `event_filter.event_stale_cap_s` (Default 3600 s) zwangsgelöscht und in `nq_capping_log` (trigger='stale_event') protokolliert. Verhindert tmpfs-Überlauf wenn Transfer-Modul ausfällt.
- Schreibmuster wie Produktion: `deque`-Buffer + Batch-`executemany`, WAL, `synchronous=NORMAL`.

## No-Gos
- Registeradressen **nicht erfinden** — nur verifizierte Siemens-PAC4200-Map (48 h-Feldtest, Phase 0).
- Kein `VACUUM` im heißen Pfad (nur `wal_checkpoint(TRUNCATE)` + `optimize`).
- Kein Row-per-Insert; keine Polling-Rate schneller als reale interne Refresh-Rate des PAC4200.
- Kein Refactor am Produktions-Collector; NQ-Code bleibt in `nq/`.

## Häufige Aufgaben
- Poll-Raten anpassen → `config/nq_config.json` (`polling.fast_ms/medium_ms/slow_ms`) nach Feldtest.
- Neue PAC-Größe aufnehmen → Spalte/Zeile in `nq/schema/nq_tech_schema.sql` + Dekodierung in `pac_live.py`.
- RAM-Budget ändern → `tmpfs.budget_mb`/`cap_mb` + `retention.raw_hours`; Rechnung in `doc/netzqualitaet/NQ_MODUL.md` §3.

## Bekannte Fallstricke
- Zu dichtes Polling liest nur intern noch nicht erneuerte Werte mehrfach (Feldtest entscheidet).
- tmpfs-Belegung inkl. WAL messen (`db_size_mb` + `tmpfs_free_mb`), sonst Überlaufrisiko.
- Datumsgrenzen laufen über `localtime` (Konsistenz mit Produktion).

## Verwandte Cards
- [`netzqualitaet-nq-aggregation.card.md`](./netzqualitaet-nq-aggregation.card.md)
- [`netzqualitaet-nq-analysis-events.card.md`](./netzqualitaet-nq-analysis-events.card.md)
- [`collector-aggregation-pipeline.card.md`](./collector-aggregation-pipeline.card.md)

## Human-Doku
- `doc/netzqualitaet/NQ_MODUL.md` (§3–§5)
- `doc/netzqualitaet/MESSTECHNIK.md`
- `.github/prompts/nq-1-tech-collector.prompt.md`
