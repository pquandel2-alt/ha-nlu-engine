"""Closed, multi-step household automation scenarios after LanguageDocument."""

from __future__ import annotations

import re

from .automation_results import AutomationMatchResult
from .entities import EntitySnapshot, normalize_for_compare
from .nlu.action_model import ActionModel, ActionType
from .nlu.automation_model import (
    AutomationModel,
    TriggerModel,
    TriggerTarget,
    TriggerType,
)
from .nlu.automation_validator import AutomationValidationError, validate_automation
from .nlu.language_frontend import LanguageDocument
from .nlu.semantic_state import SemanticState


_DOWNSTAIRS_SHUTDOWN_RE = re.compile(
    r"\bwenn\s+niemand\s+(?:mehr\s+)?unten\s+ist\b.*"
    r"\bmach\b.*\bdort\b.*\balles\b.*\baus\b.*"
    r"\blass\b.*\bflurlicht\b.*\b(?:zehn|10)\s+minuten\b.*\ban\b"
)
_LOW_RISK_OFF_DOMAINS = frozenset(
    {"light", "switch", "fan", "media_player", "climate", "humidifier", "input_boolean"}
)


def interpret_downstairs_shutdown(
    document: LanguageDocument,
    entities: list[EntitySnapshot],
) -> AutomationMatchResult | None:
    """Build an exact-ID preview for the bounded downstairs shutdown scenario."""
    if not _DOWNSTAIRS_SHUTDOWN_RE.search(document.normalized_text.casefold()):
        return None
    occupancy = [
        entity
        for entity in entities
        if entity.domain == "binary_sensor"
        and entity.floor_id is not None
        and (
            (entity.device_class or "").casefold() in {"occupancy", "presence"}
            or "anwesenheit" in normalize_for_compare(entity.friendly_name)
        )
    ]
    levels = [entity.floor_level for entity in occupancy if entity.floor_level is not None]
    if levels:
        lowest = min(levels)
        occupancy = [entity for entity in occupancy if entity.floor_level == lowest]
    if len(occupancy) != 1:
        return _rejected(
            document.source_text,
            "Ich finde unten keinen eindeutig konfigurierten Anwesenheitssensor. Es wurde nichts angelegt.",
            AutomationValidationError.AMBIGUOUS_ENTITY,
        )
    floor_id = occupancy[0].floor_id
    hall_lights = [
        entity
        for entity in entities
        if entity.floor_id == floor_id
        and entity.domain == "light"
        and "flurlicht" in normalize_for_compare(entity.friendly_name)
    ]
    if len(hall_lights) != 1:
        return _rejected(
            document.source_text,
            "Das Flurlicht unten ist nicht eindeutig. Es wurde nichts angelegt.",
            AutomationValidationError.AMBIGUOUS_ENTITY,
        )
    hall = hall_lights[0]
    shutdown = [
        entity
        for entity in entities
        if entity.floor_id == floor_id
        and entity.entity_id != hall.entity_id
        and entity.domain in _LOW_RISK_OFF_DOMAINS
        and "TURN_OFF" in entity.capabilities
    ]
    if not shutdown or "TURN_OFF" not in hall.capabilities:
        return _rejected(
            document.source_text,
            "Unten fehlen eindeutig abschaltbare Geräte oder die Fähigkeit des Flurlichts. Es wurde nichts angelegt.",
            AutomationValidationError.UNSUPPORTED_CAPABILITY,
        )
    model = AutomationModel(
        triggers=(
            TriggerModel(
                TriggerType.STATE,
                target=TriggerTarget(entity_id=occupancy[0].entity_id),
                state=SemanticState.OFF,
            ),
        ),
        actions=(
            ActionModel(
                ActionType.TURN_OFF,
                target=TriggerTarget(entity_ids=tuple(item.entity_id for item in shutdown)),
            ),
            ActionModel(ActionType.DELAY, delay_seconds=600),
            ActionModel(
                ActionType.TURN_OFF,
                target=TriggerTarget(entity_id=hall.entity_id),
            ),
        ),
        source_text=document.source_text,
    )
    error = validate_automation(model)
    return AutomationMatchResult(
        model,
        "Typisierte Automationsvorschau",
        error,
    )


def _rejected(
    source_text: str,
    message: str,
    error: AutomationValidationError,
) -> AutomationMatchResult:
    return AutomationMatchResult(AutomationModel(source_text=source_text), message, error)
