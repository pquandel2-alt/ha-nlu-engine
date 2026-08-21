"""Data-driven regression gate for multi-turn German understanding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ha_nlu.nlu.context import ConversationContext
from ha_nlu.nlu.dialog_focus import derive_dialog_focus
from test_language_understanding_expansion import ENTITIES


CASES = json.loads(
    (Path(__file__).parent / "eval" / "dialog_cases.json").read_text(encoding="utf-8")
)


def _route(engine, utterance, context):
    if context is not None:
        for matcher in (
            lambda: engine.match_correction_followup(utterance, ENTITIES, context),
            lambda: engine.match_followup(utterance, context),
            lambda: engine.match_contextual_property_followup(utterance, ENTITIES, context),
            lambda: engine.match_reference(utterance, ENTITIES, context),
            lambda: engine.match_query_followup(utterance, ENTITIES, context),
            lambda: engine.match_command_followup(utterance, ENTITIES, context),
        ):
            result = matcher()
            if result is not None:
                return result
    return engine.match(utterance, ENTITIES)


def _new_context(result):
    if result is None or getattr(result, "command", None) is None:
        return None
    command = result.command
    return ConversationContext(
        last_command=command,
        last_entities=tuple(command.entities),
        last_area=command.area,
        pending_clarification=None,
        focus=derive_dialog_focus(command),
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_language_eval_case(engine, case):
    context = None
    result = None
    for utterance in case["turns"]:
        result = _route(engine, utterance, context)
        next_context = _new_context(result)
        if next_context is not None:
            context = next_context

    expected = case["expect"]
    if expected.get("match") is False:
        assert result is None
        return
    assert result is not None
    plan = getattr(result, "plan", None)
    command = getattr(result, "command", None)
    if expected.get("action") is False:
        assert plan is None
    if "intent" in expected:
        assert command is not None and command.intent == expected["intent"]
    if "response_contains" in expected:
        assert expected["response_contains"] in result.response_text
    if "domain" in expected:
        assert plan is not None and plan.domain == expected["domain"]
    if "service" in expected:
        assert plan is not None and plan.service == expected["service"]
    if "entity_id" in expected:
        assert plan is not None and plan.entity_id == expected["entity_id"]
    if "data" in expected:
        assert plan is not None and plan.data == expected["data"]


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
