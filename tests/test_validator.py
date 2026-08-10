"""Phase 11 (v2 plan): validate_command() checks a SemanticCommand against
the 9 ValidationError classes. Two groups of tests:

- Real matches from the engine (via the existing fixtures) must always
  validate clean (``None``) - the current parsers already self-police, so
  this is a regression check that the validator doesn't reject anything
  legitimate.
- Hand-built SemanticCommand objects exercise each error class directly,
  since the current parsers never actually construct an invalid one (see
  nlu/validator.py's module docstring for why the validator exists anyway)."""

from __future__ import annotations

from ha_nlu.areas import AreaSnapshot
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.command import SemanticCommand
from ha_nlu.nlu.frame import AreaReference, Quantifier, SemanticFrame, TargetReference
from ha_nlu.nlu.validator import ValidationError, validate_command

LIGHT_WITH_BRIGHTNESS = EntitySnapshot(
    "light.a", "Lampe A", "light", "off", capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"})
)
LIGHT_WITHOUT_BRIGHTNESS = EntitySnapshot(
    "light.b", "Lampe B", "light", "off", capabilities=frozenset({"TURN_ON", "TURN_OFF"})
)
COVER = EntitySnapshot("cover.a", "Rolllade A", "cover", "closed", capabilities=frozenset({"POSITION"}))


def _frame(**kwargs) -> SemanticFrame:
    kwargs.setdefault("intent", "HassTurnOn")
    kwargs.setdefault("target", TargetReference(text="x"))
    kwargs.setdefault("area", None)
    return SemanticFrame(**kwargs)


def _command(**kwargs) -> SemanticCommand:
    frame = kwargs.pop("source_frame", None) or _frame()
    kwargs.setdefault("intent", frame.intent)
    kwargs.setdefault("entities", (LIGHT_WITH_BRIGHTNESS,))
    kwargs.setdefault("area", None)
    kwargs.setdefault("parameters", {})
    return SemanticCommand(source_frame=frame, **kwargs)


# --- real matches must always validate clean ---------------------------


def test_single_match_validates_clean(engine, entities):
    result = engine.match("Mach Treppenlicht an", entities)
    assert validate_command(result.command) is None


def test_percentage_match_validates_clean(engine):
    # The shared ``entities`` fixture predates Phase 9 (Capability System)
    # and carries no capabilities (hass_entities.py is the only thing that
    # populates them, from real HA attributes) - build a dedicated light
    # here so this test reflects what a real dimmable light looks like.
    dimmable_light = EntitySnapshot(
        "light.treppen_licht_gruppe", "Treppenlicht", "light", "off",
        capabilities=frozenset({"TURN_ON", "TURN_OFF", "BRIGHTNESS"}),
    )
    result = engine.match("mach das Treppenlicht auf 50 Prozent", [dimmable_light])
    assert validate_command(result.command) is None


def test_quantifier_both_match_validates_clean(engine, quantifier_entities):
    result = engine.match("Fahre beide Rollladen im Poleraum hoch", quantifier_entities)
    assert validate_command(result.command) is None


def test_quantifier_all_match_validates_clean(engine, quantifier_entities):
    result = engine.match("fahre alle Rolladen hoch", quantifier_entities)
    assert validate_command(result.command) is None


def test_query_match_validates_clean(engine, sensor_entities):
    result = engine.match("wie hoch ist die Außentemperatur", sensor_entities)
    assert validate_command(result.command) is None


# --- synthetic commands, one per error class ----------------------------


def test_unknown_intent():
    command = _command(source_frame=_frame(intent="HassDoesNotExist"), intent="HassDoesNotExist")
    assert validate_command(command) is ValidationError.UNKNOWN_INTENT


def test_entity_not_found():
    command = _command(entities=())
    assert validate_command(command) is ValidationError.ENTITY_NOT_FOUND


def test_ambiguous_entity():
    # No quantifier, but more than one resolved entity - an invariant a real
    # parser never produces (resolve_entity returns NOT_FOUND for a true
    # ambiguity before a frame is even built), but a possible one from an
    # untrusted future caller.
    command = _command(entities=(LIGHT_WITH_BRIGHTNESS, LIGHT_WITHOUT_BRIGHTNESS))
    assert validate_command(command) is ValidationError.AMBIGUOUS_ENTITY


def test_area_not_found():
    frame = _frame(area=AreaReference(text="Poleraum", area_id="poleraum"))
    command = _command(source_frame=frame, area=None)
    assert validate_command(command) is ValidationError.AREA_NOT_FOUND


def test_invalid_domain():
    # HassTurnOn only allows light/switch/fan - a cover entity slipping
    # through would be an INVALID_DOMAIN violation.
    command = _command(entities=(COVER,))
    assert validate_command(command) is ValidationError.INVALID_DOMAIN


def test_unsupported_capability():
    frame = _frame(intent="HassSetPercentage")
    command = _command(
        source_frame=frame, entities=(LIGHT_WITHOUT_BRIGHTNESS,), parameters={"percent": 50}
    )
    assert validate_command(command) is ValidationError.UNSUPPORTED_CAPABILITY


def test_missing_parameter():
    frame = _frame(intent="HassSetPercentage")
    command = _command(source_frame=frame, entities=(LIGHT_WITH_BRIGHTNESS,), parameters={})
    assert validate_command(command) is ValidationError.MISSING_PARAMETER


def test_invalid_parameter_out_of_range():
    frame = _frame(intent="HassSetPercentage")
    command = _command(
        source_frame=frame, entities=(LIGHT_WITH_BRIGHTNESS,), parameters={"percent": 150}
    )
    assert validate_command(command) is ValidationError.INVALID_PARAMETER


def test_invalid_parameter_wrong_type():
    frame = _frame(intent="HassSetPercentage")
    command = _command(
        source_frame=frame, entities=(LIGHT_WITH_BRIGHTNESS,), parameters={"percent": "fifty"}
    )
    assert validate_command(command) is ValidationError.INVALID_PARAMETER


def test_invalid_quantifier_both_with_wrong_count():
    frame = _frame(intent="HassOpenCover", quantifier=Quantifier(kind="both"))
    command = _command(source_frame=frame, entities=(COVER,))
    assert validate_command(command) is ValidationError.INVALID_QUANTIFIER


def test_valid_percentage_command_is_none():
    frame = _frame(intent="HassSetPercentage")
    command = _command(
        source_frame=frame, entities=(LIGHT_WITH_BRIGHTNESS,), parameters={"percent": 50}
    )
    assert validate_command(command) is None


def test_valid_quantifier_both_with_area_is_none():
    frame = _frame(
        intent="HassOpenCover",
        quantifier=Quantifier(kind="both"),
        area=AreaReference(text="Poleraum", area_id="poleraum"),
    )
    command = _command(
        source_frame=frame,
        entities=(COVER, COVER),
        area=AreaSnapshot(area_id="poleraum", name="Poleraum"),
    )
    assert validate_command(command) is None
