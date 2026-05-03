---
title: Battery-Algorithm (SOC-Modus, Schreibpfad Fronius)
domain: automation
role: C
applyTo: "automation/engine/aktoren/aktor_batterie.py"
tags: [batterie, soc, fronius, modbus]
status: stable
last_review: 2026-05-03
---

# Battery-Algorithm

## Zweck
Setzt SOC-Grenzen (`soc_min`, `soc_max`) und Lademodus an der Fronius GEN24 — der einzige Hardware-Eingriff in die Batterie. Erfolgt über die Fronius-HTTP-Config-API (nicht Modbus).

## Code-Anchor
- **Aktor:** `automation/engine/aktoren/aktor_batterie.py:AktorBatterie.ausfuehren`
- **API-Schicht:** `fronius_api.py:BatteryConfig.write` (+ `set_soc_min`, `set_soc_max`, `set_soc_mode`)
- **Diagnose-Tool (kein Schreibpfad im Daemon):** `automation/battery_control.py`
- **State:** `config/battery_scheduler_state.json` (Legacy-Fallback `soc_min_last`/`soc_max_last`)
- **Matrix:** `config/soc_param_matrix.json` Regelkreise `morgen_soc_min`, `nachmittag_soc_max`

## Inputs / Outputs
- **Inputs:** Engine-Zielwerte aus Regeln (z. B. `RegelMorgenSocMin`/`RegelNachmittagSocMax` in `automation/engine/regeln/soc_steuerung.py`), Operator-Overrides, ExternalRespect-Tracker.
- **Outputs:** HTTP-Writes an Fronius (`BAT_M0_SOC_MIN`, `BAT_M0_SOC_MAX`, `BAT_M0_SOC_MODE` ∈ {auto, manual}, `HYB_EVU_CHARGEFROMGRID`).

## Invarianten
- Schreibpfad ausschließlich über `BatteryConfig.write`. Kein Modbus-Schreibzugriff im produktiven Pfad (GEN24 22 A HW-Limit macht `InWRte`/`OutWRte` wirkungslos).
- Bei `Soll == Ist` liefert `BatteryConfig.write()` ein `_NoOpResult` (truthy, `.noop=True`) statt `None` — verhindert FEHLER-Cooldown im Aktor (`fronius_api.py:_NoOpResult`, Fix 2026-04-27).
- Nach erfolgreichem Schreiben muss Engine den Zielwert registrieren (siehe `automation-engine.card.md` → ExternalRespect).

## No-Gos
- Keine Lade-/Entlade-Raten setzen (entfernt 2026-03-07).
- Keine direkte Manipulation der Modbus-Register 40309/40311/40316/40317/40321 im Daemon-Pfad. `battery_control.py` ist Diagnose-Werkzeug, kein Aktor.
- `soc_schutz` existiert nicht mehr — SOC<5 % wird durch Tier-1-Alarm abgefangen, nicht durch eine Regel.

## Häufige Aufgaben
- SOC-Min für Morgen anpassen → `automation/engine/regeln/soc_steuerung.py:RegelMorgenSocMin` + Matrix-Eintrag `morgen_soc_min.morgen_vorlauf_min`.
- Schreibverhalten bei No-Op debuggen → `fronius_api.py:_NoOpResult` + `automation/engine/aktoren/aktor_batterie.py:_retry` (truthy-Check; explizite `.noop`-Auswertung als Tech-Debt offen).
- Default-Werte prüfen → `config/battery_control.json` (Diagnose-Tool-Defaults, nicht Daemon-Defaults).

## Bekannte Fallstricke
- `battery_scheduler_state.json` ist **nur Legacy-Fallback**, keine Quelle der Wahrheit. Quelle = Fronius-Live-Wert + Matrix.
- `soc_min_morgen` ist **kein** Hardcoded-Wert sondern Matrix-Parameter (`morgen_soc_min.morgen_vorlauf_min`).
- Wattpilot-Ladung kann SOC kritisch ziehen → siehe `automation-regel-wattpilot.card.md` (RegelWattpilotBattSchutz hebt `soc_min` an).
- `HYB_EVU_CHARGEFROMGRID` (Netzladen) wird selten gesetzt; bei Änderung Konflikt mit `RegelMorgenSocMin` prüfen.

## Verwandte Cards
- [`automation-engine.card.md`](./automation-engine.card.md)
- [`automation-regel-wattpilot.card.md`](./automation-regel-wattpilot.card.md) — SOC-Notschutz bei EV-Last
- [`automation-schutzregeln.card.md`](./automation-schutzregeln.card.md) — Tier-1, SOC<5 %

## Human-Doku
- `doc/automation/FRONIUS_SOC_MODUS.md`
- `doc/automation/AUTOMATION_ARCHITEKTUR.md`
