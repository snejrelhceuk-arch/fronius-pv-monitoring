---
title: NQ Tech-Collector (PAC4200, tmpfs, RAM-first)
domain: netzqualitaet
role: N
applyTo: "nq/collector/**"
tags: [netzqualitaet, nq, pac4200, collector, tmpfs, tech, rolle-n]
status: experimental
last_review: 2026-07-23
changes:
	- 2026-07-14 (k): **10s-Skalarpfad entfernt.** `nq/collector/nq_poller.py` schreibt Skalar-Aggregate direkt nach `nq_5min` (5-min-Buckets, inkl. `vstd`) statt `nq_agg_10s`. `config/nq_config.json:aggregate.grid_s` auf 300 gesetzt; `nq/collector/nq_capping.py` löscht kein `nq_agg_10s` mehr.
	- 2026-07-14 (j): **Saubere Lesepfade statt Fallback-Rechnung.** PAC-Clone-Werte kommen jetzt **direkt aus der Tech-DB** (kein Nachrechnen auf Primary). `nq_raw_fast` um `s_l1/l2/l3`, `q_l1/l2/l3`, `uavg_ln`, `uavg_ll`, `isum` erweitert (`_FAST_COLS`/`_FAST_REV` synchron). Vorzeichen kommen vom PAC (P/Q signiert; `Is_Lx` in `_decode_ab` aus P-Vorzeichen). **`tech_read._fill_missing_values` + `pac_live._fill_missing_values` ersatzlos entfernt** (waren U*I/cosφ-Schätzungen). **Max-Werte (Block C `FLOAT3_MAP`) via 300-s-Slow-Poll:** neue `pac_live.read_max_snapshot`, `nq_poller._MAX_COLS`→`nq_raw_max`-Tabelle (300 s im `_medium_thread`), `tech_read._MAX_REV`. Alle 16 Screens ohne None. PAC-IP-Auflösung: `PV_PAC_IP` (.infra.local) via systemd `EnvironmentFile` — manueller Start ohne Env greift auf anonymisierten Default zurück (Betrieb nur via `pv-nq-poller.service`).
	- 2026-07-14 (i): **NQ2 WP0/WP1.** Tier-Benennung vereinheitlicht: fast(200ms Skalare), medium(1s Harmonik+Freq), slow(Energiezähler). `_slow_thread`→`_medium_thread`, `medium_ms` (Fallback `slow_ms`). `nq_raw_medium.f` (Frequenz-Spalte). **LimitMonitor** (`nq_poller.LimitMonitor`): Software-Grenzwertüberwachung der Skalare gegen `config.grenzwerte` → `nq_limit_alerts` + best-effort Sofort-Mail (`nq/collector/nq_limit_mail.py`), Cooldown. Tote Stubs entfernt (`pac_client`/`nq_export_tech`/`nq_ingest_primary` — jetzt via `pac_live.py`+`nq_poller.py`). Retention-Kommentare 72h→12h angeglichen. PAC-Clone liest indirekt aus Tech (kein PAC-Direktzugriff).
	- 2026-07-12 (h): **Datenwachstum-Kontrolle.** Bug fix: `nq_raw_medium` wurde in `nq_capping.py` mit `ts` statt `ts_ms` gelöscht (Medium-Rows akkumulierten unbegrenzt). Stale-Event-Kappung ergänzt (`event_stale_cap_s=3600 s`): event=1-Zeilen ohne Transfer-Quittung nach 1 h gelöscht + stderr-Warnung. Speicherwarnungen bei >80 % Budget oder <warn_free_mb freiem tmpfs. Primary-Cap `nq/transfer/nq_primary_cap.py` neu (Alters- + Zählgrenze für nq_event_* auf SD). Config: `event_stale_cap_s`, `warn_free_mb`, `event_keep_days`, `event_max_count`.
	- 2026-07-11: Modul NQ (Rolle N) angelegt; Tech-Collector-Skelette + tmpfs-Schema + Kappungskonzept dokumentiert (Implementierung Phase 1).
	- 2026-07-11 (b): Registerkarte korrigiert/verifiziert (THD-U L-L @43-47, THD-U L-N @261-265, **THD-I @267-271**, cos φ @243-247, I_N @295; 49-53 = NaN). Energie-Differenzmethode umgesetzt: `nq/collector/nq_energy.py` (`compute_daily`, Reset-Erkennung) + `nq_energy_raw`. PAC-Live-Screens erweitert (I_N, cos φ).
	- 2026-07-12: Energie-Snapshotter **produktiv auf Tech** (systemd `pv-nq-energy.service`, Restart=always, EnvironmentFile=.infra.local -> PV_PAC_IP, tmpfs). Primary-Tages-Rollup `nq/transfer/nq_energy_rollup.py` + Timer `pv-nq-energy-rollup.timer` (00:05) schreibt nq_energy_daily/checkpoint/compare auf SD. Event-Schnipsel-Schema (dedup/60s/peak) + PAC-Clone auf 12 Screens + F1-F4-Menü erweitert.
	- 2026-07-12 (b): **Fast/Medium-Poller** `nq/collector/nq_poller.py:poller_loop` PRODUKTIV auf Tech (systemd `pv-nq-poller`, reuse `pac_live.read_snapshot`, 35 Größen -> `nq_agg_10s` + RAW fast/medium + Event-Vorfilter) + Ring-Kappung `nq/collector/nq_capping.py:enforce_retention` (Zeit-Ring 72 h + Größen-Kappung). Skalar-Aggregat: meas=''/phase=0/ord=0 (WITHOUT-ROWID-PK).
	- 2026-07-12 (c): Block C (`FLOAT3_MAP`, Adr. 75..144) gelesen: Max-Werte §12–§22; Phasor-Screen (inline SVG). MESSTECHNIK.md-Kommentar Harmonische initial falsch gesetzt (korrigiert in d).
	- 2026-07-12 (d): **Einzelharmonische H3..H31** (A.3.10): `HARM_UN_MAP` @9001, `HARM_I_MAP` @11001, `HARM_ULL_MAP` @22001 (je 96 Register, ungerade Ordnungen, % der Grundschwingung). 6 Balkendiagramm-Screens (`_harm_bar_svg`) in `_build_screens`. MESSTECHNIK.md + PAC4200-Modbus.md (§56–58) + nq_config.json korrekt dokumentiert.
	- 2026-07-12 (g): **Dual-Rate gehärtet + Harmonische als echtes 1-s-RAW.** Poller: Hintergrund-Thread `_slow_thread` (threading.Event) entkoppelt Harm-Loop vollständig vom 200-ms-Fast-Loop (kein Blocking mehr bei PAC-Latenz). Fast-Timeout 0.5 s, Slow-Timeout 1.5 s. Harmonische → `nq_raw_slow` (meas='U_LN'|'U_LL'|'I', phase, ord) statt 10-s-Bucket. RAM 12 h: ~470 MB (war 680 MB, weil 72 h). `energy_s=300` (5 min). nq_aggregate: `_run_harm_5min` (nq_raw_slow→nq_5min), hourly/daily ohne _SCALAR_FILTER → aggregiert Skalare+Harmonische gemeinsam. Transfer jetzt 4-stündlich + nq_raw_slow-Übernahme im 5-h-Fenster.
	- 2026-07-11: Basis-Registerkarte (Adr. 1..73 FLOAT32 + Energie 801 FLOAT64) gegen reales Geraet verifiziert; read-only `nq/pac_live.py` + Live-Web-Anzeige `/pac4200`; Phase-0-Feldtest `nq/fieldtest/pac_refresh_probe.py` gestartet (Frequenz refresht ~10 s, RMS <=250 ms, THD-I NaN).
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
