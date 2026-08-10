"""Capability System (v2 plan Phase 9): what an entity can actually do,
derived deterministically from its domain and its raw HA state attributes -
never guessed from its name or domain alone. A later phase (Command
Validator, Phase 11) reads the resulting set off ``EntitySnapshot.capabilities``
to reject a command the entity structurally can't perform (e.g. "mach Lampe y
blau" on a brightness-only light) as UNSUPPORTED_CAPABILITY instead of
silently building a wrong or no-op ServiceCall.

``derive_capabilities()`` takes plain domain/device_class/attributes rather
than a full ``EntitySnapshot`` because it runs *while* ``hass_entities.py``
builds one (its result fills the snapshot's own ``capabilities`` field, the
same "prepare inputs, construct once" shape already used there for aliases/
area). Kept free of Home Assistant/hassil imports (same boundary as
nlu/frame.py) so it stays unit-testable without mocking ``hass``.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any, Mapping


class Capability(Enum):
    TURN_ON = auto()
    TURN_OFF = auto()
    BRIGHTNESS = auto()
    COLOR = auto()
    COLOR_TEMPERATURE = auto()
    POSITION = auto()
    TEMPERATURE = auto()
    HUMIDITY = auto()
    FAN_SPEED = auto()


# HA light ColorMode values (homeassistant.components.light.ColorMode) that
# imply each lighting capability. Referenced by their stable string values
# rather than importing the HA enum, to keep this module hass-free.
_LIGHT_COLOR_MODES = frozenset({"hs", "rgb", "rgbw", "rgbww", "xy"})
_LIGHT_COLOR_TEMP_MODES = frozenset({"color_temp"})
_LIGHT_BRIGHTNESS_MODES = frozenset({"brightness"}) | _LIGHT_COLOR_MODES | _LIGHT_COLOR_TEMP_MODES


def derive_capabilities(
    domain: str, device_class: str | None, attributes: Mapping[str, Any]
) -> frozenset[Capability]:
    """Deterministic capability set for one entity.

    Every capability is read off a concrete HA signal - ``supported_color_modes``
    for lights, ``current_position``/``percentage`` presence for covers/fans,
    ``device_class`` for sensors. An entity that doesn't report a signal
    simply doesn't get the capability; nothing here is inferred from the
    domain alone beyond the baseline on/off contract HA itself guarantees
    for light/switch/fan.
    """
    caps: set[Capability] = set()

    if domain in ("light", "switch", "fan"):
        caps.add(Capability.TURN_ON)
        caps.add(Capability.TURN_OFF)

    if domain == "light":
        color_modes = frozenset(attributes.get("supported_color_modes") or ())
        if color_modes & _LIGHT_BRIGHTNESS_MODES:
            caps.add(Capability.BRIGHTNESS)
        if color_modes & _LIGHT_COLOR_MODES:
            caps.add(Capability.COLOR)
        if color_modes & _LIGHT_COLOR_TEMP_MODES:
            caps.add(Capability.COLOR_TEMPERATURE)

    if domain == "cover" and "current_position" in attributes:
        caps.add(Capability.POSITION)

    if domain == "fan" and "percentage" in attributes:
        caps.add(Capability.FAN_SPEED)

    if domain == "sensor":
        if device_class == "temperature":
            caps.add(Capability.TEMPERATURE)
        if device_class == "humidity":
            caps.add(Capability.HUMIDITY)

    return frozenset(caps)
