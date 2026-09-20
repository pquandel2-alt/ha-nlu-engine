"""Typed, explicitly confirmed local aliases for non-entity meanings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Mapping

from ..entities import normalize_for_compare
from .primitives import SemanticAction


class SemanticAliasKind(Enum):
    SEMANTIC = auto()
    ROUTINE = auto()


@dataclass(frozen=True)
class SemanticAliasMeaning:
    action: SemanticAction
    parameters: tuple[tuple[str, str | float | int], ...] = ()


@dataclass(frozen=True)
class SemanticAliasDraft:
    phrase: str
    kind: SemanticAliasKind
    meaning: SemanticAliasMeaning | None = None
    routine_entity_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind is SemanticAliasKind.SEMANTIC and self.meaning is None:
            raise ValueError("Ein semantischer Alias braucht eine strukturierte Bedeutung")
        if self.kind is SemanticAliasKind.ROUTINE and self.routine_entity_id is None:
            raise ValueError("Ein Routine-Alias braucht eine bestätigte Scene/Automation-ID")


class ConfirmedSemanticAliasStore:
    """Small config model; callers own persistence and confirmation UI."""

    def __init__(self) -> None:
        self._rules: dict[str, SemanticAliasDraft] = {}

    @property
    def rules(self) -> Mapping[str, SemanticAliasDraft]:
        return dict(self._rules)

    def add(self, draft: SemanticAliasDraft, *, confirmed: bool) -> None:
        if not confirmed:
            raise ValueError("Semantische Aliase dürfen nur bestätigt gespeichert werden")
        key = normalize_for_compare(draft.phrase).strip()
        if len(key) < 2:
            raise ValueError("Alias ist zu kurz")
        existing = self._rules.get(key)
        if existing is not None and existing != draft:
            raise ValueError("Alias hat bereits eine andere Bedeutung")
        self._rules[key] = draft

    def lookup(self, phrase: str) -> SemanticAliasDraft | None:
        return self._rules.get(normalize_for_compare(phrase).strip())
