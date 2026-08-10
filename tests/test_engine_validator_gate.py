"""Phase 12 (v2 plan): engine.py wires validate_command() into
_build_match_result() before a ServiceCallPlan is ever built. The three
existing parsers never produce a ParseResult that fails validation (that's
the whole reason the Validator was built ahead of a real-world trigger -
see nlu/validator.py's module docstring), so this test builds one by hand
and calls the (static) _build_match_result() directly, proving the gate is
actually wired in rather than just unit-tested in isolation."""

from __future__ import annotations

from ha_nlu.engine import NluEngine
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.frame import SemanticFrame, TargetReference
from ha_nlu.nlu.parser import ParseResult

LIGHT_WITHOUT_BRIGHTNESS = EntitySnapshot("light.a", "Lampe A", "light", "off")


def test_unsupported_capability_command_is_rejected_by_the_engine():
    frame = SemanticFrame(
        intent="HassSetPercentage",
        target=TargetReference(text="Lampe A", entity_id="light.a", domain="light"),
        area=None,
        parameters={"percent": 50},
    )
    result = ParseResult(frame=frame, resolved_entities=[LIGHT_WITHOUT_BRIGHTNESS])
    assert NluEngine._build_match_result(result) is None
