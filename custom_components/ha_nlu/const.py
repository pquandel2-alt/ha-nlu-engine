"""Shared constants for the ha_nlu custom component."""

from __future__ import annotations

DOMAIN = "ha_nlu"

CONF_SELECTED_ENTITIES = "selected_entities"

# Domains the intent set can act on or (for "sensor"/"binary_sensor") read
# state from. Mirrors service_call.py's IntentSpec/QueryIntentSpec.allowed_domains.
# "binary_sensor" (V4.2, Semantic Query Engine) is exposed as a full domain,
# not filtered to window/door device classes - it becomes selectable in
# config_flow.py's entity picker like any other domain, same as "sensor".
SELECTABLE_DOMAINS = ("light", "switch", "fan", "cover", "sensor", "binary_sensor")

NOT_UNDERSTOOD_TEXT = "Das habe ich nicht verstanden."
