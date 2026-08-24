"""Shared constants for the ha_nlu custom component."""

from __future__ import annotations

DOMAIN = "ha_nlu"

CONF_SELECTED_ENTITIES = "selected_entities"
CONF_READ_ONLY_ENTITIES = "read_only_entities"
CONF_CONFIRMATION_LEVEL = "confirmation_level"
CONF_MAX_ACTION_TARGETS = "max_action_targets"
CONF_ALLOW_NON_ADMIN_CRITICAL = "allow_non_admin_critical"
CONF_ALLOW_NON_ADMIN_AUTOMATIONS = "allow_non_admin_automations"
CONF_CONTEXT_TTL_SECONDS = "context_ttl_seconds"
CONF_CUSTOM_ALIASES = "custom_aliases"
CONF_CONTROL_USER_IDS = "control_user_ids"
CONF_ADMIN_ONLY_ENTITIES = "admin_only_entities"

# Domains the intent set can act on or (for "sensor"/"binary_sensor") read
# state from. Mirrors service_call.py's IntentSpec/QueryIntentSpec.allowed_domains.
# "binary_sensor" (V4.2, Semantic Query Engine) is exposed as a full domain,
# not filtered to window/door device classes - it becomes selectable in
# config_flow.py's entity picker like any other domain, same as "sensor".
# "script" (Skript-Aktivierung, 2026-08-20): scripts were never selectable at
# all before this, so build_entity_snapshots() silently produced zero
# script.* entities - the root cause "aktiviere Skript X" never worked, not
# a missing intent/parser (see service_call.py's HassRunScript).
SELECTABLE_DOMAINS = (
    "light", "switch", "fan", "cover", "sensor", "binary_sensor", "script",
    "climate", "media_player", "vacuum", "scene", "lock", "calendar",
    "humidifier", "water_heater", "select", "number", "input_number",
    "input_boolean", "button", "valve", "lawn_mower", "camera", "notify",
    "todo", "timer", "alarm_control_panel", "group",
)

NOT_UNDERSTOOD_TEXT = "Das habe ich nicht verstanden."
