"""QueryCommand/QueryResult type system (HomeIntent v4.2.1 plan, Sections
6-11): the 3-stage separation the plan's Section 12 asks for -

    Parser -> QueryCommand
    QueryCommand -> QueryExecutor -> QueryResult   (Phase 5)
    QueryResult -> ResponseGenerator -> text        (Phase 6)

Phase 4 only introduces these types. ``StateQueryParser`` (parsers.py) keeps
building its existing ``frame.parameters``-based results until Phase 7
migrates it onto this infrastructure non-destructively (Section 13, "keine
Big-Bang-Refactorisierung") - nothing here is wired into ``engine.py``/
``parsers.py`` yet, so existing behavior is completely unaffected by this
module's presence.

Field shapes mirror what ``StateQueryParser`` already resolves today (domain,
device_class, area, requested ``SemanticState``, matched entities) - this is
a restructuring of data already flowing through the pipeline, not new
information.

Kept free of Home Assistant/hassil imports, same boundary as ``frame.py``/
``command.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from ..areas import AreaSnapshot
from ..automation_summary import AutomationSummary
from ..devices import DeviceSnapshot
from ..entities import EntitySnapshot
from .semantic_state import SemanticState


class QueryScope(Enum):
    """Cardinality expectation of a query - mirrors the singular/plural split
    ``StateQueryParser``'s own docstring already documents."""

    SINGLE = auto()  # HassCheckState - exactly one entity expected, never guess (Regel 4)
    LIST = auto()  # HassStateQuery "welche ..." - list every matching entity
    COUNT = auto()  # HassStateQuery "wie viele ..." - count matching entities
    EXISTS = auto()  # HassExistsQuery - existence only, no per-entity detail
    ALL = auto()  # "Sind alle Rollläden oben?" - universal state check
    NONE = auto()  # "Ist kein Fenster offen?" - negated existence check
    LOCATIONS = auto()  # "Wo sind Fenster offen?" - unique matching rooms


class QueryTargetKind(Enum):
    """What kind of object a query searches over - ``ENTITY`` (the only kind
    before the WorldModelQuery wave) vs. ``DEVICE`` (HassDeviceQuery, "welche
    Geräte sind im Büro?" - answered from the WorldModel's device list, not
    an entity/state filter) vs. ``AUTOMATION`` (HassAutomationQuery/
    HassAutomationWhyQuery, V5.29 - answered from ``automations.yaml`` plus
    its metadata sidecar, not an entity/state filter either). Cut so a
    future further value could be added without restructuring
    ``QueryExecutor``/``ResponseGenerator`` - the ``DEVICE`` case already
    proved this extension point out before ``AUTOMATION`` reused it.
    """

    ENTITY = auto()
    DEVICE = auto()
    AUTOMATION = auto()


@dataclass(frozen=True)
class QueryTarget:
    """What a query searches over, before any state filter is applied.

    ``entity_id`` is set for ``QueryScope.SINGLE`` (HassCheckState's resolved
    ``{name}``) and, optionally, for ``QueryTargetKind.AUTOMATION`` targets
    (HassAutomationQuery/HassAutomationWhyQuery's resolved ``{name}`` - "was
    schaltet X?"/"warum geht X an?" - filters to automations referencing
    that entity; unset means "list every automation", V5.29).
    ``device_class`` narrows ``domain`` further, same "domain:device_class"
    split ``StateQueryParser._device_class_candidates`` already performs.
    ``domain`` is ``None`` for ``QueryTargetKind.DEVICE``/``AUTOMATION``
    targets - both are cross-domain, there is no single domain to name.
    """

    domain: str | None = None
    device_class: str | None = None
    area: AreaSnapshot | None = None
    floor_id: str | None = None
    entity_id: str | None = None
    kind: QueryTargetKind = QueryTargetKind.ENTITY


@dataclass(frozen=True)
class QueryFilter:
    """The state condition candidate entities must satisfy.

    ``state`` is ``None`` only for HassExistsQuery's bare-existence form
    ("gibt es Fenster?", no {state}/{state_adj} word at all) - every match
    passes, cardinality alone is the answer.
    """

    state: SemanticState | None = None


@dataclass(frozen=True)
class QueryCommand:
    """The fully-resolved counterpart to a query ``SemanticFrame`` - mirrors
    ``nlu/command.py``'s ``SemanticCommand`` split for ordinary commands."""

    intent: str
    scope: QueryScope
    target: QueryTarget
    filter: QueryFilter


class QueryResultStatus(Enum):
    """Distinguishes "not found" from "found but nothing matched" (Sections
    19-20) - collapsed into a single ``None``/miss in today's pre-Phase-7
    ``StateQueryParser``/``QUERY_INTENTS`` pipeline."""

    MATCHED = auto()  # 1+ entities passed the filter (or, for EXISTS, existence confirmed)
    EMPTY = auto()  # target resolved fine, 0 entities passed the filter - a normal answer, not an error
    TARGET_NOT_FOUND = auto()  # the named {name}/{area} itself didn't resolve to anything known
    AMBIGUOUS = auto()  # SINGLE scope, 2+ candidates, no quantifier - never guess (Regel 4)


@dataclass(frozen=True)
class QueryResult:
    status: QueryResultStatus
    entities: tuple[EntitySnapshot, ...] = ()
    devices: tuple[DeviceSnapshot, ...] = ()
    automations: tuple[AutomationSummary, ...] = ()
    command: QueryCommand | None = None
