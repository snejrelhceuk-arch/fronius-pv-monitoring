---
title: NQ Tech-Collector (PAC4200, tmpfs, RAM-first)
domain: netzqualitaet
role: N
applyTo: "nq/collector/**"
tags: [netzqualitaet, nq, pac4200, collector, tmpfs, tech, rolle-n]
status: experimental
last_review: 2026-07-12
changes:
	- 2026-07-11: Modul NQ (Rolle N) angelegt; Tech-Collector-Skelette + tmpfs-Schema + Kappungskonzept dokumentiert (Implementierung Phase 1).
	- 2026-07-11 (b): Registerkarte korrigiert/verifiziert (THD-U L-L @43-47, THD-U L-N @261-265, **THD-I @267-271**, cos φ @243-247, I_N @295; 49-53 = NaN). Energie-Differenzmethode umgesetzt: `nq/collector/nq_energy.py` (`compute_daily`, Reset-Erkennung) + `nq_energy_raw`. PAC-Live-Screens erweitert (I_N, cos φ).
	- 2026-07-12: Energie-Snapshotter **produktiv auf Tech** (systemd `pv-nq-energy.service`, Restart=always, EnvironmentFile=.infra.local -> PV_PAC_IP, tmpfs). Primary-Tages-Rollup `nq/transfer/nq_energy_rollup.py` + Timer `pv-nq-energy-rollup.timer` (00:05) schreibt nq_energy_daily/checkpoint/compare auf SD. Event-Schnipsel-Schema (dedup/60s/peak) + PAC-Clone auf 12 Screens + F1-F4-Menü erweitert.
	- 2026-07-11: Basis-Registerkarte (Adr. 1..73 FLOAT32 + Energie 801 FLOAT64) gegen reales Geraet verifiziert; read-only `nq/pac_live.py` + Live-Web-Anzeige `/pac4200`; Phase-0-Feldtest `nq/fieldtest/pac_refresh_probe.py` gestartet (Frequenz refresht ~10 s, RMS <=250 ms, THD-I NaN).
---

# NQ Tech-Collector

## Zweck
Dedizierter **PAC4200**-Netzqualitäts-Collector am PCC (Rolle N), läuft **RAM-first
auf Pi4-Tech** (`192.0.2.181`). Pollt drei Registerblöcke (Fast/Medium/Slow),
schreibt in eine tmpfs-DB und hält den RAM per Ring-Buffer-Kappung stabil.
Abgrenzung: `nq/` (PAC4200, Rolle N) ≠ Legacy `netzqualitaet/` (Smart-Meter, Rolle B).

## Code-Anchor
- **PAC-Client (Modbus read):** `nq/collector/pac_client.py:read_fast_block` / `read_medium_block` / `read_slow_block`
- **Verifizierte Registerkarte + Live-Snapshot (read-only):** `nq/pac_live.py` (`FLOAT_MAP`, `FLOAT2_MAP`, `DOUBLE_MAP`, `read_snapshot`)
- **Energie-Differenzmethode:** `nq/collector/nq_energy.py:compute_daily` / `append_snapshot`
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
- **Outputs (tmpfs `/dev/shm/nq_cache.db`):** `nq_raw_fast` (PK `ts_ms`), `nq_raw_medium` (PK `ts`), `nq_raw_slow` (Long-Format PK `ts,meas,phase,ord`), `nq_agg_10s` (min/avg/max, Transfer-Basis), Logs `nq_capping_log` / `nq_transfer_log`.

## Invarianten
- **Nur Modbus `read`.** Kein Schreibpfad zum PAC4200, zu `data.db` oder Aktoren (Rolle N read-only ggü. Produktion).
- **RAM-first:** Nutzdaten liegen im tmpfs; die SD-Karte wird für NQ nicht dauerhaft beschrieben.
- **RAW-Retention = 72 h** Ring-Buffer; Kappung greift spätestens bei `tmpfs.cap_mb` (1200 MB von 1500 MB Budget).
- Schreibmuster wie Produktion: `deque`-Buffer + Batch-`executemany`, WAL, `synchronous=NORMAL`.
- Event-markierte RAW-Zeilen (`event=1`) bleiben bis zur bestätigten Transfer-Quittung von der Kappung ausgenommen.

## No-Gos
- Registeradressen **nicht erfinden** — nur verifizierte Siemens-PAC4200-Map (48 h-Feldtest, Phase 0).
- Kein `VACUUM` im heißen Pfad (nur `wal_checkpoint(TRUNCATE)` + `optimize`).
- Kein Row-per-Insert; keine Polling-Rate schneller als reale interne Refresh-Rate des PAC4200.
- Kein Refactor am Produktions-Collector; NQ-Code bleibt in `nq/`.

## Häufige Aufgaben
- Poll-Raten anpassen → `config/nq_config.json` (`polling.fast_ms/medium_ms/slow_ms`) nach Feldtest.
- Neue PAC-Größe aufnehmen → Spalte/Zeile in `nq/schema/nq_tech_schema.sql` + Dekodierung in `pac_client.py`.
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
