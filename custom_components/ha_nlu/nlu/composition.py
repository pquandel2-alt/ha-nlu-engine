"""HA-free compositional plan for shared predicates and explicit targets."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..entities import EntitySnapshot
from .entity_resolution import all_mentioned_entities
from .meaning import CoordinationKind, SemanticTurn
from .semantic_lexicon import SemanticKind
from .semantic_utterance import SpeechAct


@dataclass(frozen=True)
class CompositionalPlan:
    """Structural meaning proven before any service call is generated."""

    source_text: str
    targets: tuple[EntitySnapshot, ...]
    action: str | None
    shared_predicate: bool
    atomic: bool = True


def build_compositional_plan(
    turn: SemanticTurn, entities: list[EntitySnapshot]
) -> CompositionalPlan | None:
    """Recognise one safe action distributed over named coordinated targets."""
    markers = turn.semantic_analysis.matching(SemanticKind.COMMAND_MARKER)
    actions = turn.semantic_analysis.values(SemanticKind.ACTION)
    action_values = sorted(value for value in actions if isinstance(value, str))
    if (
        turn.speech_act is not SpeechAct.COMMAND
        or not turn.safe_to_execute_directly
        or turn.coordination is not CoordinationKind.ADDITIVE
        or len(markers) != 1
        or re.search(r"\b(?:außer|ausser|oder)\b", turn.source_text, re.I)
    ):
        return None
    targets = all_mentioned_entities(turn.source_text, entities)
    if len(targets) < 2:
        return None
    return CompositionalPlan(
        turn.source_text,
        targets,
        action_values[-1] if action_values else None,
        shared_predicate=True,
    )


def project_target(plan: CompositionalPlan, selected: EntitySnapshot) -> str:
    """Project one target while preserving the shared predicate verbatim."""
    candidate = plan.source_text
    for entity in plan.targets:
        if entity.entity_id == selected.entity_id:
            continue
        for name in sorted((entity.friendly_name, *entity.aliases), key=len, reverse=True):
            candidate = re.sub(
                rf"(?<!\w){re.escape(name)}(?!\w)", " ", candidate, flags=re.I
            )
    candidate = re.sub(r"\b(?:und|sowie)\b", " ", candidate, flags=re.I)
    return re.sub(r"\s+", " ", candidate).strip(" ,")
