"""Validate the HomeIntent options flow form against a REAL Home Assistant.

Runs inside the ``home-assistant:stable`` container (CI smoke job). Builds
the options form with Home Assistant's real selectors, serializes it the way
``/api/config/config_entries/options/flow`` does for the Configure dialog,
and validates the form's own prefilled values the way Save does. HomeIntent
7.1.0 failed the first step on 2026.9 (``domain=`` tuple -> HTTP 400) and
the last one (``None`` TTS default). The full HTTP/Learning Center scenario
lives in ``tests_ha/``.
"""

from __future__ import annotations

import asyncio
from typing import Any

# Import Home Assistant first: current releases install their voluptuous
# replacement (probatio) on import, and it must precede any voluptuous use.
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import EntitySelector

from homeintent.config_flow import HomeIntentOptionsFlow
from homeintent.const import (
    CONF_EXPERIENCE_LEARNING_ENABLED,
    CONF_HABIT_DISCOVERY_ENABLED,
    CONF_PREDICTIVE_MODELS_ENABLED,
    CONF_PROACTIVE_CONTEXT_ENABLED,
    CONF_PROACTIVE_SUGGESTIONS_ENABLED,
    SELECTABLE_DOMAINS,
)

try:  # Home Assistant 2026.x
    from probatio import to_field_list as _serialize
except ImportError:  # older releases
    from voluptuous_serialize import convert as _serialize  # type: ignore[no-redef]

LEARNING_SWITCHES = (
    CONF_EXPERIENCE_LEARNING_ENABLED,
    CONF_PREDICTIVE_MODELS_ENABLED,
    CONF_HABIT_DISCOVERY_ENABLED,
    CONF_PROACTIVE_SUGGESTIONS_ENABLED,
    CONF_PROACTIVE_CONTEXT_ENABLED,
)


class _NoAuthHass:
    auth = None


async def _check() -> None:
    flow = HomeIntentOptionsFlow()
    flow.hass = _NoAuthHass()  # type: ignore[assignment]
    schema = await flow._async_schema({})  # pyright: ignore[reportPrivateUsage]

    for key, value in schema.schema.items():
        if isinstance(value, EntitySelector):
            domain = value.config.get("domain")
            assert isinstance(domain, list) and all(isinstance(d, str) for d in domain), (
                str(key), domain,
            )

    fields: list[dict[str, Any]] = _serialize(schema, custom_serializer=cv.custom_serializer)
    by_name = {field["name"]: field for field in fields}
    assert by_name["selected_entities"]["selector"]["entity"]["domain"] == list(SELECTABLE_DOMAINS)
    for key in LEARNING_SWITCHES:
        assert by_name[key]["type"] == "boolean", key

    form: dict[str, Any] = {}
    for field in fields:
        value = field.get("default", field.get("description", {}).get("suggested_value"))
        if value is not None:
            form[field["name"]] = value
    saved = schema({**form, **{key: True for key in LEARNING_SWITCHES}})
    for key in LEARNING_SWITCHES:
        assert saved[key] is True, key


asyncio.run(_check())
print("Options flow form validated against the real Home Assistant selectors.")
