"""Capability-checked controls for additional Home Assistant domains.

The established device router owns entity-name resolution and the common
result type.  This module only composes domain-specific operation/value
semantics, keeping the growing service catalogue out of ``device_control``.
"""

from __future__ import annotations

import re

from .entities import EntitySnapshot, normalize_for_compare
from .device_control import DeviceControlResult


def _feature_mask(entity: EntitySnapshot) -> int:
    try:
        return int(entity.attributes.get("supported_features", 0))
    except (TypeError, ValueError):
        return 0


def _number(text: str) -> float | None:
    match = re.search(r"\bauf\s+(-?\d+(?:[,.]\d+)?)\b", text, re.I)
    return float(match.group(1).replace(",", ".")) if match else None


def _percent(text: str) -> int | None:
    match = re.search(r"\b(100|[1-9]?\d)\s*(?:prozent|%)\b", text, re.I)
    return int(match.group(1)) if match else None


def _option(text: str, entity: EntitySnapshot) -> str | None:
    normalized = normalize_for_compare(text)
    matches = [
        str(option)
        for option in entity.attributes.get("options", ())
        if re.search(
            rf"(?<!\w){re.escape(normalize_for_compare(str(option)))}(?!\w)",
            normalized,
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _bounded_value(
    entity: EntitySnapshot,
    value: float,
    minimum_key: str,
    maximum_key: str,
    default_minimum: float,
    default_maximum: float,
) -> bool:
    try:
        minimum = float(entity.attributes.get(minimum_key, default_minimum))
        maximum = float(entity.attributes.get(maximum_key, default_maximum))
    except (TypeError, ValueError):
        return False
    return minimum <= value <= maximum


def match_extended_device_control(
    text: str,
    entities: list[EntitySnapshot],
    mentioned_entity,
    build_result,
):
    """Return one unambiguous extended-domain service plan or ``None``."""
    entity = mentioned_entity(
        text,
        entities,
        frozenset({
            "humidifier", "water_heater", "select", "number", "input_number",
            "input_boolean", "button", "valve", "lawn_mower", "camera", "notify",
        }),
    )

    if entity is not None and entity.domain in {"input_boolean", "humidifier"}:
        actions = [
            service
            for pattern, service in (
                (r"\b(?:an|ein|einschalt\w*|anmach\w*)\b", "turn_on"),
                (r"\b(?:aus|ausschalt\w*|ausmach\w*)\b", "turn_off"),
                (r"\b(?:umschalt\w*|toggle)\b", "toggle"),
            )
            if re.search(pattern, text, re.I)
        ]
        if len(actions) == 1:
            spoken = {"turn_on": "eingeschaltet", "turn_off": "ausgeschaltet", "toggle": "umgeschaltet"}[actions[0]]
            return build_result(entity, actions[0], f"{entity.friendly_name} {spoken}.")

    if entity is not None and entity.domain == "humidifier":
        humidity = _percent(text)
        if humidity is not None and re.search(r"\b(?:luftfeuchtigkeit|feuchtigkeit)\b", text, re.I):
            if not _bounded_value(entity, humidity, "min_humidity", "max_humidity", 0, 100):
                return DeviceControlResult(
                    None,
                    f"Der Wert liegt außerhalb des unterstützten Bereichs von {entity.friendly_name}.",
                    entity=entity,
                )
            return build_result(
                entity,
                "set_humidity",
                f"{entity.friendly_name} auf {humidity} Prozent Luftfeuchtigkeit gestellt.",
                {"humidity": humidity},
            )

    if entity is not None and entity.domain == "water_heater":
        temperature = _number(text)
        if temperature is not None and re.search(r"\b(?:grad|temperatur|warmwasser)\b", text, re.I):
            if not _bounded_value(entity, temperature, "min_temp", "max_temp", 20, 90):
                return None
            return build_result(
                entity,
                "set_temperature",
                f"{entity.friendly_name} auf {temperature:g} Grad gestellt.",
                {"temperature": temperature},
            )

    if entity is not None and entity.domain in {"number", "input_number"}:
        value = _number(text)
        if value is not None and re.search(r"\b(?:stell\w*|setz\w*|änder\w*|aender\w*)\b", text, re.I):
            if not _bounded_value(entity, value, "min", "max", float("-inf"), float("inf")):
                return None
            return build_result(
                entity, "set_value", f"{entity.friendly_name} auf {value:g} gestellt.", {"value": value}
            )

    if entity is not None and entity.domain == "select":
        option = _option(text, entity)
        if option is not None and re.search(r"\b(?:wähl\w*|waehl\w*|stell\w*|setz\w*)\b", text, re.I):
            return build_result(
                entity, "select_option", f"{entity.friendly_name} auf {option} gestellt.", {"option": option}
            )

    if entity is not None and entity.domain == "button" and re.search(
        r"\b(?:drück\w*|drueck\w*|betätig\w*|betaetig\w*|auslös\w*|ausloes\w*)\b",
        text,
        re.I,
    ):
        return build_result(
            entity, "press", f"{entity.friendly_name} drücken.", confirm=True
        )

    if entity is not None and entity.domain == "valve":
        opening = re.search(r"\b(?:öffn\w*|oeffn\w*)\b", text, re.I)
        closing = re.search(r"\bschließ\w*|\bschliess\w*", text, re.I)
        if bool(opening) != bool(closing):
            required = 1 if opening else 2
            if not _feature_mask(entity) & required:
                return None
            return build_result(
                entity,
                "open_valve" if opening else "close_valve",
                f"{entity.friendly_name} {'öffnen' if opening else 'schließen'}.",
                confirm=True,
            )

    if entity is not None and entity.domain == "lawn_mower":
        operations = [
            (service, feature, spoken)
            for pattern, service, feature, spoken in (
                (r"\b(?:mähe|mähen|maehe|maehen|start\w*)\b", "start_mowing", 1, "starten"),
                (r"\bpaus\w*\b", "pause", 2, "pausieren"),
                (r"\b(?:ladestation|dock)\b", "dock", 4, "zur Ladestation schicken"),
            )
            if re.search(pattern, text, re.I)
        ]
        if len(operations) == 1:
            service, feature, spoken = operations[0]
            if not _feature_mask(entity) & feature:
                return None
            return build_result(entity, service, f"{entity.friendly_name} {spoken}.")

    camera = mentioned_entity(text, entities, frozenset({"camera"}))
    player = mentioned_entity(text, entities, frozenset({"media_player"}))
    if camera is not None and player is not None and re.search(
        r"\b(?:zeig\w*|stream\w*|übertrag\w*|uebertrag\w*)\b", text, re.I
    ):
        return build_result(
            camera,
            "play_stream",
            f"{camera.friendly_name} wird auf {player.friendly_name} angezeigt.",
            {"media_player": player.entity_id},
        )

    if entity is not None and entity.domain == "notify":
        match = re.search(r"\b(?:nachricht|meldung)\s+(.+)$", text, re.I)
        if match and re.search(r"\b(?:send\w*|schick\w*)\b", text, re.I):
            message = match.group(1).strip(" .!?")
            if message:
                return build_result(
                    entity, "send_message", "Nachricht gesendet.", {"message": message}
                )
    return None
