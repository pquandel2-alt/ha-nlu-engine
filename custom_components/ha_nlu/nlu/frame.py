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
    """A structured quantifier reference ("alle"/"beide[n/r]") - v2 plan
    Phase 8, generalizing the raw "all"/"both" string previously stashed in
    ``SemanticFrame.parameters``. ``value`` is reserved for quantifier kinds
    the v3 plan adds later (e.g. "die drei Lampen" -> kind="count", value=3);
    "all"/"both" always carry ``value=None`` today.
    """

    kind: str
    value: int | None = None


@dataclass(frozen=True)
class SemanticFrame:
    intent: str
    target: TargetReference | None
    area: AreaReference | None
    quantifier: Quantifier | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    source_text: str = ""
