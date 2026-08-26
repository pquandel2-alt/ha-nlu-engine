"""Deterministic scope corrections for an already understood command."""

from __future__ import annotations

import re

from .areas import AreaResolveStatus, resolve_area_name
from .entities import EntitySnapshot
from .floors import FloorResolveStatus, resolve_floor_name
from .nlu.context import ConversationContext
from .nlu.entity_resolution import ResolutionStatus, resolve_entity_scored
from .nlu.frame import AreaReference, SemanticFrame, TargetReference
from .nlu.normalize import normalize
from .nlu.parse_outcome import ParseFailureReason, UnderstandingFeedback
from .nlu.parser import ClarificationRequest, ParseResult


_CORRECTION_RE = re.compile(
    r"^(?:nein[,.]?\s*)?(?:"
    r"nicht\s+.+?\s+sondern\s+|"
    r"(?:ich\s+)?meinte\s+|"
    r"nur\s+(?:(?:in\s+der|in\s+dem|im|am)\s+)?"
    r")(?P<location>.+?)\s*[?.!]*$",
    re.IGNORECASE,
)


class ConversationCorrectionResolver:
    """Retarget the previous action while retaining its validated meaning."""

    def resolve(
        self,
        text: str,
        entities: list[EntitySnapshot],
        context: ConversationContext | None,
    ) -> ParseResult | ClarificationRequest | UnderstandingFeedback | None:
        if context is None or context.last_command is None:
            return None
        previous = context.last_command
        # Query corrections already have richer delta semantics in
        # QueryFollowupParser and must not be reinterpreted as actions here.
        if previous.intent.startswith("HassGet") or "Query" in previous.intent:
            return None
        if not previous.entities:
            return None

        match = _CORRECTION_RE.match(normalize(text))
        if match is None:
            return None
        location = match.group("location").strip()
        domain = previous.entities[0].domain
        named = resolve_entity_scored(
            location, [entity for entity in entities if entity.domain == domain]
        )
        if named.status is ResolutionStatus.RESOLVED and named.entity is not None:
            entity = named.entity
            frame = SemanticFrame(
                intent=previous.intent,
                target=TargetReference(
                    text=entity.friendly_name,
                    entity_id=entity.entity_id,
                    domain=entity.domain,
                ),
                area=(
                    AreaReference(text=entity.area_name, area_id=entity.area_id)
                    if entity.area_id is not None and entity.area_name is not None
                    else None
                ),
                parameters=dict(previous.parameters),
                source_text=text,
            )
            return ParseResult(frame=frame, resolved_entities=[entity])
        if named.status is ResolutionStatus.AMBIGUOUS:
            return ClarificationRequest(
                pending_intent=previous.intent,
                pending_target=domain,
                candidates=named.candidates,
                pending_parameters=previous.parameters,
            )
        area = resolve_area_name(location, entities)
        floor_id: str | None = None
        area_id: str | None = None
        area_name: str | None = None
        if area.status is AreaResolveStatus.OK:
            area_id, area_name = area.area_id, location
        elif area.status is AreaResolveStatus.AMBIGUOUS:
            return UnderstandingFeedback(
                ParseFailureReason.AMBIGUOUS_TARGET,
                f"Der Ort {location} ist nicht eindeutig.",
            )
        else:
            floor = resolve_floor_name(location, entities)
            if floor.status is not FloorResolveStatus.OK:
                return UnderstandingFeedback(
                    ParseFailureReason.UNKNOWN_LOCATION,
                    f"Ich kenne keinen Raum und keine Etage namens {location}.",
                )
            floor_id = floor.floor_id

        candidates = [
            entity for entity in entities
            if entity.domain == domain
            and (area_id is None or entity.area_id == area_id)
            and (floor_id is None or entity.floor_id == floor_id)
        ]
        if not candidates:
            return UnderstandingFeedback(
                ParseFailureReason.UNKNOWN_ENTITY,
                f"Dort ist kein passendes Gerät der Art {domain} für Assist freigegeben.",
            )
        if len(candidates) > 1:
            return ClarificationRequest(
                pending_intent=previous.intent,
                pending_target=domain,
                candidates=tuple(candidates),
                pending_parameters=previous.parameters,
            )

        entity = candidates[0]
        frame = SemanticFrame(
            intent=previous.intent,
            target=TargetReference(
                text=entity.friendly_name,
                entity_id=entity.entity_id,
                domain=entity.domain,
            ),
            area=(
                AreaReference(text=area_name, area_id=area_id)
                if area_id is not None and area_name is not None
                else None
            ),
            parameters=dict(previous.parameters),
            source_text=text,
        )
        return ParseResult(frame=frame, resolved_entities=[entity])
