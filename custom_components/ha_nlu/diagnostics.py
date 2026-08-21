"""Privacy-preserving, user-triggered Home Assistant diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_SELECTED_ENTITIES, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return configuration facts without utterances, states or entity IDs.

    Home Assistant only calls this function when the user explicitly
    downloads diagnostics. HomeIntent does not persist conversation text.
    """

    selected = entry.options.get(CONF_SELECTED_ENTITIES)
    return {
        "domain": DOMAIN,
        "entry_version": entry.version,
        "selection_mode": "explicit" if selected is not None else "assist_exposure",
        "selected_entity_count": len(selected) if selected is not None else None,
        "conversation_text_stored": False,
        "world_model_persisted": False,
    }
