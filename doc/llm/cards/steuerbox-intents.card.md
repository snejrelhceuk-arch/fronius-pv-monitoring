---
title: Steuerbox Intents (Validierung, Overrides, Respekt)
domain: steuerbox
role: E
applyTo: "steuerbox/**"
tags: [intent, overrides, respekt, hard-guards, audit]
status: stable
last_review: 2026-05-03
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

### Action-Hinweis (neu)
- `afternoon_charge_request`: Tages-Intent für Nachmittags-Ladewunsch. Standardmäßig wird `respekt_s` serverseitig bis Sunset desselben Tages abgeleitet (Fallback 17:00), damit ein HA-Einmal-Trigger ohne zweite Aktion auskommt.

## Invarianten
- Steuerbox macht keine direkten Hardware-Schreibzugriffe (kein Modbus/FritzDECT/Wattpilot aus E).
- Die optionale HA-MQTT-Bridge liest nur `/api/ha/*` (B) und publiziert read-only MQTT-Telemetrie; kein direkter Aktor- oder Ops-Schreibpfad.
- IP-Allowlist wird vor der Intent-Verarbeitung geprueft.
- Auf Failover sind nicht-GET Ops-Endpunkte blockiert (`403`, read-only Verhalten).
- Pro Aktion bleibt genau ein Live-Override (`open/active`), aeltere werden auf `released` gesetzt.
- `respekt_s` muss im konfigurierten Bereich liegen (`STEUERBOX_MIN_RESPEKT_S`..`STEUERBOX_MAX_RESPEKT_S`).
- Für `afternoon_charge_request` gilt ein eigener Maximalwert (`STEUERBOX_AFTERNOON_MAX_RESPEKT_S`), damit Tages-Holds bis Sunset möglich sind.

## No-Gos
- Keine Imports aus `automation/engine/aktoren/*` in Steuerbox-Modulen.
- Kein Bypass von `validate_action()`.
- Keine neuen Actions ohne Mapping in `OperatorOverrideProcessor._map_override_to_actions`.
- Kein direkter Zugriff auf Fronius/FritzDECT/Wattpilot aus Schicht E.

## Häufige Aufgaben
- Neue Aktion einfuehren -> `config.py:STEUERBOX_ALLOWED_ACTIONS` + `steuerbox/validators.py:validate_action` + `automation/engine/operator_overrides.py:_map_override_to_actions`.
- UI-Meta fuer neue Buttons -> `steuerbox/steuerbox_api.py:api_control_meta` erweitern.
- Override-Lebenszyklus debuggen -> `GET /api/ops/status` und `GET /api/ops/audit` vergleichen.
- HA-Ladewunsch anbinden -> `action='afternoon_charge_request'` mit optionalen Parametern (`target_soc_pct`, `pause_hp_until_target`, Startfenster 12-15h).
- HA-Wattpilot anbinden -> MQTT-Topics der Bridge read-only für Telemetrie nutzen; Schaltvorgänge bleiben in HA auf der bestehenden Wattpilot-Integration.
- Für Energy-Dashboards liefert die Bridge Wattpilot-Gesamtenergie und Session-Energie als dedizierte MQTT-Sensoren.

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
