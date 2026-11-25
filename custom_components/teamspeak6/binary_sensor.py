"""Binary sensor platform for TeamSpeak 6: is the selected member online?"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TeamSpeakConfigEntry, TeamSpeakCoordinator
from .entity import TeamSpeakMemberEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeamSpeakConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the member online sensor."""
    async_add_entities([TeamSpeakMemberOnlineSensor(entry.runtime_data)])


class TeamSpeakMemberOnlineSensor(TeamSpeakMemberEntity, BinarySensorEntity):
    """On while the member chosen in the select is connected."""

    _attr_translation_key = "member_online"

    def __init__(self, coordinator: TeamSpeakCoordinator) -> None:
        super().__init__(coordinator, "member_online")

    @property
    def is_on(self) -> bool | None:
        status = self.member_status
        return status.online if status else None

    @property
    def icon(self) -> str:
        return "mdi:account-voice" if self.is_on else "mdi:account-off-outline"
