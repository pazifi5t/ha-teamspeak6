"""Diagnostics for TeamSpeak 6 (API key and nicknames redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.core import HomeAssistant

from .coordinator import TeamSpeakConfigEntry

TO_REDACT = {CONF_API_KEY, CONF_HOST, "virtualserver_unique_identifier", "virtualserver_ip"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TeamSpeakConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "serverinfo": async_redact_data(
            {k: v for k, v in data.serverinfo.items() if k.startswith("virtualserver_")},
            TO_REDACT,
        ),
        "clients_online": len(data.clients),
        "channels_known": len(data.channels),
        "last_update_success": coordinator.last_update_success,
    }
