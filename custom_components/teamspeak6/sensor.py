"""Sensor platform for TeamSpeak 6."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TeamSpeakConfigEntry, TeamSpeakCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeamSpeakConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_add_entities([TeamSpeakOnlineSensor(entry.runtime_data)])


class TeamSpeakOnlineSensor(CoordinatorEntity[TeamSpeakCoordinator], SensorEntity):
    """Number of connected voice clients, with names grouped by channel."""

    _attr_has_entity_name = True
    _attr_translation_key = "online"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "users"
    _attr_icon = "mdi:headset"

    def __init__(self, coordinator: TeamSpeakCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        info = coordinator.data.serverinfo if coordinator.data else {}
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
            name=coordinator.server_name,
            manufacturer="TeamSpeak",
            model="TeamSpeak 6 Server",
            sw_version=info.get("virtualserver_version"),
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.clients)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        attrs: dict[str, Any] = {
            "users": sorted((c.nickname for c in data.clients.values()), key=str.casefold),
            "channels": [{"name": g["name"], "users": g["users"]} for g in data.groups],
        }
        if max_clients := data.serverinfo.get("virtualserver_maxclients"):
            attrs["max_clients"] = int(max_clients)
        return attrs
