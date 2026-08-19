"""Integration Wave Migration Step 3/5: direct unit tests for
``NluEngine.match_automation()`` itself - the regex pre-check, the
sentence-split gate, propagation of each sub-parser's own "never guess"
``None``, and the happy-path -> ``validate_automation()`` wiring. Complements
``tests/test_integration_wave_e2e.py``, which exercises the same method
through the real conversation entity instead.

Conditions Wave (2026-08-19): also covers the Trigger/Condition split
fallback (``NluEngine._split_trigger_condition()``) end-to-end through
``match_automation()`` itself - not just ``split_on_top_level_and()`` in
isolation (see ``tests/test_automation_condition_parser.py`` for that), the
same "unit tests plus real pipeline tests" split every other automation
sub-feature in this repo already follows.
"""

from __future__ import annotations

from ha_nlu.engine import AutomationMatchResult
from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.automation_validator import AutomationValidationError
from ha_nlu.nlu.condition_model import ConditionType, LogicalOperator

KUECHE_FENSTER = EntitySnapshot(
    "binary_sensor.kueche_fenster", "Küchenfenster", "binary_sensor", "off",
    area_id="kueche", area_name="Küche", device_class="window",
)
KUECHE_LICHT = EntitySnapshot(
    "light.kueche_licht", "Küchenlicht", "light", "off",
    area_id="kueche", area_name="Küche",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
BUERO_FENSTER_1 = EntitySnapshot(
    "binary_sensor.buero_fenster_1", "Bürofenster", "binary_sensor", "off",
    area_id="buero_1", area_name="Büro 1", device_class="window",
)
BUERO_FENSTER_2 = EntitySnapshot(
    "binary_sensor.buero_fenster_2", "Bürofenster", "binary_sensor", "off",
    area_id="buero_2", area_name="Büro 2", device_class="window",
)
WOHNZIMMER_HEIZUNG = EntitySnapshot(
    "climate.heizung_wohnzimmer", "Heizung Wohnzimmer", "climate", "heat",
    area_id="wohnzimmer", area_name="Wohnzimmer",
    capabilities=frozenset({"TURN_ON", "TURN_OFF", "TEMPERATURE"}),
    attributes={"temperature": 20},
)

ENTITIES = [KUECHE_FENSTER, KUECHE_LICHT, BUERO_FENSTER_1, BUERO_FENSTER_2, WOHNZIMMER_HEIZUNG]


def test_non_automation_sentence_is_rejected_by_the_regex_gate(engine):
    assert engine.match_automation("Schalte das Küchenlicht ein.", ENTITIES) is None


def test_automation_keyword_without_a_comma_returns_none(engine):
    # No trigger/action split point - never guess where the sentence breaks.
    assert engine.match_automation("Wenn das Küchenfenster geöffnet wird schalte das Küchenlicht ein.", ENTITIES) is None


def test_valid_trigger_and_action_produces_a_validated_automation_model(engine):
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein.", ENTITIES
    )
    assert isinstance(result, AutomationMatchResult)
    assert result.validation_error is None
    assert len(result.model.triggers) == 1
    assert len(result.model.actions) == 1
    assert "AutomationModel" in result.response_text


def test_ambiguous_trigger_target_returns_none_never_guesses(engine):
    # Two entities named "Bürofenster" in different areas, no area named in
    # the sentence - AutomationTriggerParser._build_named_target() refuses.
    result = engine.match_automation(
        "Wenn das Bürofenster geöffnet wird, schalte das Küchenlicht ein.", ENTITIES
    )
    assert result is None


def test_unresolvable_action_target_returns_none_never_guesses(engine):
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird, schalte das Kellerlicht ein.", ENTITIES
    )
    assert result is None


def test_structurally_invalid_automation_surfaces_its_validation_error_not_silently(engine, monkeypatch):
    # Every value match_automation()'s two sub-parsers can currently produce
    # is already grammar-constrained to be valid (temperature 5-30, percent
    # 0-100, weekdays/times from fixed slot lists, targets refused rather
    # than built invalid - Regel 4) - so validate_automation() can't
    # actually be made to fail through a real sentence today. This monkey-
    # patches it to prove match_automation()'s *formatting* of a non-None
    # validation_error onto response_text works, independent of whether
    # today's grammars can reach that branch.
    monkeypatch.setattr(
        "ha_nlu.engine.validate_automation",
        lambda model: AutomationValidationError.INVALID_PARAMETER,
    )
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein.", ENTITIES
    )
    assert isinstance(result, AutomationMatchResult)
    assert result.validation_error is AutomationValidationError.INVALID_PARAMETER
    assert "validation_error: INVALID_PARAMETER" in result.response_text


