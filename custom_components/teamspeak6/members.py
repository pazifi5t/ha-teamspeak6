"""Known members and when they were last seen.

Pure Python like tracker.py, so it can be unit tested without Home Assistant.

Two sources are combined:

* ``clientdblist`` (optional, needs a key that may run it): every identity the
  server knows, with ``client_lastconnected`` = start of the *last login*.
* Own observation of ``clientlist``: the time of the last poll in which a
  member was online, i.e. (roughly) the *end* of the last session.

All timestamps are Unix seconds (float).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tracker import Client

# A real TeamSpeak identity is a base64 encoded hash: 28 characters on
# TeamSpeak 3 (SHA-1), 44 on TeamSpeak 6 (SHA-256). ServerQuery logins show
# up with unique identifiers like "serveradmin" or "ServerQuery" and are skipped.
_IDENTITY_RE = re.compile(r"^[A-Za-z0-9+/]{20,}={0,2}$")

# While a member stays online, persist the "last seen" time at least this often,
# so a crash of Home Assistant loses at most this much precision.
HEARTBEAT = 300  # seconds

SOURCE_ONLINE = "online"
SOURCE_OBSERVED = "observed"
SOURCE_LAST_LOGIN = "last_login"


def is_real_identity(uid: str | None) -> bool:
    """Return False for ServerQuery / bot identities."""
    if uid is None:  # field not delivered at all: do not filter
        return True
    return bool(_IDENTITY_RE.match(uid))


def _as_time(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _valid_dbid(dbid: Any) -> str | None:
    text = str(dbid or "").strip()
    return text if text and text != "0" else None


@dataclass
class Member:
    """A client database entry."""

    dbid: str
    nickname: str
    last_connected: float | None = None  # from clientdblist: start of last login
    last_seen: float | None = None  # own observation: last poll while online
    online_since: float | None = None  # runtime only, not persisted


@dataclass(frozen=True)
class MemberStatus:
    """What the entities show for one member."""

    dbid: str
    nickname: str
    online: bool
    timestamp: float | None  # online: session start, offline: last seen
    source: str  # SOURCE_*
    last_login: float | None


class MemberRegistry:
    """Known members, the currently online ones and the selected one."""

    def __init__(self) -> None:
        self.members: dict[str, Member] = {}
        self.online: set[str] = set()
        self.selected: str | None = None
        self._baseline = True
        self._last_flush: float = 0.0

    # --- persistence -----------------------------------------------------

    def load(self, data: Mapping[str, Any] | None) -> None:
        """Restore from the Store payload (unknown keys are ignored)."""
        if not data:
            return
        for dbid, raw in (data.get("members") or {}).items():
            if not (dbid := _valid_dbid(dbid)) or not isinstance(raw, Mapping):
                continue
            self.members[dbid] = Member(
                dbid=dbid,
                nickname=str(raw.get("nickname") or f"#{dbid}"),
                last_connected=_as_time(raw.get("last_connected")),
                last_seen=_as_time(raw.get("last_seen")),
            )
        selected = _valid_dbid(data.get("selected"))
        self.selected = selected if selected in self.members else None

    def as_dict(self) -> dict[str, Any]:
        """Payload for the Store."""
        return {
            "selected": self.selected,
            "members": {
                m.dbid: {
                    "nickname": m.nickname,
                    "last_connected": m.last_connected,
                    "last_seen": m.last_seen,
                }
                for m in self.members.values()
            },
        }

    # --- updates ---------------------------------------------------------

    def merge_dblist(self, rows: Iterable[Mapping[str, Any]], complete: bool) -> bool:
        """Merge a clientdblist body. Returns True if something changed.

        With ``complete`` (the whole list was read), members that are no
        longer in the server database and not online are dropped.
        """
        changed = False
        seen: set[str] = set()
        for row in rows:
            if not is_real_identity(row.get("client_unique_identifier")):
                continue
            if str(row.get("client_totalconnections", "1")) == "0":
                continue  # never connected (e.g. "ServerQuery Guest")
            if not (dbid := _valid_dbid(row.get("cldbid"))):
                continue
            seen.add(dbid)
            nickname = str(row.get("client_nickname") or "").strip()
            last_connected = _as_time(row.get("client_lastconnected"))
            member = self.members.get(dbid)
            if member is None:
                self.members[dbid] = Member(
                    dbid=dbid, nickname=nickname or f"#{dbid}", last_connected=last_connected
                )
                changed = True
                continue
            if nickname and nickname != member.nickname:
                member.nickname = nickname
                changed = True
            if last_connected and last_connected != member.last_connected:
                member.last_connected = last_connected
                changed = True

        if complete:
            for dbid in list(self.members):
                if dbid not in seen and dbid not in self.online:
                    del self.members[dbid]
                    changed = True
            if self.selected is not None and self.selected not in self.members:
                self.selected = None
        return changed

    def observe(self, clients: Mapping[str, Client], now: float) -> bool:
        """Record who is online right now. Returns True if it should be saved."""
        online_now: dict[str, Client] = {}
        for client in clients.values():
            if dbid := _valid_dbid(client.database_id):
                online_now.setdefault(dbid, client)

        dirty = False
        for dbid, client in online_now.items():
            member = self.members.get(dbid)
            if member is None:
                member = self.members[dbid] = Member(
                    dbid=dbid, nickname=client.nickname or f"#{dbid}"
                )
                dirty = True
            elif client.nickname and client.nickname != member.nickname:
                member.nickname = client.nickname
                dirty = True

            if dbid not in self.online:
                # Just joined, or already online when we started watching:
                # then the login time from clientdblist is the session start.
                login = member.last_connected
                if self._baseline and login and login <= now and login >= (member.last_seen or 0):
                    member.online_since = login
                else:
                    member.online_since = now
                dirty = True
            member.last_seen = now

        for dbid in self.online - online_now.keys():
            if member := self.members.get(dbid):
                member.online_since = None  # last_seen stays at the last poll
            dirty = True

        self.online = set(online_now)
        self._baseline = False

        if self.online and now - self._last_flush >= HEARTBEAT:
            dirty = True
        if dirty:
            self._last_flush = now
        return dirty

    # --- selection & display ---------------------------------------------

    def _display_names(self) -> dict[str, str]:
        """{dbid: unique display name}. Duplicate nicknames get their dbid."""
        counts: dict[str, int] = {}
        for member in self.members.values():
            key = member.nickname.casefold()
            counts[key] = counts.get(key, 0) + 1
        return {
            m.dbid: m.nickname if counts[m.nickname.casefold()] == 1 else f"{m.nickname} (#{m.dbid})"
            for m in self.members.values()
        }

    def options(self) -> list[str]:
        """All members as unique, sorted names for a select entity."""
        return sorted(self._display_names().values(), key=str.casefold)

    def display_name(self, dbid: str | None) -> str | None:
        if dbid is None:
            return None
        return self._display_names().get(dbid)

    def select(self, option: str) -> bool:
        """Select a member by display name. Returns False if unknown."""
        for dbid, name in self._display_names().items():
            if name == option:
                self.selected = dbid
                return True
        return False

    def status(self, dbid: str | None) -> MemberStatus | None:
        """Online state and last-seen time of one member."""
        if dbid is None or (member := self.members.get(dbid)) is None:
            return None
        if dbid in self.online:
            return MemberStatus(
                dbid, member.nickname, True, member.online_since, SOURCE_ONLINE, member.last_connected
            )
        seen, login = member.last_seen, member.last_connected
        if seen is not None and (login is None or seen >= login):
            timestamp, source = seen, SOURCE_OBSERVED
        elif login is not None:
            # Logged in while we were not watching; the session ended
            # at some unknown point after this.
            timestamp, source = login, SOURCE_LAST_LOGIN
        else:
            timestamp, source = None, SOURCE_OBSERVED
        return MemberStatus(dbid, member.nickname, False, timestamp, source, login)
