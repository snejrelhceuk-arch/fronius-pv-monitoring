---
title: Steuerbox Intents (Validierung, Overrides, Respekt)
domain: steuerbox
role: E
applyTo: "steuerbox/**"
tags: [intent, overrides, respekt, hard-guards, audit]
status: stable
last_review: 2026-09-29
---

# Steuerbox Intents

## Zweck
Schicht E nimmt Operator-Intents entgegen, validiert sie und schreibt sie als Overrides in die RAM-DB. Die Ausfuehrung erfolgt ausschliesslich ueber Schicht C.

## Code-Anchor
- **API-Einstieg:** `steuerbox/steuerbox_api.py:api_intent`
- **Security-Gate:** `steuerbox/steuerbox_api.py:_security_gate`
- **Validatoren:** `steuerbox/validators.py:check_allowlist`, `validate_action`
- **Persistenz/Audit:** `steuerbox/intent_handler.py:handle_intent`, `get_status`, `get_audit`
- **HA-MQTT-Bridge (optional):** `steuerbox/ha_mqtt_bridge.py:HaMqttBridge`
- **Automation-Verarbeitung:** `automation/engine/operator_overrides.py:OperatorOverrideProcessor.process_pending`
- **Konfiguration:** `config.py` (`STEUERBOX_*`, `STEUERBOX_ALLOWED_ACTIONS`)

## Inputs / Outputs
- **Inputs:** `POST /api/ops/intent` mit `action`, `params`, optional `respekt_s`; Hostrolle aus `.role`; CIDR-Allowlist aus `config.py`.
- **Outputs:** DB-Schreibpfad in `/dev/shm/automation_obs.db` (`operator_overrides`, `steuerbox_audit`) und API-Response mit `override_id`, Restlaufzeit, normalisierten Parametern.

### Action-Hinweis
- `afternoon_charge_request`: Tages-Intent für Nachmittags-Ladewunsch. Standardmäßig wird `respekt_s` serverseitig bis Sunset desselben Tages abgeleitet (Fallback 17:00), damit ein HA-Einmal-Trigger ohne zweite Aktion auskommt. Parameter: `target_soc_pct` (default 100), `pause_hp_until_target` (default False seit 2026-05-22), `start_earliest_h` (default 12.0), `start_latest_h` (default 15.0). Ausführung: 2-Phasen-Sequenz — Phase 1 (ab `start_earliest_h`): `set_soc_max → target_soc_pct`, Phase 2 (nach 60s): `set_soc_mode → auto`. Vor `start_earliest_h` bleibt der Intent als policy hold inaktiv. Während der Hold-Zeit pausiert `RegelNachmittagSocMax` (Score=0), sodass keine Doppelausführung erfolgt.
- `wattpilot_amp`: Ladestrom-Stufen `8 | 16 | 24 A` (oder `neutral`). Validierung in `steuerbox/validators.py`, Cockpit-Button-Reihe in `steuerbox/static/js/cockpit.js`, Mapping `automation/engine/operator_overrides.py:_map_override_to_actions` → `wattpilot set_max_current` (Aktor klemmt hart auf 6–32 A).
- `hp_dauerbetrieb`: HP-Dauerbetrieb als **Ersatzheizung bei WP-Defekt** (Cockpit-Schalter `hp-dauerbetrieb` mit Sicherheits-Rückfrage). **Policy-Hold** (`_map_override_to_actions` → `[]`, keine direkte Aktoraktion): die HP-Regel liest den Intent (`automation/engine/operator_intents.py:read_active_hp_dauerbetrieb_intent`) und zwingt die HP EIN/hält sie — überstimmt weiche WP-Koordinations-Caps, Verbraucher-Konkurrenz, Ladewunsch, SOC-Floor und Netzbezug (läuft bewusst aus dem Netz). Einzige Software-AUS: `WW ≥ 78 °C` (mit Hysterese); ein laufender WP (`≥ drain_max_wp_w`) hebt den Zwang auf. Dauer serverseitig `STEUERBOX_HP_DAUERBETRIEB_DEFAULT_S` (8 h), Hard-Cap `STEUERBOX_HP_DAUERBETRIEB_MAX_S` (24 h, in `.infra.local` editierbar); Cockpit sendet **ohne** `respekt_s` (Default greift). `state=on` hält als Policy; `off`/`neutral` geben die Regel sofort frei. Physischer Restschutz: 35-A-Netzanschluss-Sicherung.

## Invarianten
- Steuerbox macht keine direkten Hardware-Schreibzugriffe (kein Modbus/FritzDECT/Wattpilot aus E).
- Vor direktem Aktor-Dispatch prueft Schicht C (`OperatorOverrideProcessor`) aktuelle `obs_state`-Hard-Guards und auditiert blockierte Overrides in `steuerbox_audit`.
- Die optionale HA-MQTT-Bridge liest `/api/ha/*` (B) für Telemetrie-Publish und schreibt **ausschliesslich** `afternoon_charge_request` via loopback-POST zu `/api/ops/intent` (Schicht E). Kein direkter Aktor-/Modbus-Schreibpfad.
- IP-Allowlist wird vor der Intent-Verarbeitung geprueft.
- Auf Failover sind nicht-GET Ops-Endpunkte blockiert (`403`, read-only Verhalten).
- Pro Aktion bleibt genau ein Live-Override (`open/active`), aeltere werden auf `released` gesetzt.
- `respekt_s` muss im konfigurierten Bereich liegen (`STEUERBOX_MIN_RESPEKT_S`..`STEUERBOX_MAX_RESPEKT_S`).
- Für `afternoon_charge_request` gilt ein eigener Maximalwert (`STEUERBOX_AFTERNOON_MAX_RESPEKT_S`), damit Tages-Holds bis Sunset möglich sind.
- Für `hp_dauerbetrieb` gilt ein eigener Default/Maximalwert (`STEUERBOX_HP_DAUERBETRIEB_DEFAULT_S`/`_MAX_S`); nur `state=on` ist Policy-Hold, `off`/`neutral` lösen sofort aus.
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
