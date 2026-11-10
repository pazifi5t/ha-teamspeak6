"""Data update coordinator for TeamSpeak 6."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TeamSpeakAuthError, TeamSpeakError, TeamSpeakWebQuery
from .const import (
    CHANNEL_REFRESH_INTERVAL,
    CONF_REJOIN_GRACE,
    DEFAULT_REJOIN_GRACE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_CLIENT_JOINED,
    EVENT_CLIENT_LEFT,
)
from .tracker import Client, ClientTracker, group_by_channel, parse_channels, parse_clients

_LOGGER = logging.getLogger(__name__)

type TeamSpeakConfigEntry = ConfigEntry[TeamSpeakCoordinator]


@dataclass
class TeamSpeakData:
    """Snapshot handed to the entities."""

    clients: dict[str, Client]
    channels: dict[str, str]
    groups: list[dict[str, Any]]
    serverinfo: dict[str, Any]


class TeamSpeakCoordinator(DataUpdateCoordinator[TeamSpeakData]):
    """Polls clientlist often and channellist rarely."""

    config_entry: TeamSpeakConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: TeamSpeakConfigEntry,
        api: TeamSpeakWebQuery,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self.tracker = ClientTracker(
            rejoin_grace=entry.options.get(CONF_REJOIN_GRACE, DEFAULT_REJOIN_GRACE)
        )
        self._channels: dict[str, str] = {}
        self._channels_fetched = 0.0
        self._serverinfo: dict[str, Any] = {}

    async def _async_setup(self) -> None:
        """Fetch static server info once."""
        try:
            self._serverinfo = await self.api.serverinfo()
        except TeamSpeakAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TeamSpeakError as err:
            raise UpdateFailed(f"Cannot reach TeamSpeak server: {err}") from err

    async def _async_update_data(self) -> TeamSpeakData:
        now = time.monotonic()
        try:
            clients = parse_clients(await self.api.clientlist())
            unknown_channel = any(c.cid not in self._channels for c in clients.values())
            if unknown_channel or now - self._channels_fetched > CHANNEL_REFRESH_INTERVAL:
                self._channels = parse_channels(await self.api.channellist())
                self._channels_fetched = now
        except TeamSpeakAuthError as err:
            self.tracker.reset()
            raise ConfigEntryAuthFailed(str(err)) from err
        except TeamSpeakError as err:
            _LOGGER.debug("Poll failed, tracker reset: %s", err)
            # After an outage we only take a fresh baseline instead of
            # reporting everybody as "joined".
            self.tracker.reset()
            raise UpdateFailed(f"Cannot reach TeamSpeak server: {err}") from err

        _LOGGER.debug(
            "Poll: %d voice clients %s",
            len(clients),
            sorted(f"{c.clid}/{c.database_id}" for c in clients.values()),
        )
        for event in self.tracker.update(clients, now):
            _LOGGER.debug(
                "Event %s: clid=%s dbid=%s rejoin=%s",
                event.kind, event.client.clid, event.client.database_id, event.rejoin,
            )
            self.hass.bus.async_fire(
                EVENT_CLIENT_JOINED if event.kind == "joined" else EVENT_CLIENT_LEFT,
                {
                    "config_entry_id": self.config_entry.entry_id,
                    "server": self.server_name,
                    "nickname": event.client.nickname,
                    "client_database_id": event.client.database_id,
                    "channel": self._channels.get(event.client.cid, f"#{event.client.cid}"),
                    "rejoin": event.rejoin,
                },
            )

        return TeamSpeakData(
            clients=clients,
            channels=self._channels,
            groups=group_by_channel(clients, self._channels),
            serverinfo=self._serverinfo,
        )

    @property
    def server_name(self) -> str:
        """Virtual server name, falling back to the entry title."""
        return self._serverinfo.get("virtualserver_name") or self.config_entry.title
