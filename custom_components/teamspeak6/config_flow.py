"""Config flow for TeamSpeak 6."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import TeamSpeakAuthError, TeamSpeakError, TeamSpeakWebQuery
from .const import (
    CONF_REJOIN_GRACE,
    CONF_SERVER_ID,
    DEFAULT_PORT,
    DEFAULT_REJOIN_GRACE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SERVER_ID,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

_PASSWORD = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


def _user_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_API_KEY): _PASSWORD,
            vol.Required(
                CONF_SERVER_ID, default=defaults.get(CONF_SERVER_ID, DEFAULT_SERVER_ID)
            ): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Required(CONF_SSL, default=defaults.get(CONF_SSL, False)): bool,
            vol.Required(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, True)): bool,
        }
    )


async def _validate(hass: HomeAssistant, data: Mapping[str, Any]) -> dict[str, Any]:
    """Return serverinfo or raise a TeamSpeakError."""
    api = TeamSpeakWebQuery(
        async_get_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL]),
        host=data[CONF_HOST],
        port=data[CONF_PORT],
        api_key=data[CONF_API_KEY],
        server_id=data[CONF_SERVER_ID],
        use_ssl=data[CONF_SSL],
        verify_ssl=data[CONF_VERIFY_SSL],
    )
    await api.clientlist()  # this is what the key must be able to do
    return await api.serverinfo()  # optional, {} with a scope=read key


class TeamSpeakConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TeamSpeak 6."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await _validate(self.hass, user_input)
            except TeamSpeakAuthError:
                errors["base"] = "invalid_auth"
            except TeamSpeakError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                unique_id = info.get("virtualserver_unique_identifier") or (
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                    f"/{user_input[CONF_SERVER_ID]}"
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured(updates=user_input)
                return self.async_create_entry(
                    title=info.get("virtualserver_name")
                    or f"TeamSpeak 6 ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, CONF_API_KEY: user_input[CONF_API_KEY]}
            try:
                await _validate(self.hass, data)
            except TeamSpeakAuthError:
                errors["base"] = "invalid_auth"
            except TeamSpeakError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): _PASSWORD}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> TeamSpeakOptionsFlow:
        return TeamSpeakOptionsFlow()


class TeamSpeakOptionsFlow(OptionsFlow):
    """Polling interval and reconnect detection."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)),
                    vol.Required(
                        CONF_REJOIN_GRACE,
                        default=options.get(CONF_REJOIN_GRACE, DEFAULT_REJOIN_GRACE),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=3600)),
                }
            ),
        )
