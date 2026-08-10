"""SemanticCommand (v2 plan Phase 10): the fully-resolved counterpart to a
``SemanticFrame`` - a frame captures *what the user said* (still just text
references), a command captures *what will actually happen* (real resolved
``EntitySnapshot``/``AreaSnapshot`` objects). Building one is purely
mechanical (an ``IntentParser`` has already done all resolution by the time
its ``ParseResult`` exists) - this module only assembles the result, no new
matching/resolution logic lives here.

Kept free of Home Assistant/hassil imports (same boundary as nlu/frame.py):
``EntitySnapshot``/``AreaSnapshot`` are already hass-free by this point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ..areas import AreaSnapshot
from ..entities import EntitySnapshot
from .frame import SemanticFrame
from .parser import ParseResult


@dataclass(frozen=True)
class SemanticCommand:
    intent: str
    entities: tuple[EntitySnapshot, ...]
    area: AreaSnapshot | None
    parameters: Mapping[str, Any]
    source_frame: SemanticFrame


def _resolve_area_snapshot(frame: SemanticFrame, entities: tuple[EntitySnapshot, ...]) -> AreaSnapshot | None:
    """The command's area as a full ``AreaSnapshot`` (id + canonical name).

    Built from the already-resolved entities' own ``area_id``/``area_name``
    (the same source ``areas.py`` itself uses) rather than the frame's
    ``area.text`` - that's the user's spoken wording, not necessarily the
    registry's canonical name.
    """
    if frame.area is None or frame.area.area_id is None:
        return None
    for entity in entities:
        if entity.area_id == frame.area.area_id and entity.area_name is not None:
            return AreaSnapshot(area_id=entity.area_id, name=entity.area_name)
    return None


def build_semantic_command(result: ParseResult) -> SemanticCommand:
    frame = result.frame
    entities = tuple(result.resolved_entities)
    return SemanticCommand(
        intent=frame.intent,
        entities=entities,
        area=_resolve_area_snapshot(frame, entities),
        parameters=frame.parameters,
        source_frame=frame,
    )
