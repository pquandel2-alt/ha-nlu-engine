"""Resolve local spatial references from an Assist input device."""

from __future__ import annotations

import re

from .areas import AreaSnapshot


_LOCAL_REFERENCE_RE = re.compile(
    r"\b(?:hier|in\s+diesem\s+(?:raum|zimmer)|in\s+dieser\s+umgebung)\b",
    re.I,
)


def materialize_local_reference(text: str, area: AreaSnapshot | None) -> str:
    """Replace a local deictic phrase with one registry-backed area name."""
    if area is None:
        return text
    return _LOCAL_REFERENCE_RE.sub(f"im {area.name}", text)


def resolve_conversation_area(hass, user_input) -> AreaSnapshot | None:
    """Resolve ``device_id``/``satellite_id`` to exactly one HA area."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    device_id = getattr(user_input, "device_id", None)
    satellite_id = getattr(user_input, "satellite_id", None)
    area_id = None

    if satellite_id:
        entity = er.async_get(hass).async_get(str(satellite_id))
        if entity is not None:
            area_id = entity.area_id
            device_id = entity.device_id or device_id
        elif dr.async_get(hass).async_get(str(satellite_id)) is not None:
            device_id = str(satellite_id)

    if area_id is None and device_id:
        device = dr.async_get(hass).async_get(str(device_id))
        if device is not None:
            area_id = device.area_id
    if area_id is None:
        return None

    area = ar.async_get(hass).async_get_area(area_id)
    if area is None:
        return None
    return AreaSnapshot(area_id=area.id, name=area.name, aliases=tuple(area.aliases))
