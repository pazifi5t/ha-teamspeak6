"""Minimal async client for the TeamSpeak 6 WebQuery (HTTP query)."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

REQUEST_TIMEOUT = 10

# WebQuery status codes that mean the key is wrong or lacks permission.
_AUTH_STATUS_CODES = {5122, 5124, 2568}


class TeamSpeakError(Exception):
    """Base error."""


class TeamSpeakConnectionError(TeamSpeakError):
    """Server not reachable or returned garbage."""


class TeamSpeakAuthError(TeamSpeakError):
    """API key rejected."""


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
        self._base = f"{scheme}://{host}:{port}/{server_id}"
        self._session = session
        self._headers = {"x-api-key": api_key}
        self._ssl = bool(verify_ssl)

    async def _command(self, command: str) -> list[dict[str, Any]]:
        url = f"{self._base}/{command}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(
                    url, headers=self._headers, ssl=self._ssl
                ) as resp:
                    if resp.status in (401, 403):
                        raise TeamSpeakAuthError(f"HTTP {resp.status}")
                    data = await resp.json(content_type=None)
        except TeamSpeakError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise TeamSpeakConnectionError(str(err) or type(err).__name__) from err

        if not isinstance(data, dict):
            raise TeamSpeakConnectionError("Unexpected response")
        status = data.get("status") or {}
        code = int(status.get("code", 0) or 0)
        if code in _AUTH_STATUS_CODES:
            raise TeamSpeakAuthError(status.get("message", "invalid api key"))
        if code == 1281:  # "database empty result set"
            return []
        if code != 0:
            raise TeamSpeakConnectionError(f"{code}: {status.get('message', '')}")

        body = data.get("body") or []
        if isinstance(body, dict):
            body = [body]
        return body

    async def serverinfo(self) -> dict[str, Any]:
        """Return virtualserver_* fields of the selected virtual server."""
        body = await self._command("serverinfo")
        return body[0] if body else {}

    async def clientlist(self) -> list[dict[str, Any]]:
        """Return all connected clients (voice and query)."""
        return await self._command("clientlist")

    async def channellist(self) -> list[dict[str, Any]]:
        """Return all channels."""
        return await self._command("channellist")
