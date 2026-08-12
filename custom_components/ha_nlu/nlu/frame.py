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
    # The resolved area's display name (mirrors TargetReference.device_class:
    # unused by existing parsers, populated by StateQueryParser (V4.2) so
    # nlu/command.py::_resolve_area_snapshot() can still build an
    # AreaSnapshot when a query legitimately resolves zero entities in an
    # otherwise-valid area - resolving the area itself doesn't depend on any
    # entity matching (see areas.py::resolve_area_scored()'s docstring).
    area_name: str | None = None


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
class TemporalExpression:
    """A time-related modifier attached to an otherwise-normal on/off command
    - HomeIntent plan V4.7, "Temporal Expressions": "in fünf Minuten" (delay),
    "für eine Stunde" (duration), "morgen früh"/"heute Abend" (relative_time,
    day + day-part), "um 20 Uhr" (absolute_time).

    Per the plan's own scoping ("Zunächst nur parsen und validieren -
    tatsächliche HA-Ausführung erst in einer späteren Execution-Schicht"),
    this is captured for observability only: parsers.py's TemporalParser
    still builds the exact same HassTurnOn/HassTurnOff ``ServiceCallPlan`` an
    equivalent plain "mach {name} an/aus" would - this is only stashed in
    ``SemanticFrame.parameters["temporal"]``, no scheduling/delay is actually
    performed yet. Same "record but don't act" precedent as ``Comparison``'s
    setpoint-synonym half (V4.6).

    ``kind`` is one of "delay"/"duration"/"relative_time"/"absolute_time".
    ``minutes`` carries the delay/duration length (an "X Stunden" phrasing is
    already converted to minutes here). ``relative`` carries a fixed keyword
    ("tomorrow_morning"/"today_evening"/"tomorrow_evening"/"today_morning")
    for relative_time - the 2x2 cross product of the plan's own "morgen"/
    "heute" x "früh"/"Abend" examples, nothing invented beyond that. ``hour``
    carries the 0-23 clock hour for absolute_time. Exactly one of
    minutes/relative/hour is set, matching ``kind``.
    """

    kind: str
    minutes: int | None = None
    relative: str | None = None
    hour: int | None = None


@dataclass(frozen=True)
class SemanticFrame:
    intent: str
    target: TargetReference | None
    area: AreaReference | None
    quantifier: Quantifier | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    source_text: str = ""
