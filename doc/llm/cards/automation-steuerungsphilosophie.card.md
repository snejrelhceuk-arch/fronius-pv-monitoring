---
title: Steuerungsphilosophie (Prioritäten, ExternalRespect, Matrix)
domain: automation
role: C
tags: [philosophie, prioritaet, matrix, external-respect]
status: stable
last_review: 2026-05-03
---

# Steuerungsphilosophie

## Zweck
Übergreifende Designprinzipien für die Engine. Wer einen neuen Regelpfad oder ein neues Verbrauchergerät einbaut, muss diese Prinzipien einhalten — sonst entstehen stille Doppelschaltungen oder Endlos-ExternalRespect-Holds.

## Code-Anchor
- **Engine-Zyklus:** `automation/engine/engine.py:Engine.zyklus`
- **Regel-Registry:** `automation/engine/engine.py:_register_default_regeln`
- **Parameter-Matrix:** `automation/engine/param_matrix.py:lade_matrix`
- **Matrix-Quelle:** `config/soc_param_matrix.json` (Single Source of Truth)
- **ExternalRespect (HP):** `automation/engine/regeln/geraete.py:RegelHeizpatrone._cancel_conflicting_overrides`
- **ExternalRespect (WP):** `automation/engine/regeln/waermepumpe.py:_pruefe_extern_respekt`

## Inputs / Outputs
- **Inputs:** Beobachtungen (ObsState), Matrix-Parameter, Operator-Overrides, Tier-1-Flags.
- **Outputs:** geordnete Aktor-Aufrufe.

## Invarianten
**Prioritäten (von hart nach weich):**
1. Tier-1-Schutz (Engine-Bypass): `Tier1Checker` (batt_temp, SOC<5 %)
2. Schutzregeln: `RegelSlsSchutz`, `RegelWattpilotBattSchutz`
3. Komfort-Reset: `RegelKomfortReset` (täglich 25–75 %)
4. Optimierung: `RegelMorgenSocMin`, `RegelNachmittagSocMax`, `RegelZellausgleich`, `RegelForecastPlausi`
5. Verbraucher: `RegelHeizpatrone`, `RegelKlimaanlage`, `RegelWw/HeizAbsenkung`, `RegelWwBoost`, `RegelWpPflichtlauf`, `RegelHeizBedarf`, `RegelWw/HeizVerschiebung`

**ExternalRespect:** Wird eine extern (App, Hand, anderes System) ausgelöste Schaltung erkannt, akzeptiert die Engine sie und tritt für `extern_respekt_s` (Matrix, Default 1800 s) zurück. Voraussetzung: Engine registriert eigene erfolgreiche Schreibvorgänge, sonst Fehlinterpretation.

**Matrix als Single Source:** Alle Schwellen, Hysteresen, Zeiten in `config/soc_param_matrix.json`. Hartcodierung ist No-Go.

## No-Gos
- Keine Hartcodierung von Schwellen.
- Keine neue Verbraucherregel ohne Score-Cascade-Berücksichtigung.
- Keine Hardware-Calls außerhalb der Aktor-Klassen.
- Keine Software-Lade-/Entlade-Limits (GEN24 HW-Limit).

## Häufige Aufgaben
- Neuen Verbraucher hinzufügen → neue Regel + neuer Aktor + Matrix-Block + Score-Position bestimmen (siehe `automation-engine.card.md`).
- Prioritätskonflikt analysieren → `Engine.zyklus` Logging auf Score und Aktor-Cascade-Gewinn.
- Matrix-Reload nach Änderung → K-04 (offen, siehe `doc/TODO.md`); aktuell Daemon-Restart.

## Bekannte Fallstricke
- ExternalRespect-Endlos-Hold: Wenn Aktor schreibt, Engine aber nicht registriert → nächste Lesung wird als "extern" interpretiert. Lösung: `_registriere_erfolgreiche_soc_aktionen()` nach jedem Aktor-OK.
- Wattpilot-rbt-Reset (Recovery): noch ungeprüft, vorsichtig behandeln.
- ~40 versteckte Parameter in `pv-config.py` ohne Matrix-Eintrag — offen (Audit-TODO).
- Reihenfolge in `_register_default_regeln` = Tiebreaker bei gleichem Score.

## Verwandte Cards
- [`automation-engine.card.md`](./automation-engine.card.md)
- [`automation-schutzregeln.card.md`](./automation-schutzregeln.card.md)
- [`automation-state.card.md`](./automation-state.card.md)
- [`steuerbox-intents.card.md`](./steuerbox-intents.card.md) — _(folgt Phase 5)_

## Human-Doku
- `doc/automation/AUTOMATION_ARCHITEKTUR.md`
- `doc/automation/PV_CONFIG_HANDBUCH.md`
