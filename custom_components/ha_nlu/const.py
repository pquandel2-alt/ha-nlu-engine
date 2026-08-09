"""Shared constants for the ha_nlu custom component."""

from __future__ import annotations

DOMAIN = "ha_nlu"

CONF_SELECTED_ENTITIES = "selected_entities"

# Domains the intent set can act on or (for "sensor") read state from.
# Mirrors service_call.py's IntentSpec/QueryIntentSpec.allowed_domains.
SELECTABLE_DOMAINS = ("light", "switch", "fan", "cover", "sensor")

NOT_UNDERSTOOD_TEXT = "Das habe ich nicht verstanden."
