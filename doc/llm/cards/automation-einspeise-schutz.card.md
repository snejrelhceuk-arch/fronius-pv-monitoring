---
title: Einspeise-Schutz (Nulleinspeisungs-Guard)
domain: automation
role: C
applyTo: "automation/engine/regeln/einspeise_schutz.py"
tags: [einspeisung, nulleinspeisung, schutz, soc, grid]
status: stable
last_review: 2026-07-02
---

# Einspeise-Schutz

## Zweck
Schutzregel gegen anhaltende **Netzeinspeisung** (Vertrag = *Nulleinspeisung*). Erkennt Einspeisung (Sensorik), protokolliert sie robust (Logging), alarmiert (Warn-Mail) und reagiert steuerungstechnisch — primär durch Öffnen des Batterie-Puffers (SOC_MAX→100 %). Ergänzt die zwei bisherigen, unabhängig voneinander ausfallbaren Säulen (GEN24-Soft-Limit + Batterie-Senke).

## Anlass
Zwischenfall **2026-07-02**: Morgenregel deckelte SOC_MAX auf 75 % (LFP-Schonung), Batterie ab 09:01 voll, **F3 (Ost-WR) gehorchte dem GEN24-Soft-Limit nicht** → 2,97 kWh Einspeisung (Norm < 1 kWh). Keine Instanz reagierte; das Event endete erst um 14:29, als ein Steuerbox-Override SOC_MAX auf 100 % hob (Grid −400 W → +18 W). Genau diese Aktion ist jetzt die automatische Stufe‑1‑Reaktion.

## Code-Anchor
- **Regel:** `automation/engine/regeln/einspeise_schutz.py:RegelEinspeiseSchutz`
- **Registrierung:** `config/engine_registry.json` (nach `sls_schutz`) + Fallback `automation/engine/registry.py:DEFAULT_REGELN_SPEC`
- **Parameter:** `config/soc_param_matrix.json` → `regelkreise.einspeise_schutz`
- **Koordination:** `automation/engine/regeln/soc_steuerung.py:_einspeise_guard_haelt_soc_offen` (Morgenregel setzt SOC_MAX‑Deckelung aus, solange der Guard offen hält)
- **Event-Log:** `logs/einspeise_guard.log` (+ `logs/schaltlog.txt` über Actuator)

## Inputs / Outputs
- **Inputs:** `ObsState.grid_power_w` (Export = negativ), `soc_max`, `soc_mode`, `batt_soc_pct`, `ww_temp_c`, `heizpatrone_aktiv`, `klima_aktiv`; Tages-Kumulativ aus `data_1min.W_Einspeis` (read-only, gecached).
- **Outputs:** `set_soc_max=100` + `set_soc_mode=auto` (Aktor `batterie`); opt-in `hp_ein`/`klima_ein` bzw. Provokation (Aktor `fritzdect`); engine_flag `einspeise_guard_soc_open_bis` (RAM-DB); Warn-Mail; Event-Log.

## Auslöse-Logik
- **Sustained-Integral:** Σ(Export_W) der letzten `sustained_fenster_min` Ticks / 60000 → kWh. Nur gewertet, wenn Momentan-Export ≥ `sustained_veto_w` **und** ≥ `sustained_min_hit_pct` der Fenster-Samples über Veto liegen (filtert einzelne Curtailment-Transienten wie −15 kW-Spitzen).
- **Tages-Kumulativ:** heutige Einspeisung vs. `baseline_einspeis_kwh`.
- **WARN** wenn Kumulativ ≥ Baseline·`warn_faktor` (Default +50 %) ODER Sustained ≥ `sustained_warn_kwh` → nur Log + Mail.
- **ACT** wenn Kumulativ ≥ Baseline·`akt_faktor` (Default +100 %) ODER Sustained ≥ `sustained_akt_kwh` → Log + Mail + Reaktions-Leiter (Score = `score_gewicht`·1.5).

## Reaktions-Leiter (ACT)
1. **Stufe 1 (Default, bewährt):** `SOC_MAX→100 %` + `SOC_MODE→auto`. Öffnet den Batterie-Puffer; setzt `einspeise_guard_soc_open_bis` für `soc_open_cooldown_min`, damit die Morgenregel nicht sofort auf 75 % zurückdeckelt.
2. **Stufe 2 (opt-in `dumpload_aktiv`):** Dump-Load `hp_ein`/`klima_ein`, wenn Batterie faktisch voll (`SOC ≥ dumpload_soc_min_pct`) und WW < `dumpload_ww_temp_max_c`.
3. **Stufe 3 (opt-in `provokation_aktiv`):** eingeschaltete Verbraucher AUS→EIN (hängenden SmartMeter/WR-Regelkreis anstoßen), Abstand `provokation_min_abstand_min`.

## Invarianten
- Steuerung ausschließlich über **SOC_MIN/SOC_MAX** via Fronius HTTP-API (`fronius_api.BatteryConfig`) — **keine** Ratenlimits (InWRte/OutWRte/StorCtl_Mod). Siehe `AGENTS.md` No-Go 3.
- Name enthält `schutz` → läuft im Schutz-Pass (`engine.py:Engine.zyklus`) IMMER, unabhängig von Optimierungs-Gewinnern.
- Einzelne Export-Transienten dürfen **nicht** auslösen (Hit-Quote-Filter) — sonst würde die Morgen-Deckelung an normalen Tagen dauernd ausgehebelt.
- Logging robust in Datei + `schaltlog.txt`; **nicht** auf `automation_log` (DB) verlassen (dort Persistenz seit 2026-05-29 gestört).

## No-Gos
- Dump-Load/Provokation nicht ohne Review scharfschalten (Konflikt mit Geräteregeln bzw. AUS-Phase erhöht Einspeisung kurzzeitig).
- Keine Hardware-Calls außerhalb der Aktor-Klassen.

## Häufige Aufgaben
- Schwellen justieren → `config/soc_param_matrix.json` → `einspeise_schutz` (Daemon-Restart nötig, K-04).
- Dump-Load/Provokation aktivieren → `dumpload_aktiv` / `provokation_aktiv` auf `true`.
- Guard abschalten → `engine_registry.json` Eintrag `"aktiv": false` oder Matrix `aktiv:false`.

## Bekannte Fallstricke
- Batterie bereits voll (SOC_MAX=100, SOC≈100) → Stufe 1 wirkungslos; ohne Dump-Load warnt der Guard nur (korrekt: echter WR-Fehler → Mensch/Fronius-Support).
- `obs.grid_power_w` Vorzeichen: **negativ = Einspeisung** (siehe `collector-feldnamen-referenz.card.md`).
- Der Guard behebt **nicht** die Fronius-seitige Ursache (F3 ohne Curtailment) — dafür Support-Report `doc/system/FRONIUS_SUPPORT_EINSPEISUNG_2026-07-02.md`.

## Verwandte Cards
- [`automation-battery-algorithm.card.md`](./automation-battery-algorithm.card.md) — SOC-Schreibpfad
- [`automation-engine.card.md`](./automation-engine.card.md) — Schutz-Pass, Registry
- [`automation-schutzregeln.card.md`](./automation-schutzregeln.card.md) — Schutzschicht
- [`collector-feldnamen-referenz.card.md`](./collector-feldnamen-referenz.card.md) — `P_Netz`/Vorzeichen

## Human-Doku
- `doc/system/FRONIUS_SUPPORT_EINSPEISUNG_2026-07-02.md`
- `doc/automation/AUTOMATION_ARCHITEKTUR.md`
