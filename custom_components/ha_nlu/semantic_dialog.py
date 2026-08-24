"""Dialog completion for commands with one missing semantic component."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .device_control import DeviceControlResult, _mentioned_entity
from .entities import EntitySnapshot, ResolveStatus, normalize_for_compare, resolve_entity
from .nlu.context import PendingSemanticCommand
from .service_call import ServiceCallPlan


@dataclass(frozen=True)
class SemanticDialogOutcome:
    pending: PendingSemanticCommand | None = None
    question: str | None = None
    result: DeviceControlResult | None = None


_COMMAND_RE = re.compile(r"\b(?:stell\w*|setz\w*|regel\w*|mach\w*|schalt\w*|fahr\w*|öffn\w*|schließ\w*)\b", re.I)
_SOME_RE = re.compile(r"\b(?:ein\s+paar|einige\w*|mehrere\w*)\b", re.I)
_NUMBER_RE = re.compile(r"\b(-?\d+(?:[,.]\d+)?)\s*(grad|prozent|%)?\b", re.I)

_DOMAIN_WORDS = {
    "light": ("licht", "lichter", "lampen", "beleuchtung"),
    "switch": ("schalter", "steckdosen"),
    "cover": ("rollladen", "rollläden", "rollos", "jalousien"),
    "fan": ("ventilatoren", "lüfter"),
    "climate": ("heizungen", "thermostate"),
    "input_boolean": ("helfer", "modi"),
}


def _spoken_domain(text: str) -> str | None:
    normalized = normalize_for_compare(text)
    matches = [
        domain
        for domain, words in _DOMAIN_WORDS.items()
        if any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", normalized) for word in words)
    ]
    return matches[0] if len(matches) == 1 else None


def _action(text: str, domain: str) -> tuple[str, str, str] | None:
    actions = []
    if re.search(r"\b(?:an|ein|einschalt\w*|anmach\w*)\b", text, re.I):
        actions.append(("homeassistant", "turn_on", "eingeschaltet"))
    if re.search(r"\b(?:aus|ausschalt\w*|ausmach\w*)\b", text, re.I):
        actions.append(("homeassistant", "turn_off", "ausgeschaltet"))
    if domain == "cover" and re.search(r"\b(?:hoch|öffn\w*)\b", text, re.I):
        actions.append(("cover", "open_cover", "geöffnet"))
    if domain == "cover" and re.search(r"\b(?:runter|herunter|schließ\w*)\b", text, re.I):
        actions.append(("cover", "close_cover", "geschlossen"))
    return actions[0] if len(actions) == 1 else None


def _temperature_result(
    entity: EntitySnapshot, value: float
) -> DeviceControlResult | None:
    try:
        minimum = float(entity.attributes.get("min_temp", 7))
        maximum = float(entity.attributes.get("max_temp", 35))
    except (TypeError, ValueError):
        return None
    if not minimum <= value <= maximum:
        return None
    return DeviceControlResult(
        ServiceCallPlan("climate", "set_temperature", entity.entity_id, {"temperature": value}),
        f"{entity.friendly_name} auf {value:g} Grad gestellt.",
        entity=entity,
    )


def start_semantic_dialog(
    text: str, entities: list[EntitySnapshot]
) -> SemanticDialogOutcome | None:
    """Recognize safe partial commands after all complete parsers declined."""
    if not _COMMAND_RE.search(text) or re.search(
        r"\b(?:nicht|kein\w*|ohne|vielleicht|normalerweise|gestern)\b", text, re.I
    ):
        return None

    if _SOME_RE.search(text):
        domain = _spoken_domain(text)
        if domain is None or (operation := _action(text, domain)) is None:
            return None
        candidates = tuple(entity for entity in entities if entity.domain == domain)
        if len(candidates) < 2:
            return None
        service_domain, service, response_verb = operation
        pending = PendingSemanticCommand(
            "selection", candidates, service_domain, service, {}, response_verb
        )
        return SemanticDialogOutcome(
            pending=pending,
            question="Welche Geräte genau? Bitte nenne ihre Namen.",
        )

    number = _NUMBER_RE.search(text)
    if number is not None and (number.group(2) or "temperatur" in text.casefold()):
        value = float(number.group(1).replace(",", "."))
        candidates = tuple(
            entity for entity in entities
            if entity.domain == "climate" and "TEMPERATURE" in entity.capabilities
        )
        named = _mentioned_entity(text, list(candidates), frozenset({"climate"}))
        if named is not None:
            return None
        if len(candidates) == 1:
            result = _temperature_result(candidates[0], value)
            return SemanticDialogOutcome(result=result) if result is not None else None
        if len(candidates) > 1:
            pending = PendingSemanticCommand(
                "target", candidates, "climate", "set_temperature",
                {"temperature": value}, "eingestellt",
            )
            return SemanticDialogOutcome(pending=pending, question="Welche Heizung meinst du?")

    climate = _mentioned_entity(text, entities, frozenset({"climate"}))
    if climate is not None and re.search(r"\b(?:temperatur|grad|stell\w*|regel\w*)\b", text, re.I):
        pending = PendingSemanticCommand(
            "value", (climate,), "climate", "set_temperature", {}, "eingestellt"
        )
        return SemanticDialogOutcome(
            pending=pending,
            question=f"Auf welche Temperatur soll ich {climate.friendly_name} stellen?",
        )
    return None


def continue_semantic_dialog(
    text: str, pending: PendingSemanticCommand
) -> SemanticDialogOutcome:
    """Fill the one missing component without widening the candidate set."""
    if pending.missing == "value":
        number = _NUMBER_RE.search(text)
        if number is None:
            return SemanticDialogOutcome(pending=pending, question="Bitte nenne die gewünschte Temperatur in Grad.")
        result = _temperature_result(
            pending.candidates[0], float(number.group(1).replace(",", "."))
        )
        if result is None:
            return SemanticDialogOutcome(pending=pending, question="Diese Temperatur wird nicht unterstützt. Welche Temperatur möchtest du?")
        return SemanticDialogOutcome(result=result)

    if pending.missing == "target":
        resolved = resolve_entity(text.strip(" .!?"), list(pending.candidates))
        if resolved.status is not ResolveStatus.OK or resolved.entity is None:
            return SemanticDialogOutcome(pending=pending, question="Das ist noch nicht eindeutig. Welche Heizung meinst du?")
        value = float(pending.data["temperature"])
        result = _temperature_result(resolved.entity, value)
        return SemanticDialogOutcome(result=result) if result is not None else SemanticDialogOutcome(
            pending=pending, question="Der Wert wird von dieser Heizung nicht unterstützt."
        )

    selected = []
    normalized = normalize_for_compare(text)
    for entity in pending.candidates:
        names = (entity.friendly_name, *entity.aliases)
        if any(
            (candidate := normalize_for_compare(name))
            and re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", normalized)
            for name in names
        ):
            selected.append(entity)
    if not selected:
        return SemanticDialogOutcome(pending=pending, question="Ich konnte daraus keine eindeutigen Gerätenamen erkennen. Welche Geräte genau?")
    plan = ServiceCallPlan(
        pending.service_domain,
        pending.service,
        [entity.entity_id for entity in selected],
        dict(pending.data),
    )
    return SemanticDialogOutcome(
        result=DeviceControlResult(
            plan,
            f"{len(selected)} Geräte {pending.response_verb}.",
        )
    )
