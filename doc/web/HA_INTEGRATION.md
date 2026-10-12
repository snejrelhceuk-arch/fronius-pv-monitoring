# Home Assistant Integration (REST, read-first)

Stand: 2026-10-12

## 1) Discovery im pv-system

Der Web-API-Export bietet folgende Pfade:

- `/api/ha` — Endpoint-Index
- `/api/ha/flow` — kompakte Fluss-/Verbrauchswerte
- `/api/ha/wattpilot` — kompakter Wattpilot-Status
- `/api/ha/automation` — SOC- und Intent-Status (inkl. Nachmittags-Ladewunsch)
- `/api/ha/device` — Geräte-Metadaten (Identifier/Name/Role)
- `/api/ha/entities` — Entitätskatalog + JSON-Keys + Schreibaktion-Hinweis

## 2) Minimales HA-Beispiel (read)

Beispiel für `configuration.yaml`:

```yaml
rest:
  - resource: "http://PV-SYSTEM-IP:8000/api/ha/automation"
    scan_interval: 10
    sensor:
      - name: "PV System Automation"
        unique_id: "pv_system_automation"
        value_template: "{{ 'ok' }}"
        json_attributes:
          - battery_soc_pct
          - soc_min_pct
          - soc_max_pct
          - soc_mode
          - afternoon_charge_active
          - afternoon_charge_target_soc_pct
          - afternoon_charge_remaining_s
          - afternoon_charge_until_h

  - resource: "http://PV-SYSTEM-IP:8000/api/ha/flow"
    scan_interval: 15
    sensor:
      - name: "PV System Flow"
        unique_id: "pv_system_flow"
        value_template: "{{ value_json.pv_total_w | default(0) }}"
        unit_of_measurement: "W"
        device_class: power
        state_class: measurement
        json_attributes:
          - grid_power_w
          - battery_soc_pct
          - household_w
          - wattpilot_w
          - heatpump_w
          - heizpatrone_w
```

## 3) Schreibvorgaenge

Die MQTT-Bridge ist fuer Telemetrie read-only — **eine Ausnahme:** der MQTT-Button
`afternoon_charge_request` schreibt via loopback-POST zur Steuerbox (Schicht E).
Wattpilot-Schaltvorgaenge (Start/Stop/Modus/Strom) bleiben in der bestehenden
HA-Wattpilot-Integration.

## 4) Sichtbarkeit als "Gerät" in HA

Mit reinen REST-Sensoren erzeugt HA oft kein vollwertiges Device-Registry-Objekt.
`/api/ha/device` und `/api/ha/entities` liefern aber alle Metadaten, um Entitäten konsistent zu gruppieren.

Wenn ein echtes, automatisch angelegtes Gerät benötigt wird, ist MQTT Discovery der robustere nächste Ausbauschritt.

## 5) MQTT-Bridge innerhalb der Projektstruktur

Die Bridge ist bewusst als separater Adapter umgesetzt:

- Bridge-Code: `steuerbox/ha_mqtt_bridge.py`
- Service-Unit: `config/systemd/pv-ha-bridge.service`
- Read-Quelle: Web-API `/api/ha/*` (Schicht B)
- Write-Ziel (nur `afternoon_charge_request`): Steuerbox `/api/ops/intent` via loopback

Die Automation-Engine (Schicht C) bleibt unveraendert und HA-unabhaengig.

## 6) Aktivierung

Nicht-sensible Keys in `.infra.local`, das **Passwort in `.secrets`** (gitignored):

```bash
# .infra.local
PV_HA_BRIDGE_ENABLED=1
PV_HA_BRIDGE_MQTT_HOST=192.0.2.180   # HA-Host mit Mosquitto-Broker
PV_HA_BRIDGE_MQTT_PORT=1883
PV_HA_BRIDGE_MQTT_USERNAME=ha_pv
```

```bash
# .secrets
PV_HA_BRIDGE_MQTT_PASSWORD=<broker-passwort fuer user ha_pv>
```

**Broker-Auth ist Pflicht:** Der Mosquitto-Broker läuft mit `allow_anonymous false`
und einem `password_file`. Benutzername **und** Passwort müssen exakt einem Eintrag
in diesem `password_file` entsprechen (angelegt via `mosquitto_passwd`). `USERNAME`
und `PASSWORD` sind daher **nicht optional** — ohne gültiges Paar lehnt der Broker
die Verbindung ab.

### Troubleshooting MQTT-Auth
- Journal zeigt dauerhaft `MQTT connect failed rc=5` → der Broker weist die
  Anmeldung ab (**NOT AUTHORIZED**). Ursache ist praktisch immer ein fehlender
  oder abweichender Benutzer im `password_file` des Brokers (z. B. nach
  Neuaufsetzen/Umzug des HA-Hosts: der pv-system-User wurde nicht neu angelegt).
- Prüfen (auf dem HA-Host, Mosquitto als Docker-Container `mosquitto`):
  ```bash
  docker exec mosquitto cut -d: -f1 /mosquitto/config/passwordfile   # existierende User
  ```
- User (neu) anlegen/Passwort setzen — **ohne** `-c` (das `-c`-Flag würde die
  Datei neu erzeugen und alle anderen User löschen!) — danach Broker neu laden:
  ```bash
  docker exec mosquitto mosquitto_passwd -b /mosquitto/config/passwordfile ha_pv '<passwort>'
  docker exec mosquitto sh -c 'kill -HUP 1'   # Reload ohne HA/zigbee zu stören
  ```
- Dann `PV_HA_BRIDGE_MQTT_PASSWORD` in `.secrets` auf denselben Wert setzen und
  `sudo systemctl restart pv-ha-bridge.service`. Erfolg = Journal zeigt
  `MQTT connected` + `Subscribed to afternoon_charge_request command topic`.

Dann systemd-Unit installieren/starten:

```bash
sudo install -m 0644 config/systemd/pv-ha-bridge.service /etc/systemd/system/pv-ha-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now pv-ha-bridge.service
```

Pruefen:

```bash
systemctl status pv-ha-bridge.service
journalctl -u pv-ha-bridge -n 100 --no-pager
```
