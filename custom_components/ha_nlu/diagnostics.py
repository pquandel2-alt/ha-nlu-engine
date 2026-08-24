"""Privacy-preserving, user-triggered Home Assistant diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ALLOW_NON_ADMIN_AUTOMATIONS,
    CONF_ALLOW_NON_ADMIN_CRITICAL,
    CONF_CONFIRMATION_LEVEL,
    CONF_CONTEXT_TTL_SECONDS,
    CONF_MAX_ACTION_TARGETS,
    CONF_READ_ONLY_ENTITIES,
    CONF_SELECTED_ENTITIES,
    DOMAIN,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return configuration facts without utterances, states or entity IDs.

    Home Assistant only calls this function when the user explicitly
    downloads diagnostics. HomeIntent does not persist conversation text.
    """

    selected = entry.options.get(CONF_SELECTED_ENTITIES)
    read_only = entry.options.get(CONF_READ_ONLY_ENTITIES, [])
    return {
        "domain": DOMAIN,
        "entry_version": entry.version,
        "selection_mode": "explicit" if selected is not None else "assist_exposure",
        "selected_entity_count": len(selected) if selected is not None else None,
        "read_only_entity_count": len(read_only) if isinstance(read_only, list) else 0,
        "confirmation_level": entry.options.get(CONF_CONFIRMATION_LEVEL, "high"),
        "max_action_targets": entry.options.get(CONF_MAX_ACTION_TARGETS, 50),
        "allow_non_admin_critical": entry.options.get(
            CONF_ALLOW_NON_ADMIN_CRITICAL, True
        ),
        "allow_non_admin_automations": entry.options.get(
            CONF_ALLOW_NON_ADMIN_AUTOMATIONS, True
        ),
        "context_ttl_seconds": entry.options.get(CONF_CONTEXT_TTL_SECONDS, 30),
        "conversation_text_stored": False,
        "world_model_persisted": False,
    }
