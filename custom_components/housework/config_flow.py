"""Config flow for the Housework integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    ASSIGNMENT_STRATEGIES,
    DEFAULT_ASSIGNMENT_STRATEGY,
    DEFAULT_PRIORITY,
    DOMAIN,
    FREQUENCY_TYPES,
    SCHEDULING_MODES,
)


def _task_form_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the form schema for task creation/editing."""
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required("title", default=d.get("title", "")): TextSelector(),
            vol.Required(
                "frequency_type", default=d.get("frequency_type", "weekly")
            ): SelectSelector(
                SelectSelectorConfig(
                    options=FREQUENCY_TYPES,
                    translation_key="frequency_type",
                )
            ),
            vol.Optional(
                "frequency_value", default=d.get("frequency_value", 1)
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=365, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                "frequency_days_of_week",
                default=d.get("frequency_days_of_week", []),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=["0", "1", "2", "3", "4", "5", "6"],
                    multiple=True,
                    translation_key="day_of_week",
                )
            ),
            vol.Optional(
                "frequency_day_of_month",
                default=d.get("frequency_day_of_month"),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=31, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                "scheduling_mode", default=d.get("scheduling_mode", "rolling")
            ): SelectSelector(
                SelectSelectorConfig(
                    options=SCHEDULING_MODES,
                    translation_key="scheduling_mode",
                )
            ),
            vol.Optional(
                "priority", default=str(d.get("priority", DEFAULT_PRIORITY))
            ): SelectSelector(
                SelectSelectorConfig(
                    options=["1", "2", "3", "4"],
                    translation_key="priority",
                )
            ),
            vol.Optional(
                "assignees", default=d.get("assignees", [])
            ): EntitySelector(
                EntitySelectorConfig(domain="person", multiple=True)
            ),
            vol.Optional(
                "assignment_strategy",
                default=d.get("assignment_strategy", DEFAULT_ASSIGNMENT_STRATEGY),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=ASSIGNMENT_STRATEGIES,
                    translation_key="assignment_strategy",
                )
            ),
            vol.Optional(
                "description", default=d.get("description", "")
            ): TextSelector(
                TextSelectorConfig(multiline=True)
            ),
            vol.Optional(
                "icon", default=d.get("icon", "mdi:broom")
            ): IconSelector(),
        }
    )


def _clean_task_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Clean and normalize task form data for storage."""
    data = dict(user_input)
    if "priority" in data:
        data["priority"] = int(data["priority"])
    if "frequency_value" in data:
        data["frequency_value"] = int(data["frequency_value"])
    if "frequency_day_of_month" in data and data["frequency_day_of_month"] is not None:
        data["frequency_day_of_month"] = int(data["frequency_day_of_month"])
    if "frequency_days_of_week" in data:
        data["frequency_days_of_week"] = [
            int(d) for d in data["frequency_days_of_week"]
        ]
    return data


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

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentry types supported by this integration."""
        return {"task": TaskSubentryFlowHandler}


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


class TaskSubentryFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for adding/editing a housework task."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle adding a new task."""
        if user_input is not None:
            data = _clean_task_data(user_input)
            return self.async_create_entry(
                title=data["title"],
                data=data,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_task_form_schema(),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle editing an existing task."""
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            data = _clean_task_data(user_input)
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data=data,
                title=data.get("title", subentry.title),
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_task_form_schema(defaults=dict(subentry.data)),
        )
