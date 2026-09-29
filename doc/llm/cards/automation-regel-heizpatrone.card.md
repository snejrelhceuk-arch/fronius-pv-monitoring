---
title: Regel Heizpatrone (Phasen, Hysterese, ExternalRespect)
domain: automation
role: C
applyTo: "automation/engine/regeln/geraete_heizpatrone.py"
tags: [heizpatrone, fritzdect, ww-speicher, prognose]
status: stable
last_review: 2026-09-29
---

# Regel Heizpatrone

## Zweck
Schaltet die Heizpatrone (im WW-Speicher, FritzDECT-Steckdose) abhängig von PV-Prognose, SOC, WW-Temperatur und Tageszeit. Phasen 0, 1, 1b, 2, 4 decken den Tagesverlauf ab (Phase 2 umfasst Mittag und Nachmittag).

Zusätzlich pausiert die Regel bei aktivem `afternoon_charge_request` den HP-Betrieb bis das Ziel-SOC erreicht ist (oder Hold endet), damit die Batterie priorisiert aufgeladen werden kann.

## Code-Anchor
- **Regel:** `automation/engine/regeln/geraete_heizpatrone.py:RegelHeizpatrone.bewerte`
- **Override-Annullation:** `automation/engine/regeln/geraete_heizpatrone.py:RegelHeizpatrone._cancel_conflicting_overrides`
- **WP-Koordinations-Cap:** `automation/engine/regeln/geraete_heizpatrone.py:RegelHeizpatrone._dynamic_temp_max_c`
- **Gemeinsame AUS-Entscheidung (Single-Source für Score + Aktion):** `automation/engine/regeln/geraete_heizpatrone.py:RegelHeizpatrone._aus_kontext_pruefen` — zusammen mit `_ww_temp_aus_pruefen` (dyn. Cap), `_phase4_aus_pruefen`, `_phase0_haushalt_netto`; von `bewerte()` (Score) UND `erzeuge_aktionen()` (Aktion) genutzt.
- **Gemeinsame EIN-Entscheidung (Single-Source für Score + Aktion):** `automation/engine/regeln/geraete_heizpatrone.py:RegelHeizpatrone._ein_entscheidung` — liefert Phase (0/1/1b/2/4), Burst-Dauer, Score-Gewicht sowie Probe-/Drain-Flag; von `bewerte()` (Score) UND `erzeuge_aktionen()` (Aktion/Zustand) genutzt.
- **Momentan-Überschuss-Override (Konkurrenz/Ladewunsch):** `automation/engine/regeln/geraete_heizpatrone.py:RegelHeizpatrone._ueberschuss_traegt_hp`
- **WW-Temp-AUS (weiche Caps weichen der Autorität):** `automation/engine/regeln/geraete_heizpatrone.py:RegelHeizpatrone._ww_temp_aus_pruefen`
- **Dauerbetrieb (Steuerbox-Ersatzheizung, Hard-Stop + WP-Defer):** `automation/engine/regeln/geraete_heizpatrone.py:RegelHeizpatrone._dauerbetrieb_hard_stop`, `RegelHeizpatrone._wp_laeuft`; Intent-Reader `automation/engine/operator_intents.py:read_active_hp_dauerbetrieb_intent`
- **Aktor:** `automation/engine/aktoren/aktor_fritzdect.py:AktorFritzDECT.ausfuehren` (Kommando `hp_ein`/`hp_aus`)
- **Matrix:** `config/soc_param_matrix.json` Regelkreis `heizpatrone`
- **AIN-Mapping:** `config/fritz_config.json`
- **Referenz:** `config/heizpatrone_fritz_reference.json`

## Inputs / Outputs
- **Inputs:** ObsState (`P_PV`, `P_Netz`, `SOC_Batt`, `WW_Temp`), Forecast (Tages-kWh), Matrix-Parameter (`extern_respekt_s`, Phasenschwellen), Operator-Overrides.
- **Outputs:** FritzDECT-Schaltbefehl `hp_ein`/`hp_aus`, Engine-Zielwert für ExternalRespect-Tracker.

