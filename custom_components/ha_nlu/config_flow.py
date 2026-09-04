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
    AGENT_CHANNEL_PUSH,
    AGENT_CHANNEL_TTS,
    CONF_AGENT_COOLDOWN_SECONDS,
    CONF_AGENT_DELIVERY_CHANNELS,
    CONF_AGENT_ENABLED,
    CONF_AGENT_MEDIA_PLAYERS,
    CONF_AGENT_NOTIFY_TARGETS,
    CONF_AGENT_TTS_ENTITY,
    CONF_AGENT_AUTO_ENABLED,
    CONF_AGENT_AUTO_ENTITY_IDS,
    CONF_AGENT_EVENT_CATEGORIES,
    CONF_AGENT_QUIET_END,
    CONF_AGENT_QUIET_START,
    CONF_ANOMALY_THRESHOLD_PERCENT,
    CONF_ALLOW_NON_ADMIN_AUTOMATIONS,
    CONF_ALLOW_NON_ADMIN_CRITICAL,
    CONF_CONFIRMATION_LEVEL,
    CONF_CONTEXT_TTL_SECONDS,
    CONF_BANTER_LEVEL,
    CONF_CONTROL_USER_IDS,
    CONF_DOCUMENTS_DIRECTORY,
    CONF_DOCUMENTS_ENABLED,
    CONF_HOUSE_RELATIONS,
    CONF_FRIGATE_ENABLED,
    CONF_FRIGATE_MQTT_TOPIC,
    CONF_HA_SOURCES_ENABLED,
    CONF_CUSTOM_ALIASES,
    CONF_ADMIN_ONLY_ENTITIES,
    CONF_MAX_ACTION_TARGETS,
    CONF_MEMORY_ENABLED,
    CONF_MEMORY_RETENTION_DAYS,
    CONF_PERSONA_STYLE,
    CONF_READ_ONLY_ENTITIES,
    CONF_SELECTED_ENTITIES,
    CONF_ROUTINE_DETECTION_ENABLED,
    CONF_ROUTINE_MIN_OBSERVATIONS,
    DOMAIN,
    SELECTABLE_DOMAINS,
)
from .hass_entities import default_exposed_entities
from .customization import parse_custom_aliases
from .house_graph import parse_relation_specs
from .agent_config_validation import (
    parse_event_categories,
    validate_documents_directory,
    validate_mqtt_topic,
    validate_quiet_time,
)

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
            options={
                CONF_MEMORY_ENABLED: False,
                CONF_ROUTINE_DETECTION_ENABLED: False,
                CONF_AGENT_AUTO_ENABLED: False,
                CONF_AGENT_AUTO_ENTITY_IDS: [],
                CONF_DOCUMENTS_ENABLED: False,
            },
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
            try:
                parse_relation_specs(user_input.get(CONF_HOUSE_RELATIONS))
            except ValueError:
                return self.async_show_form(
                    step_id="init",
                    data_schema=await self._async_schema(user_input),
                    errors={CONF_HOUSE_RELATIONS: "invalid_house_relations"},
                )
            try:
                validate_quiet_time(user_input.get(CONF_AGENT_QUIET_START, "22:00"))
                validate_quiet_time(user_input.get(CONF_AGENT_QUIET_END, "07:00"))
                parse_event_categories(user_input.get(CONF_AGENT_EVENT_CATEGORIES, ""))
                validate_documents_directory(
                    user_input.get(CONF_DOCUMENTS_DIRECTORY, "homeintent_documents")
                )
                validate_mqtt_topic(
                    user_input.get(CONF_FRIGATE_MQTT_TOPIC, "frigate/events")
                )
            except ValueError:
                return self.async_show_form(
                    step_id="init",
                    data_schema=await self._async_schema(user_input),
                    errors={"base": "invalid_agent_options"},
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
                        default=defaults.get(CONF_ALLOW_NON_ADMIN_CRITICAL, False),
                    ): bool,
                    vol.Optional(
                        CONF_ALLOW_NON_ADMIN_AUTOMATIONS,
                        default=defaults.get(CONF_ALLOW_NON_ADMIN_AUTOMATIONS, True),
                    ): bool,
                    vol.Optional(
                        CONF_CONTEXT_TTL_SECONDS,
                        default=defaults.get(CONF_CONTEXT_TTL_SECONDS, 30),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
                    vol.Optional(
                        CONF_AGENT_ENABLED,
                        default=defaults.get(CONF_AGENT_ENABLED, True),
                    ): bool,
                    vol.Optional(
                        CONF_AGENT_DELIVERY_CHANNELS,
                        default=defaults.get(
                            CONF_AGENT_DELIVERY_CHANNELS, [AGENT_CHANNEL_PUSH]
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": AGENT_CHANNEL_PUSH, "label": "Push"},
                                {"value": AGENT_CHANNEL_TTS, "label": "TTS"},
                            ],
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Optional(
                        CONF_AGENT_NOTIFY_TARGETS,
                        default=defaults.get(CONF_AGENT_NOTIFY_TARGETS, []),
                    ): EntitySelector(
                        EntitySelectorConfig(domain="notify", multiple=True)
                    ),
                    vol.Optional(
                        CONF_AGENT_TTS_ENTITY,
                        default=defaults.get(CONF_AGENT_TTS_ENTITY),
                    ): EntitySelector(EntitySelectorConfig(domain="tts")),
                    vol.Optional(
                        CONF_AGENT_MEDIA_PLAYERS,
                        default=defaults.get(CONF_AGENT_MEDIA_PLAYERS, []),
                    ): EntitySelector(
                        EntitySelectorConfig(domain="media_player", multiple=True)
                    ),
                    vol.Optional(
                        CONF_AGENT_COOLDOWN_SECONDS,
                        default=defaults.get(CONF_AGENT_COOLDOWN_SECONDS, 1800),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=86400)),
                    vol.Optional(
                        CONF_MEMORY_ENABLED,
                        default=defaults.get(CONF_MEMORY_ENABLED, False),
                    ): bool,
                    vol.Optional(
                        CONF_MEMORY_RETENTION_DAYS,
                        default=defaults.get(CONF_MEMORY_RETENTION_DAYS, 90),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3650)),
                    vol.Optional(
                        CONF_PERSONA_STYLE,
                        default=defaults.get(CONF_PERSONA_STYLE, "neutral"),
                    ): vol.In(("neutral", "precise", "jarvis")),
                    vol.Optional(
                        CONF_BANTER_LEVEL,
                        default=defaults.get(CONF_BANTER_LEVEL, 0),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=3)),
                    vol.Optional(
                        CONF_AGENT_QUIET_START,
                        default=defaults.get(CONF_AGENT_QUIET_START, "22:00"),
                    ): TextSelector(TextSelectorConfig()),
                    vol.Optional(
                        CONF_AGENT_QUIET_END,
                        default=defaults.get(CONF_AGENT_QUIET_END, "07:00"),
                    ): TextSelector(TextSelectorConfig()),
                    vol.Optional(
                        CONF_AGENT_EVENT_CATEGORIES,
                        default=defaults.get(CONF_AGENT_EVENT_CATEGORIES, ""),
                    ): TextSelector(TextSelectorConfig()),
                    vol.Optional(
                        CONF_ROUTINE_DETECTION_ENABLED,
                        default=defaults.get(CONF_ROUTINE_DETECTION_ENABLED, False),
                    ): bool,
                    vol.Optional(
                        CONF_ROUTINE_MIN_OBSERVATIONS,
                        default=defaults.get(CONF_ROUTINE_MIN_OBSERVATIONS, 10),
                    ): vol.All(vol.Coerce(int), vol.Range(min=3, max=10000)),
                    vol.Optional(
                        CONF_ANOMALY_THRESHOLD_PERCENT,
                        default=defaults.get(CONF_ANOMALY_THRESHOLD_PERCENT, 5),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
                    vol.Optional(
                        CONF_AGENT_AUTO_ENABLED,
                        default=defaults.get(CONF_AGENT_AUTO_ENABLED, False),
                    ): bool,
                    vol.Optional(
                        CONF_AGENT_AUTO_ENTITY_IDS,
                        default=defaults.get(CONF_AGENT_AUTO_ENTITY_IDS, []),
                    ): EntitySelector(
                        EntitySelectorConfig(domain=SELECTABLE_DOMAINS, multiple=True)
                    ),
                    vol.Optional(
                        CONF_DOCUMENTS_ENABLED,
                        default=defaults.get(CONF_DOCUMENTS_ENABLED, False),
                    ): bool,
                    vol.Optional(
                        CONF_DOCUMENTS_DIRECTORY,
                        default=defaults.get(CONF_DOCUMENTS_DIRECTORY, "homeintent_documents"),
                    ): TextSelector(TextSelectorConfig()),
                    vol.Optional(
                        CONF_HOUSE_RELATIONS,
                        default=defaults.get(CONF_HOUSE_RELATIONS, ""),
                    ): TextSelector(TextSelectorConfig(multiline=True)),
                    vol.Optional(
                        CONF_FRIGATE_ENABLED,
                        default=defaults.get(CONF_FRIGATE_ENABLED, False),
                    ): bool,
                    vol.Optional(
                        CONF_FRIGATE_MQTT_TOPIC,
                        default=defaults.get(CONF_FRIGATE_MQTT_TOPIC, "frigate/events"),
                    ): TextSelector(TextSelectorConfig()),
                    vol.Optional(
                        CONF_HA_SOURCES_ENABLED,
                        default=defaults.get(CONF_HA_SOURCES_ENABLED, False),
                    ): bool,
                }
        )
