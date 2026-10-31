---
title: Steuerbox Intents (Validierung, Overrides, Respekt)
domain: steuerbox
role: E
applyTo: "steuerbox/**"
tags: [intent, overrides, respekt, hard-guards, audit]
status: stable
last_review: 2026-10-31
---

# Steuerbox Intents

## Zweck
Schicht E nimmt Operator-Intents entgegen, validiert sie und schreibt sie als Overrides in die RAM-DB. Die Ausfuehrung erfolgt ausschliesslich ueber Schicht C.

## Code-Anchor
- **API-Einstieg:** `steuerbox/steuerbox_api.py:api_intent`
- **Security-Gate:** `steuerbox/steuerbox_api.py:_security_gate`
- **Port-Guard beim Start:** `steuerbox/steuerbox_api.py:_check_port_available`
- **Validatoren:** `steuerbox/validators.py:check_allowlist`, `validate_action`
- **Persistenz/Audit:** `steuerbox/intent_handler.py:handle_intent`, `get_status`, `get_audit`
- **HA-MQTT-Bridge (optional):** `steuerbox/ha_mqtt_bridge.py:HaMqttBridge`
- **Automation-Verarbeitung:** `automation/engine/operator_overrides.py:OperatorOverrideProcessor.process_pending`
- **Konfiguration:** `config.py` (`STEUERBOX_*`, `STEUERBOX_ALLOWED_ACTIONS`)

## Inputs / Outputs
- **Inputs:** `POST /api/ops/intent` mit `action`, `params`, optional `respekt_s`; Hostrolle aus `.role`; CIDR-Allowlist aus `config.py`.
- **Outputs:** DB-Schreibpfad in `/dev/shm/automation_obs.db` (`operator_overrides`, `steuerbox_audit`) und API-Response mit `override_id`, Restlaufzeit, normalisierten Parametern.

### Action-Hinweis
- `wp_mode`: WP-Sollwert-Modus `max | std | min` (oder `neutral`). Mapping `automation/engine/operator_overrides.py:_map_override_to_actions` → `waermepumpe set_ww_soll` + `set_heiz_soll` (Zielwerte aus Parametermatrix via `_resolve_wp_mode_targets`; WW-55 °C-Legionellen-Sperre per Zwischenschritt). **Respekt-Hold:** max/std/min halten den Operator-Sollwert über das Respekt-Fenster — der Override bleibt `active` und die Engine überspringt währenddessen **alle** `aktor=='waermepumpe'`-Regeln (Gate `engine.zyklus` via `operator_intents.read_active_wp_mode_intent`). Sonst würde z. B. `RegelHeizBedarf` den gewählten Soll binnen ~1 min wieder auf Standard setzen. Kein per-Zyklus-Reapply (einmaliger Schreibvorgang beim Hold-Start). `neutral` (oder Respekt-Ablauf) gibt die WP-Automatik wieder frei.
- `afternoon_charge_request`: Tages-Intent für Nachmittags-Ladewunsch. Standardmäßig wird `respekt_s` serverseitig bis Sunset desselben Tages abgeleitet (Fallback 17:00), damit ein HA-Einmal-Trigger ohne zweite Aktion auskommt. Parameter: `target_soc_pct` (default 100), `pause_hp_until_target` (default False seit 2026-05-22), `start_earliest_h` (default 12.0), `start_latest_h` (default 15.0). **Policy-Hold** (`_map_override_to_actions → []`, keine direkte Aktoraktion): der Processor hält nur den Status `active` über das Respekt-Fenster. Die SOC-Öffnung führt `RegelNachmittagSocMax` aus — Ziel `SOC_MAX=target`, **Startzeitpunkt prognose-/SOC-abhängig** im Fenster `start_earliest_h..start_latest_h` (`_berechne_intent_startzeit`: hoher SOC + starke Prognose → spät, damit ~100 % erst spät nachmittags; niedriger SOC/schwache Prognose → früh), 2-Phasen-Schaltung (`SOC_MAX→100` manual, dann `SOC_MODE→auto`).
- `wattpilot_amp`: Ladestrom-Stufen `8 | 16 | 24 A` (oder `neutral`). Validierung in `steuerbox/validators.py`, Cockpit-Button-Reihe in `steuerbox/static/js/cockpit.js`, Mapping `automation/engine/operator_overrides.py:_map_override_to_actions` → `wattpilot set_max_current` (Aktor klemmt hart auf 6–32 A).
- `hp_toggle`: HP An/Aus mit Respekt-Timer (analog `klima_toggle`). Mapping `automation/engine/operator_overrides.py:_map_override_to_actions` → `fritzdect hp_ein`/`hp_aus`; `neutral`/Respekt-Ablauf gibt die HP-Regel wieder frei. Hard-Guards bei EIN: kritischer SOC (`STEUERBOX_HP_AUS_SOC_PCT`) und Übertemperatur (`STEUERBOX_HP_UEBERTEMP_C`). Funktioniert auch bei deaktivierter HP-Automatik (`hp-regel-aktiv=false`). Der frühere `hp_dauerbetrieb`-Intent ist entfernt; Ersatzheizung = HP-Automatik deaktivieren + `hp_toggle=on` (einzige harte Abschaltung: Tier-1-SLS > 35 A).

