---
mode: agent
description: "NQ Phase 1 — Tech-Collector: PAC-Client, Block-Poller, tmpfs-DB, Kappung"
---

# NQ Phase 1 — Tech-Collector (Rolle N, RAM-first)

Du bist Senior-Entwickler am **PV-System**, Rolle **N**. Host: **Pi4-Tech** (`192.0.2.181`, 4 GB RAM).

## Pflichtlektüre zuerst
1. [`AGENTS.md`](../../AGENTS.md) — Rollen, No-Gos (Rolle N read-only ggü. Produktion; RAM-first; SD selten).
2. [`doc/netzqualitaet/NQ_MODUL.md`](../../doc/netzqualitaet/NQ_MODUL.md) — §3–§5 (RAM-Budget 72 h, Blöcke/Tabellen, Kappung).
3. [`doc/netzqualitaet/NQ_TESTS_UND_DB.md`](../../doc/netzqualitaet/NQ_TESTS_UND_DB.md) — Differenzmethode (§4), Härtung (§7), Verifizierungsstand (§1).
4. [`doc/netzqualitaet/MESSTECHNIK.md`](../../doc/netzqualitaet/MESSTECHNIK.md) + [`doc/netzqualitaet/PAC4200-Modbus.md`](../../doc/netzqualitaet/PAC4200-Modbus.md) — **verifizierte** Registerlage (THD-I @267–271, cos φ @243–247, I_N @295, Energie @801+).
5. [`doc/llm/cards/netzqualitaet-nq-collector.card.md`](../../doc/llm/cards/netzqualitaet-nq-collector.card.md) — Invarianten, No-Gos, Anchor.
6. **Vorbild-Code (Muster übernehmen, nicht ändern):**
   - [`collector/poller.py`](../../collector/poller.py) — Poll-Loop-Struktur, Fehlerbehandlung.
   - [`collector/buffer.py`](../../collector/buffer.py) — `deque`-RAM-Buffer + Batch-`executemany`-Flush.
   - [`collector/modbus_client.py`](../../collector/modbus_client.py), [`collector/sunspec.py`](../../collector/sunspec.py) — Modbus-Lesen, FLOAT32-Dekodierung.
   - [`collector/pid_lock.py`](../../collector/pid_lock.py) — Single-Instance-Lock.

## Ziel
Produktiver, **systemkonsistenter** Collector, der den PAC4200 in drei Takten
pollt, in eine **tmpfs-DB** (`/dev/shm/nq_cache.db`) schreibt und über eine
Ring-Buffer-Kappung den RAM nie überlaufen lässt.

## Zu implementierende Skelette (bereits vorhanden, jetzt füllen)
- [`nq/collector/pac_client.py`](../../nq/collector/pac_client.py) — `read_fast_block` / `read_medium_block` / `read_slow_block`.
- [`nq/collector/nq_poller.py`](../../nq/collector/nq_poller.py) — `poller_loop` (Orchestrator, 3 Takte, Buffer, Flush, Event-Vorfilter, 3–10 s-Aggregat fortschreiben).
- [`nq/collector/nq_capping.py`](../../nq/collector/nq_capping.py) — `enforce_retention` (Zeit-Ring + Größen-Kappung).
- Nutze [`nq/nq_common.py`](../../nq/nq_common.py) (`load_config`, `open_db`, `db_size_mb`, `tmpfs_free_mb`) und das Schema [`nq/schema/nq_tech_schema.sql`](../../nq/schema/nq_tech_schema.sql).
- Konfig: [`config/nq_config.json`](../../config/nq_config.json).

## Fachliche Vorgaben
- **Poll-Takte:** Default aus Config (`fast_ms` 500 / `medium_ms` 1000 / `slow_ms` 5000). Nach Phase 0 (Feldtest) auf reale Refresh-Rate anpassen.
- **Schreibmuster:** `deque`-Buffer je Block, Batch-Flush alle `flush_interval_s`, WAL, `synchronous=NORMAL`, kurzer Lock-Timeout. Kein Row-per-Insert.
- **Fast-Block** → `nq_raw_fast` (PK `ts_ms`), **Medium** → `nq_raw_medium` (PK `ts`), **Slow** → `nq_raw_slow` (Long-Format, PK `ts,meas,phase,ord`).
- **Zweirichtungszähler:** RMS-Ströme (Adr. 13/15/17) sind vorzeichenlose Beträge; die Richtung folgt dem Vorzeichen der Phasen-Wirkleistung P (Adr. 25/27/29). Ströme **vorzeichenbehaftet** speichern (`i_lx = -abs(i)` bei `P_lx < 0`), Muster: `read_snapshot` in [`nq/pac_live.py`](../../nq/pac_live.py). Siehe [`doc/netzqualitaet/MESSTECHNIK.md`](../../doc/netzqualitaet/MESSTECHNIK.md) „Vorzeichen der Stroeme".
- **Energiezähler / Differenzmethode (bereits umgesetzt):** [`nq/collector/nq_energy.py`](../../nq/collector/nq_energy.py) läuft eigenständig (langsamer Takt `polling.energy_s`), schreibt kumulative Zähler nach `nq_energy_raw`; `compute_daily` liefert start/end/delta mit Reset-Erkennung. Nur noch als eigenen Snapshotter-Prozess (PID-Lock + systemd) einbinden — nicht neu erfinden.
- **3–10 s-Aggregat** (`nq_agg_10s`, min/avg/max je Größe) fortlaufend fortschreiben — Basis des späteren Transfers.
- **Event-Vorfilter:** aus `event_filter` (Δu, Δf, THD-Schwelle) — setzt `event=1` auf betroffene RAW-Zeilen inkl. Pre-/Post-Window. Nur markieren, nicht separat speichern.
- **Kappung (`nq_capping.py`):** (1) Zeit-Ring `DELETE ... WHERE ts < now-72h` (Event-markierte ausnehmen bis Transfer-Quittung); (2) Größen-Kappung, wenn tmpfs-Belegung > `cap_mb`, älteste Nicht-Event-Zeilen blockweise löschen; danach `wal_checkpoint(TRUNCATE)` + `optimize` (kein `VACUUM` im heißen Pfad). Protokoll in `nq_capping_log`.
- **Single-Instance** via PID-Lock (Muster [`collector/pid_lock.py`](../../collector/pid_lock.py)).

## Harte No-Gos
- **Nur Modbus `read`.** Kein Schreibpfad zum PAC4200, zu `data.db` oder Aktoren.
- **Registeradressen NICHT erfinden** — verifizierte Siemens-Map (Phase 0). Ohne Map: innehalten und anfordern.
- **Kein Dauer-SD-Write.** Nutzdaten ausschließlich im tmpfs.
- Kein Refactor am Produktions-Collector; NQ-Code bleibt in `nq/`.

## Definition of Done
- `python3 -m nq.collector.nq_poller` läuft stabil auf Tech, füllt die tmpfs-Tabellen, hält RAM < Budget.
- Kappung nachweislich wirksam (Log-Einträge, tmpfs stabil unter `cap_mb`).
- Optional: systemd-Unit-Vorschlag unter [`config/systemd/`](../../config/systemd) (analog vorhandener Units), **read-only** dokumentiert.
- Card [`netzqualitaet-nq-collector.card.md`](../../doc/llm/cards/netzqualitaet-nq-collector.card.md) aktualisiert (Anchor auf reale Funktionen, `last_review` heute).
- Kurzer Smoke-Test-Beleg (lokal, Port-frei; Modbus ggf. Mock).
