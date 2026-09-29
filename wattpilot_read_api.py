"""Read-only Wattpilot API facade for Collector/Web paths."""

from __future__ import annotations

from wattpilot_api import WattpilotClient


class WattpilotReadOnly:
    """Read-only wrapper around the Wattpilot WebSocket client."""

    def __init__(self, ip=None, timeout=None, password=None):
        self._client = WattpilotClient(ip=ip, timeout=timeout, password=password)

    def read_status(self):
        return self._client.read_status()

    def get_energy_total_wh(self):
        return self._client.get_energy_total_wh()

    def get_energy_total_kwh(self):
        return self._client.get_energy_total_kwh()

    def get_live_power_w(self):
        return self._client.get_live_power_w()

    def get_status_summary(self):
        return self._client.get_status_summary()