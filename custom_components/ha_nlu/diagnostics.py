"""Privacy-preserving, user-triggered Home Assistant diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AGENT_COOLDOWN_SECONDS,
    CONF_AGENT_DELIVERY_CHANNELS,
    CONF_AGENT_ENABLED,
    CONF_AGENT_MEDIA_PLAYERS,
    CONF_AGENT_NOTIFY_TARGETS,
    CONF_AGENT_TTS_ENTITY,
    CONF_ADMIN_ONLY_ENTITIES,
    CONF_ALLOW_NON_ADMIN_AUTOMATIONS,
    CONF_ALLOW_NON_ADMIN_CRITICAL,
    CONF_CONFIRMATION_LEVEL,
    CONF_CONTEXT_TTL_SECONDS,
    CONF_CONTROL_USER_IDS,
    CONF_CUSTOM_ALIASES,
    CONF_MAX_ACTION_TARGETS,
    CONF_READ_ONLY_ENTITIES,
    CONF_SELECTED_ENTITIES,
    DOMAIN,
)
from .customization import parse_custom_aliases


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return configuration facts without utterances, states or entity IDs.

    Home Assistant only calls this function when the user explicitly
    downloads diagnostics. HomeIntent does not persist conversation text.
    """

    selected = entry.options.get(CONF_SELECTED_ENTITIES)
    read_only = entry.options.get(CONF_READ_ONLY_ENTITIES, [])
    admin_only = entry.options.get(CONF_ADMIN_ONLY_ENTITIES, [])
    control_users = entry.options.get(CONF_CONTROL_USER_IDS, [])
    try:
        alias_count = sum(
            len(aliases)
            for aliases in parse_custom_aliases(
                entry.options.get(CONF_CUSTOM_ALIASES)
            ).values()
        )
    except ValueError:
        alias_count = "invalid"
    return {
        "domain": DOMAIN,
        "entry_version": entry.version,
        "selection_mode": "explicit" if selected is not None else "assist_exposure",
        "selected_entity_count": len(selected) if selected is not None else None,
        "read_only_entity_count": len(read_only) if isinstance(read_only, list) else 0,
        "admin_only_entity_count": (
            len(admin_only) if isinstance(admin_only, list) else 0
        ),
        "control_user_count": (
            len(control_users) if isinstance(control_users, list) else 0
        ),
        "custom_alias_count": alias_count,
        "confirmation_level": entry.options.get(CONF_CONFIRMATION_LEVEL, "high"),
        "max_action_targets": entry.options.get(CONF_MAX_ACTION_TARGETS, 50),
        "allow_non_admin_critical": entry.options.get(
            CONF_ALLOW_NON_ADMIN_CRITICAL, True
        ),
        "allow_non_admin_automations": entry.options.get(
            CONF_ALLOW_NON_ADMIN_AUTOMATIONS, True
        ),
        "context_ttl_seconds": entry.options.get(CONF_CONTEXT_TTL_SECONDS, 30),
        "proactive_agent_enabled": entry.options.get(CONF_AGENT_ENABLED, True),
        "agent_delivery_channels": entry.options.get(
            CONF_AGENT_DELIVERY_CHANNELS, ["push"]
        ),
        "agent_notify_target_count": len(
            entry.options.get(CONF_AGENT_NOTIFY_TARGETS, [])
        ),
        "agent_tts_configured": bool(entry.options.get(CONF_AGENT_TTS_ENTITY)),
        "agent_media_player_count": len(
            entry.options.get(CONF_AGENT_MEDIA_PLAYERS, [])
        ),
        "agent_cooldown_seconds": entry.options.get(
            CONF_AGENT_COOLDOWN_SECONDS, 1800
        ),
        "conversation_text_stored": False,
        "world_model_persisted": False,
    }
