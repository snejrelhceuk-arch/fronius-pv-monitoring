#!/usr/bin/env python3
"""Home-Assistant MQTT Bridge fuer pv-system.

Adapter zwischen:
- B (Read): /api/ha/* auf Port 8000

Die Bridge ist strikt read-only: Sie erzeugt MQTT Discovery-Entitaeten
und publiziert Zustandswerte, ohne Schreibzugriffe auf Steuerbox/Aktoren.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests
from paho.mqtt import client as mqtt

import config

LOG = logging.getLogger('steuerbox.ha_mqtt_bridge')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


def _is_on(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return False


class HaMqttBridge:
    def __init__(self) -> None:
        self.web_base = config.HA_BRIDGE_WEB_BASE.rstrip('/')
        self.poll_s = max(5, int(config.HA_BRIDGE_POLL_S))
        self.http_timeout_s = max(2, int(config.HA_BRIDGE_HTTP_TIMEOUT_S))

        self.discovery_prefix = config.HA_BRIDGE_DISCOVERY_PREFIX.strip('/')
        self.state_prefix = config.HA_BRIDGE_STATE_PREFIX.strip('/')
        self.node_id = config.HA_BRIDGE_NODE_ID.strip()

        self.availability_topic = f'{self.state_prefix}/{self.node_id}/bridge/availability'

        self._session = requests.Session()
        self._client = mqtt.Client(client_id=f'pv-bridge-{self.node_id}', clean_session=True)
        self._client.enable_logger(LOG)
        self._client.on_connect = self._on_connect

        if config.HA_BRIDGE_MQTT_USERNAME:
            self._client.username_pw_set(
                config.HA_BRIDGE_MQTT_USERNAME,
                config.HA_BRIDGE_MQTT_PASSWORD or None,
            )

        self._client.will_set(self.availability_topic, payload='offline', qos=1, retain=True)

        self._discovery_published = False
        self._legacy_cleanup_done = False

    def _mqtt_connect(self) -> None:
        while True:
            try:
                self._client.connect(
                    host=config.HA_BRIDGE_MQTT_HOST,
                    port=int(config.HA_BRIDGE_MQTT_PORT),
                    keepalive=int(config.HA_BRIDGE_MQTT_KEEPALIVE_S),
                )
                return
            except Exception as exc:
                LOG.warning('MQTT connect failed (%s), retry in 10s', exc)
                time.sleep(10)

    def _json_get(self, path: str) -> dict[str, Any]:
        url = f'{self.web_base}{path}'
        resp = self._session.get(url, timeout=self.http_timeout_s)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data
        raise RuntimeError(f'Unexpected payload type for {path}')

    def _publish(self, topic: str, value: Any, retain: bool = True) -> None:
        if value is None:
            return
        payload = value
        if not isinstance(value, str):
            payload = str(value)
        self._client.publish(topic, payload=payload, qos=1, retain=retain)

    def _publish_json(self, topic: str, data: dict[str, Any], retain: bool = True) -> None:
        self._client.publish(topic, payload=json.dumps(data, ensure_ascii=False), qos=1, retain=retain)

    @staticmethod
    def _wattpilot_status(car_state: Any) -> str:
        state = int(car_state or 0)
        if state == 2:
            return 'Charging'
        if state == 3:
            return 'Wait Car'
        if state == 4:
            return 'Complete'
        return 'Idle'

    @staticmethod
    def _wattpilot_mode_name(lmo: Any) -> str:
        mode = int(lmo or 0)
        return {
            3: 'default',
            4: 'eco',
            5: 'next_trip',
        }.get(mode, 'unknown')

    def _device_info(self, device_payload: dict[str, Any]) -> dict[str, Any]:
        device = (device_payload or {}).get('device')
        if not isinstance(device, dict):
            return {
                'identifiers': [self.node_id],
                'name': 'PV-System Erlau',
                'manufacturer': 'PV-System',
                'model': 'GEN24 Orchestrator',
            }

        identifier = str(device.get('identifier') or self.node_id)
        return {
            'identifiers': [identifier],
            'name': str(device.get('name') or 'PV-System Erlau'),
            'manufacturer': str(device.get('manufacturer') or 'PV-System'),
            'model': str(device.get('model') or 'GEN24 Orchestrator'),
            'sw_version': str(device.get('sw_version') or 'unknown'),
        }

    def _entity_state_topic(self, key: str) -> str:
        return f'{self.state_prefix}/{self.node_id}/state/{key}'

    def _discovery_topic(self, component: str, object_id: str) -> str:
        return f'{self.discovery_prefix}/{component}/{self.node_id}/{object_id}/config'

    def _clear_legacy_command_discovery(self) -> None:
        """Entfernt fruehere Command-Entitaeten per retained-empty config payload."""
        legacy = [
            ('button', 'afternoon_charge_request'),
            ('button', 'wattpilot_start'),
            ('button', 'wattpilot_stop'),
            ('number', 'wattpilot_amp_set'),
            ('select', 'wattpilot_mode_set'),
        ]
        for component, object_id in legacy:
            topic = self._discovery_topic(component, object_id)
            self._client.publish(topic, payload='', qos=1, retain=True)
        self._legacy_cleanup_done = True
        LOG.info('Legacy command discovery topics cleared (%s)', len(legacy))

    def _publish_discovery(self, device_payload: dict[str, Any]) -> None:
        device = self._device_info(device_payload)

        entities = [
            {
                'component': 'sensor',
                'object_id': 'pv_total_w',
                'name': 'PV Totalleistung',
                'state_topic': self._entity_state_topic('pv_total_w'),
                'unit_of_measurement': 'W',
                'device_class': 'power',
                'state_class': 'measurement',
            },
            {
                'component': 'sensor',
                'object_id': 'grid_power_w',
                'name': 'Netzleistung',
                'state_topic': self._entity_state_topic('grid_power_w'),
                'unit_of_measurement': 'W',
                'device_class': 'power',
                'state_class': 'measurement',
            },
            {
                'component': 'sensor',
                'object_id': 'battery_soc_pct',
                'name': 'Batterie SOC',
                'state_topic': self._entity_state_topic('battery_soc_pct'),
                'unit_of_measurement': '%',
                'device_class': 'battery',
                'state_class': 'measurement',
            },
            {
                'component': 'sensor',
                'object_id': 'wattpilot_power_w',
                'name': 'Wattpilot Leistung',
                'state_topic': self._entity_state_topic('wattpilot_power_w'),
                'unit_of_measurement': 'W',
                'device_class': 'power',
                'state_class': 'measurement',
            },
            {
                'component': 'sensor',
                'object_id': 'wattpilot_status',
                'name': 'Wattpilot Status',
                'state_topic': self._entity_state_topic('wattpilot_status'),
            },
            {
                'component': 'binary_sensor',
                'object_id': 'wattpilot_charging',
                'name': 'Wattpilot Laedt',
                'state_topic': self._entity_state_topic('wattpilot_charging'),
                'payload_on': 'ON',
                'payload_off': 'OFF',
            },
            {
                'component': 'binary_sensor',
                'object_id': 'wattpilot_online',
                'name': 'Wattpilot Online',
                'state_topic': self._entity_state_topic('wattpilot_online'),
                'payload_on': 'ON',
                'payload_off': 'OFF',
            },
            {
                'component': 'sensor',
                'object_id': 'wattpilot_age_s',
                'name': 'Wattpilot Alter',
                'state_topic': self._entity_state_topic('wattpilot_age_s'),
                'unit_of_measurement': 's',
                'state_class': 'measurement',
            },
            {
                'component': 'sensor',
                'object_id': 'wattpilot_energy_session_kwh',
                'name': 'Wattpilot Session Energie',
                'state_topic': self._entity_state_topic('wattpilot_energy_session_kwh'),
                'unit_of_measurement': 'kWh',
                'device_class': 'energy',
                'state_class': 'total_increasing',
            },
            {
                'component': 'sensor',
                'object_id': 'wattpilot_gesamt_energie',
                'name': 'Wattpilot Gesamt Energie',
                'state_topic': self._entity_state_topic('wattpilot_gesamt_energie'),
                'unit_of_measurement': 'kWh',
                'device_class': 'energy',
                'state_class': 'total_increasing',
            },
            {
                'component': 'sensor',
                'object_id': 'wattpilot_amp',
                'name': 'Wattpilot Max Strom',
                'state_topic': self._entity_state_topic('wattpilot_amp'),
                'unit_of_measurement': 'A',
                'state_class': 'measurement',
            },
            {
                'component': 'sensor',
                'object_id': 'wattpilot_trx',
                'name': 'Wattpilot RFID Chip',
                'state_topic': self._entity_state_topic('wattpilot_trx'),
            },
            {
                'component': 'sensor',
                'object_id': 'wattpilot_lmo',
                'name': 'Wattpilot Lademodus Raw',
                'state_topic': self._entity_state_topic('wattpilot_lmo'),
                'state_class': 'measurement',
            },
            {
                'component': 'sensor',
                'object_id': 'wattpilot_mode',
                'name': 'Wattpilot Lademodus',
                'state_topic': self._entity_state_topic('wattpilot_mode'),
            },
            {
                'component': 'sensor',
                'object_id': 'wattpilot_frc',
                'name': 'Wattpilot FRC',
                'state_topic': self._entity_state_topic('wattpilot_frc'),
                'state_class': 'measurement',
            },
            {
                'component': 'sensor',
                'object_id': 'soc_max_pct',
                'name': 'SOC Max',
                'state_topic': self._entity_state_topic('soc_max_pct'),
                'unit_of_measurement': '%',
                'state_class': 'measurement',
            },
            {
                'component': 'binary_sensor',
                'object_id': 'afternoon_charge_active',
                'name': 'Nachmittag Ladewunsch Aktiv',
                'state_topic': self._entity_state_topic('afternoon_charge_active'),
                'payload_on': 'ON',
                'payload_off': 'OFF',
            },
            {
                'component': 'sensor',
                'object_id': 'afternoon_charge_remaining_s',
                'name': 'Nachmittag Ladewunsch Restzeit',
                'state_topic': self._entity_state_topic('afternoon_charge_remaining_s'),
                'unit_of_measurement': 's',
                'state_class': 'measurement',
            },
        ]

        for ent in entities:
            topic = self._discovery_topic(ent['component'], ent['object_id'])
            payload = {
                'name': ent['name'],
                'unique_id': f'{self.node_id}_{ent["object_id"]}',
                'availability_topic': self.availability_topic,
                'payload_available': 'online',
                'payload_not_available': 'offline',
                'device': device,
            }
            payload.update({k: v for k, v in ent.items() if k not in {'component', 'object_id', 'name'}})
            self._publish_json(topic, payload, retain=True)

        self._discovery_published = True
        LOG.info('MQTT discovery published (%s entities)', len(entities))

    def _publish_states(
        self,
        flow: dict[str, Any],
        wattpilot: dict[str, Any],
        automation: dict[str, Any],
    ) -> None:
        self._publish(self._entity_state_topic('pv_total_w'), flow.get('pv_total_w'))
        self._publish(self._entity_state_topic('grid_power_w'), flow.get('grid_power_w'))
        self._publish(self._entity_state_topic('battery_soc_pct'), flow.get('battery_soc_pct'))
        self._publish(self._entity_state_topic('wattpilot_power_w'), wattpilot.get('power_w'))
        self._publish(self._entity_state_topic('wattpilot_status'), self._wattpilot_status(wattpilot.get('car_state')))
        self._publish(self._entity_state_topic('wattpilot_online'), 'ON' if _is_on(wattpilot.get('online')) else 'OFF')
        self._publish(self._entity_state_topic('wattpilot_age_s'), wattpilot.get('age_s'))
        self._publish(self._entity_state_topic('wattpilot_energy_session_kwh'), wattpilot.get('energy_session_kwh'))
        self._publish(self._entity_state_topic('wattpilot_gesamt_energie'), wattpilot.get('energy_total_kwh'))
        self._publish(self._entity_state_topic('wattpilot_amp'), wattpilot.get('amp'))
        self._publish(self._entity_state_topic('wattpilot_trx'), wattpilot.get('trx'))
        self._publish(self._entity_state_topic('wattpilot_lmo'), wattpilot.get('lmo'))
        self._publish(self._entity_state_topic('wattpilot_mode'), self._wattpilot_mode_name(wattpilot.get('lmo')))
        self._publish(self._entity_state_topic('wattpilot_frc'), wattpilot.get('frc'))

        charging = 'ON' if _is_on(wattpilot.get('charging')) else 'OFF'
        self._publish(self._entity_state_topic('wattpilot_charging'), charging)

        self._publish(self._entity_state_topic('soc_max_pct'), automation.get('soc_max_pct'))

        afternoon_active = 'ON' if _is_on(automation.get('afternoon_charge_active')) else 'OFF'
        self._publish(self._entity_state_topic('afternoon_charge_active'), afternoon_active)
        self._publish(
            self._entity_state_topic('afternoon_charge_remaining_s'),
            automation.get('afternoon_charge_remaining_s', 0),
        )

        # Raw JSON Topics fuer tieferes HA-Template-Debugging
        self._publish_json(self._entity_state_topic('flow_json'), flow, retain=True)
        self._publish_json(self._entity_state_topic('wattpilot_json'), wattpilot, retain=True)
        self._publish_json(self._entity_state_topic('automation_json'), automation, retain=True)

    def _on_connect(self, client: mqtt.Client, _userdata: Any, flags: dict, rc: int) -> None:
        if rc != 0:
            LOG.error('MQTT connect failed rc=%s', rc)
            return
        LOG.info('MQTT connected: flags=%s', flags)
        self._publish(self.availability_topic, 'online', retain=True)

    def run(self) -> None:
        LOG.info('HA MQTT bridge start (read-only): web=%s mqtt=%s:%s poll=%ss',
                 self.web_base,
                 config.HA_BRIDGE_MQTT_HOST, config.HA_BRIDGE_MQTT_PORT,
                 self.poll_s)

        self._mqtt_connect()
        self._client.loop_start()

        while True:
            try:
                device_payload = self._json_get('/api/ha/device')
                if not self._legacy_cleanup_done:
                    self._clear_legacy_command_discovery()
                if not self._discovery_published:
                    self._publish_discovery(device_payload)

                flow = self._json_get('/api/ha/flow')
                wattpilot = self._json_get('/api/ha/wattpilot')
                automation = self._json_get('/api/ha/automation')

                self._publish_states(flow, wattpilot, automation)
                self._publish(self.availability_topic, 'online', retain=True)
            except Exception as exc:
                LOG.warning('bridge cycle failed: %s', exc)
                self._publish(self.availability_topic, 'offline', retain=True)

            time.sleep(self.poll_s)


def main() -> int:
    if not config.HA_BRIDGE_ENABLED:
        LOG.warning('HA bridge disabled (PV_HA_BRIDGE_ENABLED=0). Exiting.')
        return 0

    bridge = HaMqttBridge()
    bridge.run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