## Invarianten
- **Grundprinzip:** Die Heizpatrone ist ein Verbraucher für PV-Überschuss. Sie darf grundsätzlich **keinen Netzbezug verursachen**. Toleriert sind ausschließlich kurze Schaltverluste durch Lastwechsel/Erzeugungsschwankungen (Wattpilot-Start, Wolkenfront, Backofen), bis die Wechselrichter sich angepasst haben.
- **AUS-Entscheidung ist Single-Source:** `bewerte()` (Score) und `erzeuge_aktionen()` (Aktion) leiten die AUS-Kriterien aus **denselben** Helfern ab (`_ww_temp_aus_pruefen` mit dyn. WP-Koordinations-Cap in BEIDEN Pfaden, `_phase4_aus_pruefen`, `_aus_kontext_pruefen` für Entladung/Konkurrenz/Netzbezug, `_phase0_haushalt_netto` mit HP+WP-Herausrechnung). Kein getrennter Zweitpfad → Score und Aktion können nicht mehr auseinanderlaufen.
- **EIN-Entscheidung ist Single-Source:** Die Phasen-EIN-Entscheidung liegt allein in `_ein_entscheidung()` (Phase 0/1/1b/2/4 inkl. Burst-Dauer, Probe- und Drain-Flag). `bewerte()` nimmt daraus das Score-Gewicht, `erzeuge_aktionen()` Phase/Burst/Zustand — kein zweiter Entscheidungspfad. Die tatsächliche Schaltung ist die Schnittmenge beider Methoden: der `bewerte()`-Score entscheidet im Engine-Lauf, ob `erzeuge_aktionen()` überhaupt aufgerufen wird. Phase 2 gilt für Mittag **und** Nachmittag (rest_h < 3 h → höhere `batt_reserve_nachmittag_kwh`; die frühere separate Phase 3 ist darin aufgegangen). Phase-2-Freigabe nur über `rest_kwh > batt_rest + reserve` (bei SOC≈MAX ist `batt_rest` ≤ ~1 kWh, daher war die frühere Zusatzbedingung `rest_kwh > min_rest_kwh` nie separat erreichbar).
- Prognose-Klassifikation (**absolut**, aus Tages-Rest-kWh): `<40 kWh = schlecht`, `40–100 = mittel`, `≥100 kWh = gut` → bestimmt Freigabegrad pro Phase. Die Bedingungen (`_potenzial`/`_hp_parallel_erlaubt`/`_min_lade_nach_potenzial`/`_batt_entladung_toleriert`) vergleichen die numerische Stufe (`FC_TIER_*` via `forecast_tier_of`), nicht Synonym-Strings; ClearSky-relative Anzeige bleibt getrennt.
- AUS-Schwellen (immer aktiv): `WW_Temp ≥ 78 °C` (Hart), `SOC ≤ stop_entladung_unter` (5 %), `SOC ≤ extern_aus_soc_pct` (15 %, nur bei Extern-EIN), Netzbezug-Energie-Integral, `PV<1500 W` in PV-only-Phasen.
- **WP-Koordinations-Cap (`_dynamic_temp_max_c`, seit 2026-05-28):** kontextabhängige Verschaerfung der WW-Temp-Schwelle, damit der Dimplex-WP-Lauf möglich bleibt und der mechanische Thermostat (~72 °C) nicht hart abwirft.
  - `now_h < drain_fenster_ende_h` (Morgens) → Cap = `drain_aus_ww_temp_c` (Default 55 °C, Bereich 50–65).
  - `<= abend_ww_cap_aktiv_vor_sunset_h` vor Sunset → Cap = `abend_ww_temp_c` (Default 65 °C, Bereich 60–70).
  - Sonst → Hart-Cap `speicher_temp_max_c` (78 °C).
  Wirkt **sowohl AUS-Pfad als auch EIN-Pfad**; Phasen-Reihenfolge, Score, Forecast-Bedingungen, Netzbezug-Integral, ExternalRespect bleiben unberührt.
  - **Weiche Caps weichen der Autorität:** Bei manueller/Operator-Autorität (`ist_extern` — manueller HP-EIN *oder* Steuerbox-`hp_toggle(on)`, beide als Extern-EIN erkannt) prüft `_ww_temp_aus_pruefen(nur_hart_cap=True)` **nur** die harte Schwelle `speicher_temp_max_c` (78 °C). Die weichen drain/abend-Caps schalten dann **nicht** ab und cancellen die Override **nicht** — der Bediener darf den WW-Speicher bewusst über die Abend-/Drain-Grenze aufheizen (z. B. bei WP-Defekt, HP als Ersatzheizung). Nur die 78-°C-Schwelle (nahe mechanischem Thermostat ~72 °C) bleibt zwingend.
