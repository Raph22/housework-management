"""Config flow for the Housework integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    ASSIGNMENT_STRATEGIES,
    DEFAULT_ASSIGNMENT_STRATEGY,
    DEFAULT_PRIORITY,
    DOMAIN,
)


class HouseworkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Housework."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        # Single instance only
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="Housework",
                data={},
            )

        return self.async_show_form(step_id="user")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return HouseworkOptionsFlow(config_entry)


class HouseworkOptionsFlow(OptionsFlow):
    """Handle options for Housework."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "default_assignment_strategy",
                        default=self._config_entry.options.get(
                            "default_assignment_strategy",
                            DEFAULT_ASSIGNMENT_STRATEGY,
                        ),
                    ): vol.In(ASSIGNMENT_STRATEGIES),
                    vol.Optional(
                        "default_priority",
                        default=self._config_entry.options.get(
                            "default_priority",
                            DEFAULT_PRIORITY,
                        ),
                    ): vol.In({1: "P1 - Urgent", 2: "P2 - High", 3: "P3 - Normal", 4: "P4 - Low"}),
                }
            ),
        )
