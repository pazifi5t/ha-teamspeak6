"""Sensor platform for TeamSpeak 6."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import TeamSpeakConfigEntry, TeamSpeakCoordinator
from .entity import TeamSpeakEntity, TeamSpeakMemberEntity

PARALLEL_UPDATES = 0


def _dt(timestamp: float | None) -> datetime | None:
    return dt_util.utc_from_timestamp(timestamp) if timestamp else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeamSpeakConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [TeamSpeakOnlineSensor(coordinator), TeamSpeakMemberLastSeenSensor(coordinator)]
    )


class TeamSpeakOnlineSensor(TeamSpeakEntity, SensorEntity):
    """Number of connected voice clients, with names grouped by channel."""

    _attr_translation_key = "online"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "users"
    _attr_icon = "mdi:headset"

    def __init__(self, coordinator: TeamSpeakCoordinator) -> None:
        super().__init__(coordinator, "online")

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


class TeamSpeakMemberLastSeenSensor(TeamSpeakMemberEntity, SensorEntity):
    """When the selected member was last seen (or since when they are online)."""

    _attr_translation_key = "member_last_seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:account-clock"

    def __init__(self, coordinator: TeamSpeakCoordinator) -> None:
        super().__init__(coordinator, "member_last_seen")

    @property
    def native_value(self) -> datetime | None:
        status = self.member_status
        return _dt(status.timestamp) if status else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self.member_status
        if status is None:
            return {"member": None, "online": None, "source": None}
        return {
            "member": status.nickname,
            "online": status.online,
            # online: value is the start of the current session;
            # observed: last poll in which the member was online;
            # last_login: only the login time is known (clientdblist).
            "source": status.source,
            "last_login": _dt(status.last_login),
            "member_source": self.coordinator.member_source,
        }