- **Netzbezug-AUS (`_netzbezug_aus_ausloesen`, seit 2026-05-16, Vorfall »3 h Netzbezug im Drain«):** Energie-Integral-Verfahren
  1. **Veto:** Aktueller Bezug `< aus_netzbezug_aktuell_veto_w` (200 W) → keine Auswertung (Historie evtl. veraltet, kein akuter Bezug).
  2. **Messung:** Σ der positiven `grid_power_w`-Samples der letzten `aus_netzbezug_fenster_min` (5) Engine-Ticks (≈ 60 s/Tick) als Energie (kWh = Σ_W / 60000).
  3. **Auslöser:** Energie ≥ `aus_netzbezug_energie_kwh` (0.1 kWh ≡ Ø 1200 W über 5 Min) → HP AUS. Schaltspitzen (z. B. einmal 3 kW für 30 s) bleiben darunter. Wert erhöht 2026-05-25 (vorher 0.02 kWh).
  Es gibt **keine Vetos durch Forecast-Rest, Winter-Schutz oder Transient-Fenster mehr**. Winter-Tiefentladung wird über das **dynamische SOC_MIN-Sliding (5–25 %)** in `RegelSocSteuerung` und die HART-Schwellen `stop_entladung_unter`/`extern_aus_soc_pct` abgesichert, nicht durch toleriertes HP-Netzbezug.
- Begriff **„Notaus"** ist reserviert für menschen-/spannungsbezogene Schutzkontexte (BYD-BMS, Tier-1-Alarm). Im HP-Kontext heißt es **„AUS"** (`aus_grund`, `_netzbezug_aus_ausloesen`, `extern_aus_soc_pct`, AUS-Pfad, AUS-Kriterienwerk).
- **Override-Cancellation (seit 2026-07-23):** Regel cancelt automatisch konfligierende `hp_toggle(state=on)` Overrides bei starken AUS-Bedingungen (HARTE Kriterien, Verbraucher-Konkurrenz, Batterie-Entladung, Netzbezug, Phase 4). Verhindert Pingpong: Override will EIN → Regel schaltet AUS → Override reapplied → ... Normales Burst-Ende (Timer abgelaufen) cancelt NICHT.
- Externe Schaltung erkannt → `_cancel_conflicting_overrides()` annulliert offene Operator-Overrides + setzt 30-min-Respekt-Hold (`extern_respekt_s`).
- Schreibbestätigung: Aktor muss Engine-Wert registrieren, sonst falsch-positive Extern-Erkennung.
- Bei aktivem Nachmittags-Ladewunsch (`afternoon_charge_request` + `pause_hp_until_target=true`) schaltet die Engine HP AUS **nur wenn** `0 < batt_power_w < 8000 W` (Batterie laedt mit schwacher Leistung). Bei fehlender Ladung (Batterie idle/entlaedt) oder starker Ladung (>=8 kW) bleibt HP freigegeben.
- **Momentan-Überschuss-Override (`_ueberschuss_traegt_hp`):** Sowohl die Verbraucher-Konkurrenz-AUS (`_aus_kontext_pruefen`, Grund `konkurrenz`) als auch die Ladewunsch-Pause weichen, wenn der momentane PV-Überschuss die HP nachweislich trägt: `grid_power_w < ueberschuss_grid_bezug_max_w` (300 W) **und** `batt_power_w ≥ -ueberschuss_batt_entlade_tol_w` (−300 W) **und** `SOC ≥ ueberschuss_soc_hoch_pct` (85 %, Batterie nahe voll). Dann bleibt HP EIN — die Energie ginge sonst in die Abregelung. Das Netzbezug-Integral (`_netzbezug_aus_ausloesen`) bleibt die eigentliche Schutzinstanz gegen echten Netzbezug; bei niedrigerem SOC hat die Batterieladung weiter Vorrang.
- **HP-Dauerbetrieb (Ersatzheizung bei WP-Defekt, Steuerbox `hp_dauerbetrieb`):** höchste HP-Priorität außer WW-Übertemperatur. Bei aktivem Intent (`read_active_hp_dauerbetrieb_intent`) zwingt die Regel HP EIN/hält sie und überstimmt weiche Caps, Konkurrenz, Ladewunsch, SOC-Floor und Netzbezug (läuft bewusst aus dem Netz, zeitlich begrenzt 8 h / max 24 h). Einzige Software-AUS: `WW ≥ speicher_temp_max_c` (78 °C) mit Hysterese `dauerbetrieb_ww_hysterese_k`; ein laufender WP (`≥ drain_max_wp_w`, `_wp_laeuft`) hebt den Zwang auf → normale Logik. Physischer Restschutz: 35-A-Netzanschluss-Sicherung. Tier-1/BYD-BMS bleiben vorrangig (Dauerbetrieb ist tier-2).

