"""Minimal async client for the TeamSpeak 6 WebQuery (HTTP query)."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

REQUEST_TIMEOUT = 10

# WebQuery status codes that mean the key is wrong or expired.
_AUTH_STATUS_CODES = {5122, 5124}
# "command not in api key scope": key is valid, command is not allowed.
_OUT_OF_SCOPE = 5120


class TeamSpeakError(Exception):
    """Base error."""


class TeamSpeakConnectionError(TeamSpeakError):
    """Server not reachable or returned garbage."""


class TeamSpeakAuthError(TeamSpeakError):
    """API key rejected."""


class TeamSpeakScopeError(TeamSpeakError):
    """API key valid, but the command is outside its scope."""


class TeamSpeakWebQuery:
    """Talks to http(s)://host:port/<sid>/<command>."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        api_key: str,
        server_id: int = 1,
        use_ssl: bool = False,
        verify_ssl: bool = True,
    ) -> None:
        scheme = "https" if use_ssl else "http"
        self._base = f"{scheme}://{host.strip()}:{port}/{server_id}"
        self._session = session
        self._headers = {"x-api-key": api_key.strip()}
        self._ssl = bool(verify_ssl)

    async def _command(self, command: str) -> list[dict[str, Any]]:
        url = f"{self._base}/{command}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(
                    url, headers=self._headers, ssl=self._ssl
                ) as resp:
                    http_status = resp.status
                    try:
                        data = await resp.json(content_type=None)
                    except ValueError:
                        data = None
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TeamSpeakConnectionError(str(err) or type(err).__name__) from err

        status = (data.get("status") if isinstance(data, dict) else None) or {}
        code = int(status.get("code", 0) or 0)
        message = status.get("extra_message") or status.get("message") or ""
        if code == _OUT_OF_SCOPE:
            # Valid key, but this command needs a wider scope (e.g. serverinfo
            # with a scope=read key answers HTTP 401 / 5120).
            raise TeamSpeakScopeError(message)
        if http_status in (401, 403) or code in _AUTH_STATUS_CODES:
            raise TeamSpeakAuthError(message or f"HTTP {http_status}")
        if not isinstance(data, dict):
            raise TeamSpeakConnectionError(f"Unexpected response (HTTP {http_status})")
        if code == 1281:  # "database empty result set"
            return []
        if code != 0:
            raise TeamSpeakConnectionError(f"{code}: {status.get('message', '')}")

        body = data.get("body") or []
        if isinstance(body, dict):
            body = [body]
        return body

    async def serverinfo(self) -> dict[str, Any]:
        """Return virtualserver_* fields, or {} if the key may not read them.

        A scope=read key on TeamSpeak 6 is not allowed to run serverinfo,
        so this information is optional everywhere.
        """
        try:
            body = await self._command("serverinfo")
        except TeamSpeakScopeError:
            return {}
        return body[0] if body else {}

    async def clientlist(self) -> list[dict[str, Any]]:
        """Return all connected clients (voice and query)."""
        return await self._command("clientlist")

    async def channellist(self) -> list[dict[str, Any]]:
        """Return all channels."""
        return await self._command("channellist")
