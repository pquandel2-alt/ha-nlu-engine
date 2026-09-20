"""Small HA-free primitives for answers grounded in observed state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TruthValue(Enum):
    TRUE = auto()
    FALSE = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class GroundedAnswer:
    """A rendered fact together with its explicit evidential status."""

    truth: TruthValue
    speech: str
    evidence: str


def render_state_answer(
    entity_name: str,
    current_description: str,
    evaluation: bool | None,
    *,
    negated_question: bool = False,
) -> GroundedAnswer:
    """Render German polarity without turning missing evidence into ``Nein``."""
    evidence = f"{entity_name}: {current_description}"
    if evaluation is None:
        return GroundedAnswer(
            TruthValue.UNKNOWN,
            f"Das kann ich aus dem verfügbaren Zustand nicht sicher erkennen. "
            f"{entity_name} {current_description}.",
            evidence,
        )
    truth = TruthValue.TRUE if evaluation else TruthValue.FALSE
    prefix = "Doch" if negated_question and evaluation else "Nein" if not evaluation else "Ja"
    return GroundedAnswer(
        truth,
        f"{prefix}, {entity_name} {current_description}.",
        evidence,
    )


def join_german(items: list[str] | tuple[str, ...]) -> str:
    """Join labels as a natural German enumeration."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" und {items[-1]}"
