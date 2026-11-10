"""Constants for the TeamSpeak 6 integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "teamspeak6"

CONF_SERVER_ID: Final = "server_id"
CONF_REJOIN_GRACE: Final = "rejoin_grace"

DEFAULT_PORT: Final = 10080
DEFAULT_SERVER_ID: Final = 1
DEFAULT_SCAN_INTERVAL: Final = 15  # seconds
MIN_SCAN_INTERVAL: Final = 5
DEFAULT_REJOIN_GRACE: Final = 60  # seconds

# The channel list rarely changes; refresh it at most this often,
# or immediately when a client shows up in an unknown channel.
CHANNEL_REFRESH_INTERVAL: Final = 300  # seconds

EVENT_CLIENT_JOINED: Final = f"{DOMAIN}_client_joined"
EVENT_CLIENT_LEFT: Final = f"{DOMAIN}_client_left"
