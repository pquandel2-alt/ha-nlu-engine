"""Config and options flow for ha_nlu.

No required input on setup - v1 has nothing to configure beyond which
entities it may act on, and that defaults to whatever is already exposed to
Assist. The options flow (pattern ported from xiaozhi_entity_mcp's
``CONF_SELECTED_ENTITIES`` multi-select) lets that default be overridden.
Single-instance only: one ha_nlu agent is enough to register with Assist.

Setup deliberately does *not* persist a ``default_exposed_entities()``
snapshot into ``options`` (bug found via live testing, 2026-08): a frozen
list captured once at entry-creation time silently excludes any entity
exposed to Assist *afterwards* - e.g. a whole domain such as
``binary_sensor`` that wasn't yet exposed at setup - with no error, just
quietly empty query results forever after, regardless of later exposure
changes. Leaving ``options`` empty keeps ``get_selected_entity_ids()``
(``hass_entities.py``) on its documented dynamic fallback
(``default_exposed_entities()`` computed fresh every turn) until a user
explicitly saves a selection via the options flow below - which is the
only case ``CONF_SELECTED_ENTITIES`` should ever "win" per that function's
own docstring.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import CONF_SELECTED_ENTITIES, DOMAIN, SELECTABLE_DOMAINS
from .hass_entities import default_exposed_entities

_LOGGER = logging.getLogger(__name__)

TITLE = "HA NLU Engine"


class HaNluConfigFlow(ConfigFlow, domain=DOMAIN):
    """Single-instance config flow; no fields required."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        self._async_abort_entries_match({})
        return self.async_create_entry(
            title=TITLE,
            data={},
            options={},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HaNluOptionsFlow()


class HaNluOptionsFlow(OptionsFlow):
    """Options flow: override which entities the agent may act on."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(CONF_SELECTED_ENTITIES)
        if current is None:
            current = default_exposed_entities(self.hass)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SELECTED_ENTITIES, default=current
                    ): EntitySelector(
                        EntitySelectorConfig(domain=SELECTABLE_DOMAINS, multiple=True)
                    )
                }
            ),
        )