## Invarianten
- Steuerbox macht keine direkten Hardware-Schreibzugriffe (kein Modbus/FritzDECT/Wattpilot aus E).
- Vor direktem Aktor-Dispatch prueft Schicht C (`OperatorOverrideProcessor`) aktuelle `obs_state`-Hard-Guards und auditiert blockierte Overrides in `steuerbox_audit`.
- Die optionale HA-MQTT-Bridge liest `/api/ha/*` (B) für Telemetrie-Publish und schreibt **ausschliesslich** `afternoon_charge_request` via loopback-POST zu `/api/ops/intent` (Schicht E). Kein direkter Aktor-/Modbus-Schreibpfad.
- IP-Allowlist wird vor der Intent-Verarbeitung geprueft.
- Auf Failover sind nicht-GET Ops-Endpunkte blockiert (`403`, read-only Verhalten).
- Pro Aktion bleibt genau ein Live-Override (`open/active`), aeltere werden auf `released` gesetzt.
- `respekt_s` muss im konfigurierten Bereich liegen (`STEUERBOX_MIN_RESPEKT_S`..`STEUERBOX_MAX_RESPEKT_S`).
- Solange ein `wp_mode`-Hold (max/std/min) aktiv ist, treten **alle** WP-Sollwertregeln (`aktor=='waermepumpe'`) zurück (Engine-Gate), damit der Operator-Soll nicht überschrieben wird.
- Für `afternoon_charge_request` gilt ein eigener Maximalwert (`STEUERBOX_AFTERNOON_MAX_RESPEKT_S`), damit Tages-Holds bis Sunset möglich sind.
- `klima_toggle(state=on)` wird in Schicht C blockiert, solange `klima_cooldown_bis` aktiv ist; Cooldown ueberstimmt Steuerbox-Hold.

## No-Gos
- Keine Imports aus `automation/engine/aktoren/*` in Steuerbox-Modulen.
- Kein Bypass von `validate_action()`.
- Keine neuen Actions ohne Mapping in `OperatorOverrideProcessor._map_override_to_actions`.
- Kein direkter Zugriff auf Fronius/FritzDECT/Wattpilot aus Schicht E.

