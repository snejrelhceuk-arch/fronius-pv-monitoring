---
title: Diagnos NQ (Netzqualität-Beobachtung, Rolle N)
domain: diagnos
role: D
applyTo: "diagnos/nq_health.py"
tags: [netzqualitaet, pac4200, freshness, pipeline, rolle-n]
status: stable
last_review: 2026-08-10
---

# Diagnos NQ

## Zweck
Read-only Beobachtung des Netzqualitäts-Subsystems (PAC4200, Rolle N) aus Sicht von Primary: lebt die Tech→Primary-Pipeline (frische Aggregate), rollt die Tagesenergie, sind die Primary-NQ-Timer scharf, gab es Netzereignisse? Kein PAC-Hardwarezugriff.

## Code-Anchor
- **Hauptlauf:** `diagnos/nq_health.py:run_all`
- **Pipeline:** `diagnos/nq_health.py:check_nq_pipeline_freshness` (nq_5min der neuesten Monats-DB)
- **Energie:** `diagnos/nq_health.py:check_nq_energy_freshness` (nq_energy_daily)
- **Timer:** `diagnos/nq_health.py:check_nq_services` (Primary-NQ-Timer, nur installierte)
- **Ereignisse:** `diagnos/nq_health.py:check_nq_events_recent` (Info, kein Alarm)
- **Parameter:** `diagnos/config.py` (`NQ_DB_DIR`, `NQ_PIPELINE_WARN_S`/`_CRIT_S`, `NQ_ENERGY_WARN_DAYS`/`_CRIT_DAYS`, `NQ_TIMERS`)
- **Mail-/Report-Anteil:** `automation/engine/nq_notifier.py:diff_nq_befunde`, `automation/engine/notify/report_format.py`, `diagnos/status_report.py` (Netz-Status.md)

## Inputs / Outputs
- **Inputs:** read-only Monats-DBs `nq/db/nq_YYYY-MM.db` (`nq_5min`, `nq_energy_daily`, `nq_events`), `systemctl show` der NQ-Timer, `.role`.
- **Outputs:** JSON-Snapshot (`nq:*`-Checks); fließt in den Sunset-Bericht (NQ-Sektion) und nach `logs/diagnos/Netz-Status.md`.

## Invarianten
- Strikt read-only; **kein** PAC-Hardwarezugriff (Sache des Tech-Collectors, Rolle N).
- Rollen-/deploymentbewusst: ohne NQ-Monats-DB oder auf Failover → `skipped`, kein Alarm.
- Frische-Schwellen zentral in `diagnos/config.py` (Pipeline 5/9,5 h, Energie 2/4 d).
- Die PAC-Hardware wird indirekt bewiesen: frische Aggregate = Kette PAC→Tech→Transfer→Aggregation lebt.

## No-Gos
- Kein Schreibpfad zur PAC oder in NQ-DBs.
- Kein direkter Modbus-Zugriff aus Diagnos (Rollentrennung N/D).

## Häufige Aufgaben
- Frische-Schwelle anpassen → `NQ_PIPELINE_*`/`NQ_ENERGY_*` in `diagnos/config.py`.
- Weiteren Primary-NQ-Timer überwachen → `NQ_TIMERS` erweitern.

## Bekannte Fallstricke
- Transfer/Aggregation laufen alle 4 h → Frische bis ~4 h ist normal (Warn erst > 5 h).
- Nur auf Primary sinnvoll (dort läuft die Aggregation); der Poller läuft auf Tech.

## Verwandte Cards
- [`diagnos-health.card.md`](./diagnos-health.card.md)
- [`netzqualitaet-nq-aggregation.card.md`](./netzqualitaet-nq-aggregation.card.md)
- [`netzqualitaet-nq-collector.card.md`](./netzqualitaet-nq-collector.card.md)

## Human-Doku
- `doc/diagnos/DIAGNOS.md`
- `doc/diagnos/CHECKKATALOG.md`
