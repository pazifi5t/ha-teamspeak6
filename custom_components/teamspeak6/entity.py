"""Base entity for TeamSpeak 6."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TeamSpeakCoordinator
from .members import MemberStatus


class TeamSpeakEntity(CoordinatorEntity[TeamSpeakCoordinator]):
    """Shares the service device of one TeamSpeak server."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TeamSpeakCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        info = coordinator.data.serverinfo if coordinator.data else {}
        base = entry.unique_id or entry.entry_id
        self._attr_unique_id = f"{base}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, base)},
            name=coordinator.server_name,
            manufacturer="TeamSpeak",
            model="TeamSpeak 6 Server",
            sw_version=info.get("virtualserver_version"),
            entry_type=DeviceEntryType.SERVICE,
        )


class TeamSpeakMemberEntity(TeamSpeakEntity):
    """An entity about the member chosen in the member select."""

    @property
    def member_status(self) -> MemberStatus | None:
        members = self.coordinator.members
        return members.status(members.selected)
