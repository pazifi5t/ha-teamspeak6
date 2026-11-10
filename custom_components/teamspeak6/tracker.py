"""Pure helpers for TeamSpeak 6 client tracking.

Nothing in here imports Home Assistant, so the logic can be unit tested
without a Home Assistant installation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

# Spacer channels: [spacer], [cspacer], [lspacer], [rspacer], [*spacer],
# optionally followed by a number or other suffix, e.g. "[cspacer0]".
_SPACER_RE = re.compile(r"^\s*\[[lrc*]?spacer[^\]]*\]\s*", re.IGNORECASE)

# client_type "0" is a real voice client, "1" is a ServerQuery connection.
_VOICE_CLIENT = "0"


def clean_channel_name(name: str | None) -> str:
    """Strip a TeamSpeak spacer prefix from a channel name."""
    if not name:
        return ""
    return _SPACER_RE.sub("", name).strip()


@dataclass(frozen=True)
class Client:
    """A connected voice client."""

    clid: str
    database_id: str
    nickname: str
    cid: str

    @property
    def identity(self) -> str:
        """A key that survives reconnects (the clid does not)."""
        if self.database_id and self.database_id != "0":
            return f"db:{self.database_id}"
        return f"nick:{self.nickname}"


def parse_clients(body: list[dict[str, Any]] | None) -> dict[str, Client]:
    """Turn a WebQuery clientlist body into voice clients keyed by clid."""
    clients: dict[str, Client] = {}
    for raw in body or []:
        if str(raw.get("client_type", "")) != _VOICE_CLIENT:
            continue
        clid = str(raw.get("clid", ""))
        if not clid:
            continue
        clients[clid] = Client(
            clid=clid,
            database_id=str(raw.get("client_database_id", "")),
            nickname=str(raw.get("client_nickname", "")),
            cid=str(raw.get("cid", "")),
        )
    return clients


def parse_channels(body: list[dict[str, Any]] | None) -> dict[str, str]:
    """Turn a WebQuery channellist body into {cid: display name}, in server order."""
    channels: dict[str, str] = {}
    for raw in body or []:
        cid = str(raw.get("cid", ""))
        if cid:
            channels[cid] = clean_channel_name(raw.get("channel_name"))
    return channels


def group_by_channel(
    clients: dict[str, Client], channels: dict[str, str]
) -> list[dict[str, Any]]:
    """Return non-empty channels in server order, each with its users."""
    by_cid: dict[str, list[str]] = {}
    for client in clients.values():
        by_cid.setdefault(client.cid, []).append(client.nickname)

    groups: list[dict[str, Any]] = []
    for cid, name in channels.items():
        if cid in by_cid:
            groups.append(
                {"cid": cid, "name": name, "users": sorted(by_cid.pop(cid), key=str.casefold)}
            )
    # Clients in channels we do not know (yet) still get listed.
    for cid, users in by_cid.items():
        groups.append({"cid": cid, "name": f"#{cid}", "users": sorted(users, key=str.casefold)})
    return groups


@dataclass
class ClientEvent:
    """A join or leave detected between two polls."""

    kind: str  # "joined" or "left"
    client: Client
    rejoin: bool = False


@dataclass
class ClientTracker:
    """Diff consecutive client lists and detect quick reconnects."""

    rejoin_grace: float
    _known: dict[str, Client] | None = None
    _left_at: dict[str, float] = field(default_factory=dict)

    def reset(self) -> None:
        """Forget state, e.g. after the server was unreachable.

        The next update then only records a baseline and emits no events,
        so a restart of Home Assistant or of the server does not flood
        automations with "joined" events.
        """
        self._known = None

    def update(self, clients: dict[str, Client], now: float) -> list[ClientEvent]:
        """Record a new client list and return what changed."""
        if self._known is None:
            self._known = dict(clients)
            return []

        events: list[ClientEvent] = []
        online_identities = {c.identity for c in clients.values()}

        for clid, client in self._known.items():
            if clid not in clients:
                events.append(ClientEvent("left", client))
                if client.identity not in online_identities:
                    self._left_at[client.identity] = now

        previous_identities = {c.identity for c in self._known.values()}
        for clid, client in clients.items():
            if clid in self._known:
                continue
            left = self._left_at.pop(client.identity, None)
            # Same user was online in the last poll (reconnect between two
            # polls, or a second connection) or left only a moment ago.
            rejoin = client.identity in previous_identities or (
                left is not None and now - left <= self.rejoin_grace
            )
            events.append(ClientEvent("joined", client, rejoin=rejoin))

        # Drop stale leave timestamps.
        self._left_at = {
            k: t for k, t in self._left_at.items() if now - t <= self.rejoin_grace
        }
        self._known = dict(clients)
        return events
