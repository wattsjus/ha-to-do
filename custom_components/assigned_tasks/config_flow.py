"""Config flow for Assigned Tasks."""

from __future__ import annotations

from homeassistant import config_entries

from .const import DOMAIN


class AssignedTasksConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Assigned Tasks."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(title="Assigned Tasks", data={})

        return self.async_show_form(
            step_id="user",
            data_schema=None,
        )
