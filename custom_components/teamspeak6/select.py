"""Select platform for TeamSpeak 6: pick a member."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import TeamSpeakConfigEntry, TeamSpeakCoordinator
from .entity import TeamSpeakEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeamSpeakConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the member select."""
    async_add_entities([TeamSpeakMemberSelect(entry.runtime_data)])


class TeamSpeakMemberSelect(TeamSpeakEntity, SelectEntity):
    """All known members; the choice drives the member sensors."""

    _attr_translation_key = "member"
    _attr_icon = "mdi:account-search"

    def __init__(self, coordinator: TeamSpeakCoordinator) -> None:
        super().__init__(coordinator, "member")

    @property
    def options(self) -> list[str]:
        return self.coordinator.members.options()

    @property
    def current_option(self) -> str | None:
        members = self.coordinator.members
        return members.display_name(members.selected)

    async def async_select_option(self, option: str) -> None:
        if not self.coordinator.members.select(option):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_member",
                translation_placeholders={"member": option},
            )
        self.coordinator.async_schedule_save()
        # Refresh the member sensors right away, without polling the server.
        self.coordinator.async_update_listeners()
