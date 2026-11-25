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
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    TeamSpeakAuthError,
    TeamSpeakError,
    TeamSpeakPermissionError,
    TeamSpeakScopeError,
    TeamSpeakWebQuery,
)
from .const import (
    CHANNEL_REFRESH_INTERVAL,
    CONF_REJOIN_GRACE,
    DBLIST_REFRESH_INTERVAL,
    DEFAULT_REJOIN_GRACE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_CLIENT_JOINED,
    EVENT_CLIENT_LEFT,
    ISSUE_DBLIST_NOT_ALLOWED,
    MEMBER_SOURCE_DATABASE,
    MEMBER_SOURCE_OBSERVED,
    STORAGE_VERSION,
)
from .members import MemberRegistry
from .tracker import Client, ClientTracker, group_by_channel, parse_channels, parse_clients

_LOGGER = logging.getLogger(__name__)

type TeamSpeakConfigEntry = ConfigEntry[TeamSpeakCoordinator]


def members_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Store for known members (.storage/teamspeak6.<entry_id>.members)."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.members")


def issue_id(entry_id: str) -> str:
    """Repair issue id for a missing clientdblist permission."""
    return f"{ISSUE_DBLIST_NOT_ALLOWED}_{entry_id}"


@dataclass
class TeamSpeakData:
    """Snapshot handed to the entities."""

    clients: dict[str, Client]
    channels: dict[str, str]
    groups: list[dict[str, Any]]
    serverinfo: dict[str, Any]


class TeamSpeakCoordinator(DataUpdateCoordinator[TeamSpeakData]):
    """Polls clientlist often, channellist rarely and clientdblist hourly."""

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
        self.members = MemberRegistry()
        # None until clientdblist was tried once.
        self.member_source: str | None = None
        self._store = members_store(hass, entry.entry_id)
        self._channels: dict[str, str] = {}
        self._channels_fetched = 0.0
        self._dblist_fetched: float | None = None
        self._serverinfo: dict[str, Any] = {}

    async def _async_setup(self) -> None:
        """Fetch static server info and restore known members once."""
        self.members.load(await self._store.async_load())
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

        dirty = False
        if self._dblist_fetched is None or now - self._dblist_fetched > DBLIST_REFRESH_INTERVAL:
            self._dblist_fetched = now
            dirty = await self._async_refresh_dblist()
        dirty = self.members.observe(clients, dt_util.utcnow().timestamp()) or dirty
        if dirty:
            self.async_schedule_save()

        return TeamSpeakData(
            clients=clients,
            channels=self._channels,
            groups=group_by_channel(clients, self._channels),
            serverinfo=self._serverinfo,
        )

    async def _async_refresh_dblist(self) -> bool:
        """Read clientdblist; fall back to own observation if not allowed."""
        try:
            rows, complete = await self.api.clientdblist()
        except (TeamSpeakScopeError, TeamSpeakPermissionError, TeamSpeakAuthError) as err:
            # clientlist just worked with the same key, so an auth-looking
            # answer here means "not allowed", not "key invalid".
            if self.member_source != MEMBER_SOURCE_OBSERVED:
                _LOGGER.warning(
                    "The API key may not run clientdblist (%s). Members are only "
                    "learned while they are online, and 'last seen' only covers "
                    "sessions Home Assistant observed itself",
                    err,
                )
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id(self.config_entry.entry_id),
                    is_fixable=False,
                    is_persistent=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_DBLIST_NOT_ALLOWED,
                    translation_placeholders={"server": self.config_entry.title},
                    learn_more_url="https://github.com/pazifi5t/ha-teamspeak6#members-and-last-seen",
                )
            self.member_source = MEMBER_SOURCE_OBSERVED
            return False
        except TeamSpeakError as err:
            # Temporary problem: keep what we have, try again next interval.
            _LOGGER.debug("clientdblist failed, keeping known members: %s", err)
            return False

        if self.member_source != MEMBER_SOURCE_DATABASE:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id(self.config_entry.entry_id))
        self.member_source = MEMBER_SOURCE_DATABASE
        _LOGGER.debug("clientdblist: %d rows, complete=%s", len(rows), complete)
        return self.members.merge_dblist(rows, complete)

    def async_schedule_save(self) -> None:
        """Persist the members a few seconds from now."""
        self._store.async_delay_save(self.members.as_dict, 10)

    async def async_save_now(self, *_: Any) -> None:
        """Persist the members immediately (shutdown / unload)."""
        await self._store.async_save(self.members.as_dict())

    @property
    def server_name(self) -> str:
        """Virtual server name, falling back to the entry title."""
        return self._serverinfo.get("virtualserver_name") or self.config_entry.title
