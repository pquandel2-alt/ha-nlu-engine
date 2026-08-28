"""Compatibility adapters for compositional group semantics.

V7 removed the second domain/action/quantity regex vocabulary that used to
live here.  Legacy parser call sites remain stable while every group meaning
is now compiled by the shared ``SemanticCommandCompiler`` and catalogue.
"""

from __future__ import annotations

from ..entities import EntitySnapshot
from .parser import ParseResult
from .semantic_compiler import SemanticCommandCompiler
from .semantic_location import resolve_location_name


def resolve_group_location(
    name: str, entities: list[EntitySnapshot]
) -> tuple[str | None, str | None] | None:
    """Resolve a group scope through the canonical location resolver."""
    return resolve_location_name(name, entities)


def _group_result(text: str, entities: list[EntitySnapshot]) -> ParseResult | None:
    result = SemanticCommandCompiler.compile(text, entities)
    if not isinstance(result, ParseResult):
        return None
    return result if result.frame.quantifier is not None else None


def parse_flexible_group_command(
    text: str, entities: list[EntitySnapshot]
) -> ParseResult | None:
    """Compile a non-percentage group command through the shared core."""
    result = _group_result(text, entities)
    if result is None or result.frame.intent == "HassSetPercentage":
        return None
    return result


def parse_flexible_percentage_group(
    text: str, entities: list[EntitySnapshot]
) -> ParseResult | None:
    """Compile a percentage group command through the shared core."""
    result = _group_result(text, entities)
    if result is None or result.frame.intent != "HassSetPercentage":
        return None
    return result
