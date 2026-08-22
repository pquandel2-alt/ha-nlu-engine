"""Deterministic German measurement queries for rooms and floors."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .areas import AreaResolveStatus, resolve_area_name
from .entities import EntitySnapshot, ResolveStatus, resolve_entity
from .floors import FloorResolveStatus, resolve_floor_by_level_keyword, resolve_floor_name
from .nlu.frame import AreaReference, Quantifier, SemanticFrame, TargetReference
from .nlu.parser import ParseResult
from .nlu.parse_outcome import ParseFailureReason
from .nlu.semantic_lexicon import (
    MEASUREMENT_PROPERTY_SPECS,
    SemanticKind,
    analyse_semantics,
)
from .nlu.semantic_location import resolve_semantic_location


@dataclass(frozen=True)
class LocationQueryFeedback:
    response_text: str
    reason: ParseFailureReason = ParseFailureReason.UNSUPPORTED_PROPERTY


_PROPERTIES = {
    "temperatur": ("sensor", "temperature", "Temperatur"),
    "wärme": ("sensor", "temperature", "Temperatur"),
    "luftfeuchtigkeit": ("sensor", "humidity", "Luftfeuchtigkeit"),
    "feuchtigkeit": ("sensor", "humidity", "Luftfeuchtigkeit"),
    "batteriestand": ("sensor", "battery", "Batteriestand"),
    "batterie": ("sensor", "battery", "Batteriestand"),
    "batterien": ("sensor", "battery", "Batteriestand"),
    "leistung": ("sensor", "power", "Leistung"),
    "stromverbrauch": ("sensor", "energy", "Energieverbrauch"),
    "energieverbrauch": ("sensor", "energy", "Energieverbrauch"),
    "helligkeit": ("light", None, "Helligkeit"),
}
_PROPERTY_WORDS = "|".join(sorted(_PROPERTIES, key=len, reverse=True))
_LOCATION_PREFIX = r"(?:in\s+der|in\s+dem|im|am|beim|von|des|der|das|die)\s+"

_PATTERNS = (
    re.compile(
        rf"^wie\s*viele?\s+grad\s+(?:sind|hat)(?:\s+es)?\s+"
        rf"{_LOCATION_PREFIX}(?P<location>.+?)\s*[?.!]*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:wie|was)\s+ist\s+die\s+(?P<property>{_PROPERTY_WORDS})\s+"
        rf"{_LOCATION_PREFIX}(?P<location>.+?)\s*[?.!]*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?P<property>batterie|batterien|batteriestand)\s+"
        rf"(?:{_LOCATION_PREFIX})?(?P<location>.+?)\s+"
        rf"(?P<comparator>unter|über|höchstens|mindestens)\s+"
        rf"(?P<threshold>\d+(?:[,.]\d+)?)\s*(?:prozent|%)?\s*[?.!]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^wie\s+(?:warm|kalt|feucht|hell)\s+(?P<location>.+?)\s*[?.!]*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:wie\s+(?:hoch|warm|kalt|feucht|hell)\s+ist\s+(?:es|die\s+)?|"
        rf"welche\s+)(?P<property>{_PROPERTY_WORDS})?\s*(?:hat|ist)?\s*"
        rf"{_LOCATION_PREFIX}(?P<location>.+?)\s*[?.!]*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:wie\s+(?:warm|kalt|feucht|hell)\s+ist\s+es\s+){_LOCATION_PREFIX}"
        rf"(?P<location>.+?)\s*[?.!]*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?P<average>durchschnitt(?:liche|licher|liches|lichen)?\s+)?"
        rf"(?P<property>{_PROPERTY_WORDS})\s+(?:{_LOCATION_PREFIX})?(?P<location>.+?)\s*[?.!]*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:wie\s+hoch\s+ist\s+die\s+)(?P<property>{_PROPERTY_WORDS})\s+"
        rf"{_LOCATION_PREFIX}(?P<location>.+?)\s*[?.!]*$",
        re.IGNORECASE,
    ),
)


def _default_property(text: str) -> str | None:
    folded = text.casefold()
    if "warm" in folded or "kalt" in folded or "grad" in folded:
        return "temperatur"
    if "feucht" in folded:
        return "luftfeuchtigkeit"
    if "hell" in folded:
        return "helligkeit"
    return None


class LocationPropertyQueryParser:
    @staticmethod
    def _semantic_request(text: str, entities: list[EntitySnapshot]):
        analysis = analyse_semantics(text)
        if (
            analysis.values(SemanticKind.COMMAND_MARKER)
            or re.search(r"^\s*welch\w*\b", text, re.I)
        ):
            return None
        properties = analysis.values(SemanticKind.PROPERTY)
        comparators = analysis.values(SemanticKind.COMPARATOR)
        if len(properties) != 1 or len(comparators) > 1:
            return None
        location = resolve_semantic_location(text, entities)
        if location is None:
            return None

        location_tokens = {
            token.casefold()
            for token in re.findall(r"[\wäöüß]+", location[0], re.I)
        }
        unexplained = {
            token.casefold() for token in analysis.unexplained_tokens
        } - location_tokens
        if unexplained:
            return None

        canonical = next(iter(properties))
        spec = MEASUREMENT_PROPERTY_SPECS.get(canonical)
        if spec is None:
            return None
        comparator = next(iter(comparators), None)
        threshold_match = re.search(r"\b\d+(?:[,.]\d+)?\b", text)
        if comparator is not None and threshold_match is None:
            return None
        comparator_words = {
            "lt": "unter", "gt": "über", "lte": "höchstens", "gte": "mindestens",
        }
        return {
            "property_name": spec[3],
            "spec": spec[:3],
            "location": location[0],
            "comparator": comparator_words.get(comparator),
            "threshold": threshold_match.group(0) if threshold_match is not None else None,
            "average": "average" in analysis.values(SemanticKind.QUERY_SCOPE),
        }

    def parse(
        self, text: str, entities: list[EntitySnapshot]
    ) -> ParseResult | LocationQueryFeedback | None:
        text = re.sub(r"^und\s+", "", text, flags=re.IGNORECASE)
        match = next(
            (candidate for pattern in _PATTERNS if (candidate := pattern.match(text))),
            None,
        )
        semantic_request = None if match is not None else self._semantic_request(text, entities)
        if match is None and semantic_request is None:
            return None
        property_name = (
            (match.groupdict().get("property") or _default_property(text) or "").casefold()
            if match is not None else semantic_request["property_name"]
        )
        spec = _PROPERTIES.get(property_name) if match is not None else semantic_request["spec"]
        if spec is None:
            return None
        location = (
            match.group("location").strip(" ,.?!")
            if match is not None else semantic_request["location"]
        )
        if not location:
            return None

        explicit_location = bool(
            semantic_request is not None
            or
            re.search(r"\b(?:im|in der|in dem|am|beim)\b", text, re.IGNORECASE)
            or re.search(r"\bhat\s+(?:der|die|das)\b", text, re.IGNORECASE)
            or re.match(rf"^(?:{_PROPERTY_WORDS})\b", text, re.IGNORECASE)
        )
        if not explicit_location and resolve_entity(location, entities).status is ResolveStatus.OK:
            return None

        area = resolve_area_name(location, entities)
        floor = None
        if area.status is AreaResolveStatus.NOT_FOUND:
            if location.casefold() in {"oben", "unten"}:
                floor = resolve_floor_by_level_keyword(
                    "up" if location.casefold() == "oben" else "down", entities
                )
            else:
                floor = resolve_floor_name(location, entities)
        if area.status is AreaResolveStatus.AMBIGUOUS or (
            floor is not None and floor.status is FloorResolveStatus.AMBIGUOUS
        ):
            return LocationQueryFeedback(
                f"Der Ort {location} ist nicht eindeutig.",
                ParseFailureReason.AMBIGUOUS_TARGET,
            )
        if area.status is AreaResolveStatus.NOT_FOUND and (
            floor is None or floor.status is FloorResolveStatus.NOT_FOUND
        ):
            # Name-based queries ("wie hell ist das Küchenlicht") belong to
            # the established entity query parser, not to this location
            # parser. Only emit a location error for an unmistakably
            # location-shaped phrase.
            if resolve_entity(location, entities).status is ResolveStatus.OK:
                return None
            if not explicit_location:
                return None
            return LocationQueryFeedback(
                f"Ich kenne keinen Raum und keine Etage namens {location}.",
                ParseFailureReason.UNKNOWN_LOCATION,
            )

        domain, device_class, label = spec
        area_id = area.area_id if area.status is AreaResolveStatus.OK else None
        floor_id = floor.floor_id if floor is not None and floor.status is FloorResolveStatus.OK else None
        matched = [
            entity
            for entity in entities
            if entity.domain == domain
            and (device_class is None or entity.device_class == device_class)
            and (area_id is None or entity.area_id == area_id)
            and (floor_id is None or entity.floor_id == floor_id)
        ]
        comparator = (
            match.groupdict().get("comparator")
            if match is not None else semantic_request["comparator"]
        )
        threshold_raw = (
            match.groupdict().get("threshold")
            if match is not None else semantic_request["threshold"]
        )
        if comparator and threshold_raw:
            threshold = float(threshold_raw.replace(",", "."))
            operators = {
                "unter": lambda value: value < threshold,
                "über": lambda value: value > threshold,
                "höchstens": lambda value: value <= threshold,
                "mindestens": lambda value: value >= threshold,
            }
            predicate = operators[comparator.casefold()]
            filtered: list[EntitySnapshot] = []
            for entity in matched:
                try:
                    if predicate(float(entity.state)):
                        filtered.append(entity)
                except (TypeError, ValueError):
                    continue
            matched = filtered
        if not matched:
            if comparator:
                return LocationQueryFeedback(
                    f"In {location} erfüllt kein {label} die genannte Grenze.",
                    ParseFailureReason.UNKNOWN_ENTITY,
                )
            target_kind = "Sensor" if domain == "sensor" else "Gerät"
            return LocationQueryFeedback(
                f"Für {label} ist in {location} kein passender {target_kind} für Assist freigegeben.",
                ParseFailureReason.UNSUPPORTED_CAPABILITY,
            )
        matched.sort(key=lambda entity: (entity.area_name or "", entity.friendly_name))
        average = (
            bool(match.groupdict().get("average"))
            if match is not None else semantic_request["average"]
        ) or "durchschnitt" in text.casefold()
        frame = SemanticFrame(
            intent="HassLocationPropertyQuery" if len(matched) > 1 or average else "HassGetState",
            target=TargetReference(text=location, domain=domain, device_class=device_class),
            area=(
                AreaReference(text=location, area_id=area_id, area_name=matched[0].area_name)
                if area_id is not None
                else None
            ),
            quantifier=Quantifier(kind="all") if len(matched) > 1 else None,
            parameters={
                "property": property_name,
                "property_label": label,
                "average": average,
                "location_kind": "area" if area_id is not None else "floor",
                "location_id": area_id if area_id is not None else floor_id,
            },
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=matched)
