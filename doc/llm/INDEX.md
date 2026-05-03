# LLM-Card-Index — Trigger → Card

**Stand:** 2026-05-03 (Phase 3 — Pilot automation + collector live)

Dieser Index ist die **Stufe 3** der Lade-Hierarchie (s. `AGENTS.md`). Er bildet konkrete Aufgabenstellungen / Stichworte auf die zuständige Card ab.

> **Agenten-Workflow:** Aufgabe lesen → in der Trigger-Tabelle suchen → genannte Card öffnen → dort weitermachen. Wenn nichts passt: `doc/SYSTEM_BRIEFING.md` (Stufe 2).

## Trigger-Tabelle

| Aufgabe / Stichwort | Card | Status |
|---|---|---|
| **automation: Tick-Loop, Regel-Reihenfolge, Engine-Zyklus** | [`automation-engine.card.md`](./cards/automation-engine.card.md) | stable |
| **automation: SOC-Min/Max setzen, Fronius-BatteryConfig schreiben** | [`automation-battery-algorithm.card.md`](./cards/automation-battery-algorithm.card.md) | stable |
| **automation: Heizpatrone, WW-Speicher, FritzDECT-Schaltung** | [`automation-regel-heizpatrone.card.md`](./cards/automation-regel-heizpatrone.card.md) | stable |
| **automation: Wattpilot/EV-Lader, Ladestrom, SOC-Schutz bei Ladung** | [`automation-regel-wattpilot.card.md`](./cards/automation-regel-wattpilot.card.md) | stable |
| **automation: Prioritäten, ExternalRespect, Matrix-Konzept** | [`automation-steuerungsphilosophie.card.md`](./cards/automation-steuerungsphilosophie.card.md) | stable |
| **automation: Tier-1, SLS, No-Op-Schutz, Watchdog** | [`automation-schutzregeln.card.md`](./cards/automation-schutzregeln.card.md) | stable |
| **automation: ObsState, RAM-DB, Configs, automation_log** | [`automation-state.card.md`](./cards/automation-state.card.md) | stable |
| **collector: DB-Schema, Tabellen, Retention** | [`collector-db-schema.card.md`](./cards/collector-db-schema.card.md) | stable |
| **collector: Feldnamen, Einheiten, Vorzeichen, `W_AC_Inv` ≠ PV** | [`collector-feldnamen-referenz.card.md`](./cards/collector-feldnamen-referenz.card.md) | stable |
| **collector: Aggregat-Pipeline, raw → 1min → daily → monthly** | [`collector-aggregation-pipeline.card.md`](./cards/collector-aggregation-pipeline.card.md) | stable |
| **collector: Fronius-Modbus, Solar-API, raw_data-Schreiber** | [`collector-fronius-collector.card.md`](./cards/collector-fronius-collector.card.md) | stable |
| **collector: Wattpilot-Polling, `eto`, `wattpilot_daily`** | [`collector-wattpilot-collector.card.md`](./cards/collector-wattpilot-collector.card.md) | stable |
| **collector: FritzDECT, AIN-Mapping, Steckdosen-Polling** | [`collector-fritzdect-collector.card.md`](./cards/collector-fritzdect-collector.card.md) | stable |

## Cards nach Domäne

### automation (Schicht C)
- [`automation-engine.card.md`](./cards/automation-engine.card.md) — Tick-Loop, Regel-Registry
- [`automation-battery-algorithm.card.md`](./cards/automation-battery-algorithm.card.md) — Fronius-BatteryConfig-Schreibpfad
- [`automation-regel-heizpatrone.card.md`](./cards/automation-regel-heizpatrone.card.md) — HP, 6 Phasen, ExternalRespect
- [`automation-regel-wattpilot.card.md`](./cards/automation-regel-wattpilot.card.md) — Wallbox, SOC-Schutz, WS
- [`automation-steuerungsphilosophie.card.md`](./cards/automation-steuerungsphilosophie.card.md) — Prioritäten + Matrix
- [`automation-schutzregeln.card.md`](./cards/automation-schutzregeln.card.md) — Tier-1, SLS, No-Op
- [`automation-state.card.md`](./cards/automation-state.card.md) — RAM-DB, Persist, Configs

### collector (Schicht A)
- [`collector-db-schema.card.md`](./cards/collector-db-schema.card.md) — Tabellen + Retention
- [`collector-feldnamen-referenz.card.md`](./cards/collector-feldnamen-referenz.card.md) — Konventionen, Dupletten
- [`collector-aggregation-pipeline.card.md`](./cards/collector-aggregation-pipeline.card.md) — raw → daily → monthly
- [`collector-fronius-collector.card.md`](./cards/collector-fronius-collector.card.md) — Modbus + Solar-API
- [`collector-wattpilot-collector.card.md`](./cards/collector-wattpilot-collector.card.md) — WS-Polling, `eto`
- [`collector-fritzdect-collector.card.md`](./cards/collector-fritzdect-collector.card.md) — AHA-API, AIN-Mapping

### diagnos (Schicht D)
_(folgt in Phase 5)_

### steuerbox (Schicht E)
_(folgt in Phase 5; `doc/steuerbox/LLM_AUSFUEHRUNG.md` ist Vorlage)_

### netzqualitaet
_(folgt in Phase 5)_

### system
_(folgt in Phase 5)_

### web
_(folgt in Phase 5)_

## Konventionen

- Card-Name: `<domain>-<modul>.card.md` (Bindestrich, lowercase, Domain-Präfix).
- Status: `stable` (Standard), `experimental`, `deprecated`.
- Deprecated Cards bleiben gelistet, klar markiert — als Negativ-Lenkung („nicht mehr verwenden").

## Pflege

Pre-commit-Hook (`tools/pre_commit_doc_check.py`) verifiziert: Frontmatter, existierende Code-Anchors, INDEX-Konsistenz (keine Karteileichen), `last_review = heute` bei jeder Card-Änderung. Drift-Engine (Pi5-Cron, ab Phase 5) erzeugt Tasks bei Code-Doku-Drift.
