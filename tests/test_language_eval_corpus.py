"""Data-driven regression gate for multi-turn German understanding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.context import ConversationContext
from ha_nlu.nlu.dialog_focus import derive_dialog_focus
from ha_nlu.nlu.semantic_utterance import SpeechAct, analyse_utterance
from test_language_understanding_expansion import ENTITIES


CASES = json.loads(
    (Path(__file__).parent / "eval" / "dialog_cases.json").read_text(encoding="utf-8")
)

EVAL_ENTITIES = ENTITIES + [
    EntitySnapshot(
        "media_player.atlas", "Radio Atlas", "media_player", "playing",
        area_id="wohnzimmer", area_name="Wohnzimmer", floor_id="eg",
        floor_name="Erdgeschoss", floor_level=0,
    ),
    EntitySnapshot(
        "media_player.birke", "Radio Birke", "media_player", "paused",
        area_id="kueche", area_name="Küche", floor_id="eg",
        floor_name="Erdgeschoss", floor_level=0,
    ),
    EntitySnapshot(
        "vacuum.atlas", "Saugroboter Atlas", "vacuum", "cleaning",
        area_id="buero", area_name="Büro",
    ),
    EntitySnapshot(
        "binary_sensor.bad_fenster", "Badezimmerfenster", "binary_sensor", "on",
        area_id="bad", area_name="Badezimmer", device_class="window",
    ),
]


def _route(engine, utterance, context):
    if context is not None:
        for matcher in (
            lambda: engine.match_correction_followup(utterance, EVAL_ENTITIES, context),
            lambda: engine.match_followup(utterance, context),
            lambda: engine.match_contextual_property_followup(utterance, EVAL_ENTITIES, context),
            lambda: engine.match_reference(utterance, EVAL_ENTITIES, context),
            lambda: engine.match_query_followup(utterance, EVAL_ENTITIES, context),
            lambda: engine.match_command_followup(utterance, EVAL_ENTITIES, context),
        ):
            result = matcher()
            if result is not None:
                return result
    return engine.match(utterance, EVAL_ENTITIES)


def _new_context(result):
    if result is None:
        return None
    command = getattr(result, "command", None)
    if command is not None:
        return ConversationContext(
            last_command=command,
            last_entities=tuple(command.entities),
            last_area=command.area,
            pending_clarification=None,
            focus=derive_dialog_focus(command),
            last_explanation=getattr(result, "explanation_text", None),
        )
    context_entities = tuple(getattr(result, "context_entities", ()))
    if context_entities:
        return ConversationContext(
            last_command=None,
            last_entities=context_entities,
            last_area=None,
            pending_clarification=None,
            last_query_predicate=getattr(result, "context_predicate", None),
            last_explanation=getattr(result, "explanation_text", None),
        )
    return None


def _assert_expectation(result, expected, *, utterance: str, case_id: str):
    label = f"{case_id}: {utterance}"
    if "speech_act" in expected:
        assert analyse_utterance(utterance).speech_act is SpeechAct[
            expected["speech_act"]
        ], label
    if expected.get("match") is False:
        assert result is None, label
        return
    assert result is not None, label
    plan = getattr(result, "plan", None)
    command = getattr(result, "command", None)
    if expected.get("action") is False:
        assert plan is None, label
    if expected.get("action") is True:
        assert plan is not None, label
    if "intent" in expected:
        assert command is not None and command.intent == expected["intent"], label
    if "response_contains" in expected:
        assert expected["response_contains"] in result.response_text, label
    if "response_not_contains" in expected:
        assert expected["response_not_contains"] not in result.response_text, label
    if "domain" in expected:
        assert plan is not None and plan.domain == expected["domain"], label
    if "service" in expected:
        assert plan is not None and plan.service == expected["service"], label
    if "entity_id" in expected:
        assert plan is not None and plan.entity_id == expected["entity_id"], label
    if "data" in expected:
        assert plan is not None and plan.data == expected["data"], label


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_language_eval_case(engine, case):
    context = None
    result = None
    turn_expectations = case.get("turn_expect", ())
    for index, utterance in enumerate(case["turns"]):
        result = _route(engine, utterance, context)
        if index < len(turn_expectations):
            _assert_expectation(
                result,
                turn_expectations[index],
                utterance=utterance,
                case_id=case["id"],
            )
        next_context = _new_context(result)
        if next_context is not None:
            context = next_context

    _assert_expectation(
        result, case["expect"], utterance=case["turns"][-1], case_id=case["id"]
    )


def test_eval_corpus_has_zero_unsafe_false_actions(engine):
    """Safety release gate: negative cases may never create a service plan."""
    for case in CASES:
        if case["expect"].get("action") is not False:
            continue
        context = None
        result = None
        for utterance in case["turns"]:
            result = _route(engine, utterance, context)
            next_context = _new_context(result)
            if next_context is not None:
                context = next_context
        assert result is None or result.plan is None, case["id"]


def test_eval_corpus_is_structurally_representative():
    ids = [case["id"] for case in CASES]
    assert len(ids) == len(set(ids))
    assert len(CASES) >= 40
    dimensions = {
        dimension for case in CASES for dimension in case.get("dimensions", ())
    }
    assert {
        "command", "query", "safety", "dialog", "reference",
        "negation", "group", "time", "ambiguity",
    } <= dimensions
