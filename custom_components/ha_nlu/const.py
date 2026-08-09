"""Shared constants for the ha_nlu custom component."""

from __future__ import annotations

DOMAIN = "ha_nlu"

CONF_SELECTED_ENTITIES = "selected_entities"

# Domains the v1 intent set (light_switch.yaml, cover.yaml) can act on.
# Mirrors service_call.py's IntentSpec.allowed_domains.
SELECTABLE_DOMAINS = ("light", "switch", "fan", "cover")

NOT_UNDERSTOOD_TEXT = "Das habe ich nicht verstanden."