def test_never_produces_a_service_call_plan():
    """AutomationMatchResult has no plan/ServiceCallPlan field at all -
    structurally impossible to reach hass.services.async_call() from this
    path (see AutomationMatchResult's own docstring)."""
    assert not hasattr(AutomationMatchResult, "plan")


# ============================================================================
# Conditions Wave (2026-08-19): "wenn Trigger und Condition, Action" through
# the real match_automation() Trigger/Condition split fallback.
# ============================================================================

WOHNZIMMER_LICHT = EntitySnapshot(
    "light.wohnzimmer_licht", "Wohnzimmerlicht", "light", "off",
    area_id="wohnzimmer", area_name="Wohnzimmer",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)

CONDITIONS_ENTITIES = ENTITIES + [WOHNZIMMER_LICHT]


def test_trigger_and_action_without_a_condition_still_matches_unchanged(engine):
    # Same sentence test_valid_trigger_and_action_produces_a_validated_automation_model
    # already covers - repeated here to pin that adding the Condition
    # fallback did not change the primary (no "und") path at all.
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein.", CONDITIONS_ENTITIES
    )
    assert isinstance(result, AutomationMatchResult)
    assert result.model.conditions == ()
    assert result.validation_error is None


def test_trigger_and_action_with_a_multi_entity_und_still_matches_as_a_single_trigger(engine):
    # "Tür und Fenster" is a single Trigger, not a Trigger+Condition split -
    # the full-text Trigger parse must succeed first and win, so the split
    # fallback never even runs (see match_automation()'s own docstring).
    result = engine.match_automation(
        "Wenn das Küchenfenster und das Bürofenster geöffnet werden, schalte das Küchenlicht ein.",
        CONDITIONS_ENTITIES,
    )
    assert result is None  # Bürofenster is ambiguous across two areas - never guessed, not a regression


def test_trigger_and_numeric_condition_and_action(engine):
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird und die Heizung Wohnzimmer über 22 Grad liegt, "
        "schalte das Küchenlicht ein.",
        CONDITIONS_ENTITIES,
    )
    assert isinstance(result, AutomationMatchResult)
    assert result.validation_error is None
    assert len(result.model.conditions) == 1
    assert result.model.conditions[0].condition.type is ConditionType.NUMERIC


def test_trigger_and_time_condition_and_action(engine):
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird und es nach 18 Uhr ist, schalte das Küchenlicht ein.",
        CONDITIONS_ENTITIES,
    )
    assert isinstance(result, AutomationMatchResult)
    assert result.validation_error is None
    assert len(result.model.conditions) == 1
    assert result.model.conditions[0].condition.type is ConditionType.TIME


def test_trigger_and_presence_condition_and_action(engine):
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird und niemand zuhause ist, schalte das Küchenlicht ein.",
        CONDITIONS_ENTITIES,
    )
    assert isinstance(result, AutomationMatchResult)
    assert result.validation_error is None
    assert len(result.model.conditions) == 1
    assert result.model.conditions[0].operator is LogicalOperator.NOT


def test_trigger_and_weekday_condition_and_action(engine):
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird und Samstag ist, schalte das Küchenlicht ein.",
        CONDITIONS_ENTITIES,
    )
    assert isinstance(result, AutomationMatchResult)
    assert result.validation_error is None
    assert len(result.model.conditions) == 1
    assert result.model.conditions[0].condition.type is ConditionType.WEEKDAY


def test_ambiguous_condition_target_returns_none_never_guesses(engine):
    # Two entities named "Bürofenster" in different areas - the Condition
    # half must refuse exactly like the Trigger half already does elsewhere
    # in this file, not fall back to a guess.
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird und das Bürofenster offen ist, schalte das Küchenlicht ein.",
        CONDITIONS_ENTITIES,
    )
    assert result is None


def test_unresolvable_condition_target_returns_none_never_guesses(engine):
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird und das Kellerlicht an ist, schalte das Küchenlicht ein.",
        CONDITIONS_ENTITIES,
    )
    assert result is None


def test_condition_result_is_validated_the_same_way_as_triggers_and_actions(engine, monkeypatch):
    monkeypatch.setattr(
        "ha_nlu.engine.validate_automation",
        lambda model: AutomationValidationError.INVALID_LOGIC,
    )
    result = engine.match_automation(
        "Wenn das Küchenfenster geöffnet wird und es nach 18 Uhr ist, schalte das Küchenlicht ein.",
        CONDITIONS_ENTITIES,
    )
    assert isinstance(result, AutomationMatchResult)
    assert result.validation_error is AutomationValidationError.INVALID_LOGIC
    assert "validation_error: INVALID_LOGIC" in result.response_text


def test_plain_command_is_unaffected_by_the_condition_fallback(engine):
    assert engine.match_automation("Schalte das Wohnzimmerlicht ein.", CONDITIONS_ENTITIES) is None
