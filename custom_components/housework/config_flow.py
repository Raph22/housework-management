"""Config flow for the Housework integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

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
    ) -> ConfigFlowResult:
        """Handle the initial step."""
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
        return HouseworkOptionsFlow()


class HouseworkOptionsFlow(OptionsFlow):
    """Handle options for Housework."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            data = dict(user_input)
            if "default_priority" in data:
                data["default_priority"] = int(data["default_priority"])
            return self.async_create_entry(title="", data=data)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "default_assignment_strategy",
                        default=self.config_entry.options.get(
                            "default_assignment_strategy",
                            DEFAULT_ASSIGNMENT_STRATEGY,
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=ASSIGNMENT_STRATEGIES,
                            translation_key="assignment_strategy",
                        )
                    ),
                    vol.Optional(
                        "default_priority",
                        default=str(self.config_entry.options.get(
                            "default_priority",
                            DEFAULT_PRIORITY,
                        )),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=["1", "2", "3", "4"],
                            translation_key="priority",
                        )
                    ),
                }
            ),
        )
