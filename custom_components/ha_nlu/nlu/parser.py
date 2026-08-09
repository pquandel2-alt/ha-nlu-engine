"""IntentParser abstraction (v2 plan, Phase 2): engine.py should orchestrate
routing and ServiceCall construction only, not contain the sentence-
matching logic itself. Concrete, hassil-based parsers live in
``ha_nlu.parsers`` (outside this package, since ``nlu/`` stays free of
hassil/HA imports) and implement this Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..entities import EntitySnapshot
from .frame import SemanticFrame


@dataclass(frozen=True)
class ParseContext:
    entities: list[EntitySnapshot]


@dataclass(frozen=True)
class ParseResult:
    frame: SemanticFrame
    resolved_entities: list[EntitySnapshot]


@runtime_checkable
class IntentParser(Protocol):
    def parse(self, text: str, context: ParseContext) -> ParseResult | None: ...
