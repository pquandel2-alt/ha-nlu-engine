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
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_ALLOW_NON_ADMIN_AUTOMATIONS,
    CONF_ALLOW_NON_ADMIN_CRITICAL,
    CONF_CONFIRMATION_LEVEL,
    CONF_CONTEXT_TTL_SECONDS,
    CONF_CONTROL_USER_IDS,
    CONF_CUSTOM_ALIASES,
    CONF_ADMIN_ONLY_ENTITIES,
    CONF_MAX_ACTION_TARGETS,
    CONF_READ_ONLY_ENTITIES,
    CONF_SELECTED_ENTITIES,
    DOMAIN,
    SELECTABLE_DOMAINS,
)
from .hass_entities import default_exposed_entities
from .customization import parse_custom_aliases

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
            try:
                parse_custom_aliases(user_input.get(CONF_CUSTOM_ALIASES))
            except ValueError:
                return self.async_show_form(
                    step_id="init",
                    data_schema=await self._async_schema(user_input),
                    errors={CONF_CUSTOM_ALIASES: "invalid_alias_rules"},
                )
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(CONF_SELECTED_ENTITIES)
        if current is None:
            current = default_exposed_entities(self.hass)

        return self.async_show_form(
            step_id="init",
            data_schema=await self._async_schema(
                {**self.config_entry.options, CONF_SELECTED_ENTITIES: current}
            ),
        )

    async def _async_schema(self, defaults: dict[str, Any]) -> vol.Schema:
        selected_user_ids = defaults.get(CONF_CONTROL_USER_IDS, [])
        users_by_id: dict[str, str] = {}
        auth = getattr(self.hass, "auth", None)
        get_users = getattr(auth, "async_get_users", None)
        if get_users is not None:
            try:
                for user in await get_users():
                    user_id = str(user.id)
                    users_by_id[user_id] = str(user.name or user_id)
            except Exception:  # The options form must remain available.
                _LOGGER.debug("Could not enumerate Home Assistant users", exc_info=True)
        if isinstance(selected_user_ids, list):
            for user_id in selected_user_ids:
                users_by_id.setdefault(str(user_id), str(user_id))
        user_options: list[SelectOptionDict] = [
            {"value": user_id, "label": label}
            for user_id, label in sorted(
                users_by_id.items(), key=lambda item: item[1].casefold()
            )
        ]
        return vol.Schema(
                {
                    vol.Optional(
                        CONF_SELECTED_ENTITIES, default=defaults.get(CONF_SELECTED_ENTITIES, [])
                    ): EntitySelector(
                        EntitySelectorConfig(domain=SELECTABLE_DOMAINS, multiple=True)
                    ),
                    vol.Optional(
                        CONF_READ_ONLY_ENTITIES,
                        default=defaults.get(CONF_READ_ONLY_ENTITIES, []),
                    ): EntitySelector(
                        EntitySelectorConfig(domain=SELECTABLE_DOMAINS, multiple=True)
                    ),
                    vol.Optional(
                        CONF_ADMIN_ONLY_ENTITIES,
                        default=defaults.get(CONF_ADMIN_ONLY_ENTITIES, []),
                    ): EntitySelector(
                        EntitySelectorConfig(domain=SELECTABLE_DOMAINS, multiple=True)
                    ),
                    vol.Optional(
                        CONF_CONTROL_USER_IDS,
                        default=defaults.get(CONF_CONTROL_USER_IDS, []),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=user_options,
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_CUSTOM_ALIASES,
                        default=defaults.get(CONF_CUSTOM_ALIASES, ""),
                    ): TextSelector(TextSelectorConfig(multiline=True)),
                    vol.Optional(
                        CONF_CONFIRMATION_LEVEL,
                        default=defaults.get(CONF_CONFIRMATION_LEVEL, "high"),
                    ): vol.In(("medium", "high", "critical")),
                    vol.Optional(
                        CONF_MAX_ACTION_TARGETS,
                        default=defaults.get(CONF_MAX_ACTION_TARGETS, 50),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
                    vol.Optional(
                        CONF_ALLOW_NON_ADMIN_CRITICAL,
                        default=defaults.get(CONF_ALLOW_NON_ADMIN_CRITICAL, True),
                    ): bool,
                    vol.Optional(
                        CONF_ALLOW_NON_ADMIN_AUTOMATIONS,
                        default=defaults.get(CONF_ALLOW_NON_ADMIN_AUTOMATIONS, True),
                    ): bool,
                    vol.Optional(
                        CONF_CONTEXT_TTL_SECONDS,
                        default=defaults.get(CONF_CONTEXT_TTL_SECONDS, 30),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
                }
        )