## No-Gos
- Keine HP-Einschaltung bei Tier-1-Alarm.
- Keine HP-Einschaltung bei Operator-Override `hp_aus` ohne Respekt-Ablauf.
- Keine Hartcodierung von Schwellen — alles in Matrix.

## Häufige Aufgaben
- Phasenschwelle ändern → Matrix `heizpatrone.<phase>.<param>` (z. B. `phase2.soc_min_freigabe`).
- ExternalRespect-Dauer ändern → Matrix `heizpatrone.extern_respekt_s` (Default 1800).
- WP-Koordinations-Cap justieren → Matrix `heizpatrone.drain_aus_ww_temp_c` (Morgens, 50–65), `heizpatrone.abend_ww_temp_c` (Abends, 60–70), `heizpatrone.abend_ww_cap_aktiv_vor_sunset_h` (1–8 h).
- Überschuss-Override justieren → Matrix `heizpatrone.ueberschuss_soc_hoch_pct` (70–95), `heizpatrone.ueberschuss_grid_bezug_max_w` (0–1000), `heizpatrone.ueberschuss_batt_entlade_tol_w` (0–2000).
- Dauerbetrieb justieren → Matrix `heizpatrone.dauerbetrieb_ww_hysterese_k` (0–15); Dauer/Cap in `config.py` bzw. `.infra.local` (`STEUERBOX_HP_DAUERBETRIEB_DEFAULT_S`/`_MAX_S`); Schalter `steuerbox/templates/cockpit.html` + `steuerbox/static/js/cockpit.js`.
- Neue Phase einbauen → `RegelHeizpatrone.bewerte` + Score-Logik + Matrix-Schema dokumentieren.
- HP-Startup-Check (Daemon-Restart schaltet HP AUS) → `automation/engine/automation_daemon.py:_hp_startup_check`.
- Ladewunsch-Pause anpassen → `RegelHeizpatrone.bewerte` und `RegelHeizpatrone.erzeuge_aktionen` (Intent-Lesepfad: `automation/engine/operator_intents.py`).

## Bekannte Fallstricke
- **Stale-Grid-History (2026-05-24):** `_grid_history` wird nur gepflegt wenn HP ON ist. Nach einer OFF-Pause (z.B. 10–30 Min) enthält der Deque noch hohe Bezugswerte aus dem vorherigen EIN-Zeitraum. Phase 1b schaltet HP EIN, Netzbezug-Integral feuert sofort auf Basis der alten Werte — Probe läuft nie durch. **Fix:** `_grid_history.clear()` am Anfang jedes neuen Bursts (beide Stellen in `erzeuge_aktionen`). Die `len < fenster_min`-Guard verhindert dann frühzeitiges Feuern.
- ExternalRespect: Wenn der Aktor erfolgreich schreibt, aber die Engine den Zielwert nicht registriert, erkennt der nächste Tick eine "fremde" Änderung → Endlos-Hold (`hp-extern-respekt-hold-note`).
- FritzDECT-Session: 15 min Cache, bei Fritz!Box-Reboot kurzzeitig 401 → Aktor retry.
- AIN-Mapping aus `fritz_config.json` muss zur HW passen — Vertauschungen sind häufige Quelle stiller Fehlschaltung (`fritzdect-ain-mapping-note`).
- Heizpatronen-Nachtlast (Phase 0 Drain): noch im Aufbau (`heizpatrone-nachtlast-phase0-note`, `heizpatrone-potenzial-schwellen-note`).

## Verwandte Cards
- [`automation-engine.card.md`](./automation-engine.card.md)
- [`automation-steuerungsphilosophie.card.md`](./automation-steuerungsphilosophie.card.md) — ExternalRespect-Konzept
- [`collector-fritzdect-collector.card.md`](./collector-fritzdect-collector.card.md) — AIN-Mapping & Polling

## Human-Doku
- `doc/automation/AUTOMATION_ARCHITEKTUR.md`
- `doc/automation/HP_TOGGLE_OVERRIDE_FLOW.md`
