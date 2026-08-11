"""SemanticFrame: the parser's output, one abstraction level above a raw
hassil RecognizeResult. A frame captures *what the user said* (intent plus
textual target/area references) - it is not yet resolved against real HA
entities/areas, and it does not yet imply a ServiceCall. Resolution and
service-call construction remain separate, later pipeline steps.

Kept free of Home Assistant and hassil imports so it can be reused by any
future parser implementation (see plan Phase 2, Intent Parser Registry).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TargetReference:
    """A device/entity as named in the spoken sentence, before resolution."""

    text: str
    entity_id: str | None = None
    domain: str | None = None
    device_class: str | None = None


@dataclass(frozen=True)
class AreaReference:
    """A room/area as named in the spoken sentence, before resolution."""

    text: str
    area_id: str | None = None


@dataclass(frozen=True)
class Quantifier:
    """A structured quantifier reference ("alle"/"beide[n/r]"/"nur"/count
    words) - v2 plan Phase 8, generalizing the raw "all"/"both" string
    previously stashed in ``SemanticFrame.parameters``. ``value`` holds the
    parsed count for ``kind="count"`` (e.g. "die drei Lampen" ->
    kind="count", value=3) - added in Phase 29, "Natural Quantifiers".
    "all"/"both" always carry ``value=None``.
    """

    kind: str
    value: int | None = None


@dataclass(frozen=True)
class Comparison:
    """A relative threshold ("mindestens"/"höchstens"/"nicht höher als"/
    "über"/"unter" + a percent/degree value) - HomeIntent plan V4.6,
    "Comparisons". User decision (2026-08-11): needed both as a SET-command
    setpoint synonym (parsers.py's PercentageParser/ClimateExtendedParser -
    the comparator is captured for observability, but ``value`` still
    drives the actual target the same way a plain number would) and as a
    standalone filter query (parsers.py's ComparisonQueryParser - keeps only
    entities whose current value satisfies the comparison). ``operator`` is
    one of "gte" (mindestens), "lte" (höchstens/nicht höher als), "gt"
    (über), "lt" (unter) - stashed in ``SemanticFrame.parameters["comparison"]``
    rather than becoming a new top-level frame field, same as how percent/
    temperature/step_percent already flow through ``parameters``.
    """

    operator: str
    value: float


@dataclass(frozen=True)
class SemanticFrame:
    intent: str
    target: TargetReference | None
    area: AreaReference | None
    quantifier: Quantifier | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    source_text: str = ""
