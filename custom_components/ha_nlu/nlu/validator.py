"""Command Validator (v2 plan Phase 11): checks a ``SemanticCommand`` against
the 9 error classes the plan defines, returning the first violated one (or
``None`` if the command is safe to execute).

Today's six hassil-based parsers (``parsers.py``) already self-police most
of these - they return ``None`` *before* a frame/command is ever built
whenever entity resolution fails, ambiguity occurs, the domain is wrong, an
area doesn't resolve, a quantifier count is wrong, or the intent isn't
registered (see docstrings on ``SingleTargetParser``/``QuantifierParser``/
``PercentageParser``/``LightExtendedParser``/``FanExtendedParser``/
``ClimateExtendedParser``). This validator is deliberately
built anyway, for the same reason ``Capability`` (Phase 9) and
``SemanticCommand`` (Phase 10) were
built ahead of their consumers: the plan's later LLM Adapter phase (LLM
output is always untrusted input) will not self-police the way the current
parsers do, and will need this as its actual gatekeeper. The one check with
no current upstream enforcement at all - and therefore the most immediately
valuable part of this phase - is ``UNSUPPORTED_CAPABILITY``: no existing
parser reads ``EntitySnapshot.capabilities``.

Kept free of Home Assistant/hassil imports (same boundary as nlu/frame.py
and nlu/command.py); ``service_call.py`` is already hass-free too.
"""

from __future__ import annotations

from enum import Enum, auto

from ..service_call import (
    CLIMATE_EXTENDED_INTENTS,
    FAN_EXTENDED_INTENTS,
    INTENTS,
    LIGHT_EXTENDED_INTENTS,
    PERCENT_INTENTS,
    QUERY_INTENTS,
)
from .capabilities import Capability
from .command import SemanticCommand


class ValidationError(Enum):
    UNKNOWN_INTENT = auto()
    ENTITY_NOT_FOUND = auto()
    AMBIGUOUS_ENTITY = auto()
    AREA_NOT_FOUND = auto()
    INVALID_DOMAIN = auto()
    UNSUPPORTED_CAPABILITY = auto()
    MISSING_PARAMETER = auto()
    INVALID_PARAMETER = auto()
    INVALID_QUANTIFIER = auto()


# The single grammar-level intent name percent commands use (see
# PERCENT_INTENTS in service_call.py) - which service call applies is
# decided per resolved entity domain, not by a domain-specific intent name.
_PERCENT_INTENT_NAME = "HassSetPercentage"

# Which Capability a percent command requires on its target entity, per
# domain - the check no existing parser performs today.
_PERCENT_CAPABILITY_BY_DOMAIN: dict[str, Capability] = {
    "cover": Capability.POSITION,
    "light": Capability.BRIGHTNESS,
}

# Matches ClimateExtendedParser's RangeSlotList bounds (parsers.py) - kept in
# sync there and here rather than importing across that boundary, same
# precedent PERCENT/level range checks below already follow (0-100, 1-10).
_CLIMATE_TEMPERATURE_MIN = 5
_CLIMATE_TEMPERATURE_MAX = 30


def validate_command(command: SemanticCommand) -> ValidationError | None:
    frame = command.source_frame
    is_percent_intent = command.intent == _PERCENT_INTENT_NAME
    is_light_extended_intent = command.intent in LIGHT_EXTENDED_INTENTS
    is_fan_extended_intent = command.intent in FAN_EXTENDED_INTENTS
    is_climate_extended_intent = command.intent in CLIMATE_EXTENDED_INTENTS

    # 1. Intent vorhanden?
    if (
        not is_percent_intent
        and not is_light_extended_intent
        and not is_fan_extended_intent
        and not is_climate_extended_intent
        and command.intent not in QUERY_INTENTS
        and command.intent not in INTENTS
    ):
        return ValidationError.UNKNOWN_INTENT

    # 2. Target vorhanden?
    if not command.entities:
        return ValidationError.ENTITY_NOT_FOUND

    # 3. Target eindeutig auflösbar? (a non-quantifier command resolving to
    # more than one entity is a detectable invariant violation - true
    # ambiguity during resolution never reaches a SemanticCommand at all,
    # since resolve_entity() already returns NOT_FOUND for it upstream)
    if frame.quantifier is None and len(command.entities) > 1:
        return ValidationError.AMBIGUOUS_ENTITY

    # 4. Area gültig?
    if frame.area is not None and command.area is None:
        return ValidationError.AREA_NOT_FOUND

    # 5. Domain erlaubt?
    if is_percent_intent:
        allowed_domains = PERCENT_INTENTS.keys()
    elif is_light_extended_intent:
        allowed_domains = frozenset({"light"})
    elif is_fan_extended_intent:
        allowed_domains = frozenset({"fan"})
    elif is_climate_extended_intent:
        allowed_domains = frozenset({"climate"})
    elif command.intent in QUERY_INTENTS:
        allowed_domains = QUERY_INTENTS[command.intent].allowed_domains
    else:
        allowed_domains = INTENTS[command.intent].allowed_domains
    if any(entity.domain not in allowed_domains for entity in command.entities):
        return ValidationError.INVALID_DOMAIN

    # 6. Capability vorhanden?
    if is_percent_intent:
        for entity in command.entities:
            required = _PERCENT_CAPABILITY_BY_DOMAIN.get(entity.domain)
            if required is not None and required.name not in entity.capabilities:
                return ValidationError.UNSUPPORTED_CAPABILITY
    elif is_light_extended_intent:
        required_light_capability = LIGHT_EXTENDED_INTENTS[command.intent].capability
        for entity in command.entities:
            if required_light_capability.name not in entity.capabilities:
                return ValidationError.UNSUPPORTED_CAPABILITY
    elif is_fan_extended_intent:
        required_fan_capability = FAN_EXTENDED_INTENTS[command.intent].capability
        for entity in command.entities:
            if required_fan_capability.name not in entity.capabilities:
                return ValidationError.UNSUPPORTED_CAPABILITY
    elif is_climate_extended_intent:
        required_climate_capability = CLIMATE_EXTENDED_INTENTS[command.intent].capability
        for entity in command.entities:
            if required_climate_capability.name not in entity.capabilities:
                return ValidationError.UNSUPPORTED_CAPABILITY

    # 7. Parameter vorhanden?
    if is_percent_intent and "percent" not in command.parameters:
        return ValidationError.MISSING_PARAMETER
    if command.intent == "HassFanSetSpeed" and "level" not in command.parameters:
        return ValidationError.MISSING_PARAMETER
    if command.intent == "HassClimateSetTemperature" and "temperature" not in command.parameters:
        return ValidationError.MISSING_PARAMETER

    # 8. Parameter gültig?
    if is_percent_intent:
        percent = command.parameters["percent"]
        if not isinstance(percent, int) or not 0 <= percent <= 100:
            return ValidationError.INVALID_PARAMETER
    if command.intent == "HassFanSetSpeed":
        level = command.parameters["level"]
        if not isinstance(level, int) or not 1 <= level <= 10:
            return ValidationError.INVALID_PARAMETER
    if command.intent == "HassClimateSetTemperature":
        temperature = command.parameters["temperature"]
        if not isinstance(temperature, int) or not _CLIMATE_TEMPERATURE_MIN <= temperature <= _CLIMATE_TEMPERATURE_MAX:
            return ValidationError.INVALID_PARAMETER

    # 9. Quantifier gültig?
    if frame.quantifier is not None and frame.quantifier.kind == "both" and len(command.entities) != 2:
        return ValidationError.INVALID_QUANTIFIER

    return None