## Häufige Aufgaben
- Neue Aktion einfuehren -> `config.py:STEUERBOX_ALLOWED_ACTIONS` + `steuerbox/validators.py:validate_action` + `automation/engine/operator_overrides.py:_map_override_to_actions`.
- UI-Meta fuer neue Buttons -> `steuerbox/steuerbox_api.py:api_control_meta` erweitern.
- **Klima-Regelkreis dauerhaft deaktivieren/aktivieren:** `GET/POST /api/ops/klima-regel-aktiv` (direkte Config-API, kein Intent — schreibt `regelkreise.klimaanlage.aktiv` in `soc_param_matrix.json` atomar). Endpoint in `steuerbox/steuerbox_api.py:api_klima_regel_aktiv_get/set`. Failover: read-only (403 auf POST).
- **HP-Regelkreis dauerhaft deaktivieren/aktivieren (analog Klima):** `GET/POST /api/ops/hp-regel-aktiv` (direkte Config-API, kein Intent — schreibt `regelkreise.heizpatrone.aktiv` atomar). Endpoint `steuerbox/steuerbox_api.py:api_hp_regel_aktiv_get/set` (nutzt `_set_regelkreis_aktiv`). Cockpit-Schalter „HP-Steuerung" (`buildHpRegelControl`/`buildRegelControl`). Deaktiviert die HP-Automatik; `hp_toggle` schaltet dann frei An/Aus. Immer-aktive Ausnahme: `RegelSlsSchutz` (Tier 1, Phasenstrom > 35 A → HP AUS). Failover: read-only (403 auf POST).
- **Alle SOC-Automationen deaktivieren/aktivieren (Batterie-Formatierung):** `GET/POST /api/ops/soc-automation-aktiv` (direkte Config-API, kein Intent — schreibt Top-Level `soc_automation_aktiv` in `soc_param_matrix.json` atomar). Endpoint `steuerbox/steuerbox_api.py:api_soc_automation_aktiv_get/set`, Setter `_set_soc_automation_aktiv`. Cockpit-Schalter „SOC-Automation“ (Batterie-Karte) mit **zweistufiger Ja/Nein-Rückfrage bei Deaktivierung** (`steuerbox/static/js/cockpit.js:confirmSocAutomationAus`/`buildSocAutomationControl`). `false` → Engine überspringt alle `aktor=='batterie'`-Regeln (s. `automation-battery-algorithm.card.md`). Failover: read-only (403 auf POST).
- Override-Lebenszyklus debuggen -> `GET /api/ops/status` und `GET /api/ops/audit` vergleichen.
- HA-Ladewunsch anbinden -> `action='afternoon_charge_request'` mit optionalen Parametern (`target_soc_pct`, `pause_hp_until_target`, Startfenster 12-15h).
- MQTT-Button in HA: Bridge subscribt `{state_prefix}/{node_id}/cmd/afternoon_charge_request` (payload `PRESS`/`ON`) und POSTet Intent lokal zu `HA_BRIDGE_STEUERBOX_BASE/api/ops/intent`.
- HA-Wattpilot anbinden -> MQTT-Topics der Bridge read-only für Telemetrie nutzen; Schaltvorgänge bleiben in HA auf der bestehenden Wattpilot-Integration.
- Für Energy-Dashboards liefert die Bridge Wattpilot-Gesamtenergie und Session-Energie als dedizierte MQTT-Sensoren.
- **Flow-Bubble-Komfort (Web B → Cockpit E):** Die Flow-Bubbles verlinken Komfort-Aktionen als **Deep-Link** auf das Cockpit (`steuerbox/templates/cockpit.html`, Anker `#card-wp`/`#card-wattpilot`/`#card-battery`/`#card-toggles`), nie als direkter POST aus der Web-UI. Ziel-URL: `config.STEUERBOX_COCKPIT_URL` bzw. abgeleitet aus Host + `config.STEUERBOX_EXTERNAL_PORT` (nginx-TLS-Port, i. d. R. 11933; **nicht** der interne Flask-Bind `STEUERBOX_PORT`). Details: `web-flow-view.card.md`.

## Bekannte Fallstricke
- Sicherheitsdoku beschreibt teils Bearer-Token; Ist-Stand im Code: Auth via mTLS-Reverse-Proxy, Validator prueft nur Allowlist.
- Override-Holds wirken nur, wenn `OperatorOverrideProcessor` im Automation-Zyklus regelmaessig laeuft.

## Verwandte Cards
- [`automation-engine.card.md`](./automation-engine.card.md)
- [`automation-state.card.md`](./automation-state.card.md)
- [`automation-steuerungsphilosophie.card.md`](./automation-steuerungsphilosophie.card.md)
- [`diagnos-health.card.md`](./diagnos-health.card.md)

## Human-Doku
- `doc/steuerbox/ARCHITEKTUR.md`
- `doc/steuerbox/SICHERHEIT.md`
- `doc/steuerbox/LLM_AUSFUEHRUNG.md`
