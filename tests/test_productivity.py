from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import ha_nlu.conversation as ha_conversation  # noqa: E402
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.productivity import (  # noqa: E402
    TimerOperation,
    TodoOperation,
    parse_productivity_request,
    split_todo_items,
)
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


SHOPPING = EntitySnapshot("todo.einkauf", "Einkaufsliste", "todo", "3")
WORK = EntitySnapshot("todo.arbeit", "Arbeitsliste", "todo", "1")
TIMER = EntitySnapshot(
    "timer.kueche", "Küchentimer", "timer", "active",
    attributes={"remaining": "00:04:15"},
)


def _entity(monkeypatch, entities):
    entry = ConfigEntry()
    agent = NluConversationEntity(entry)
    agent.hass = HomeAssistant()
    monkeypatch.setattr(ha_conversation, "build_entity_snapshots", lambda hass, entry: entities)
    return agent


def _run(agent, text, conversation_id="p-1"):
    return asyncio.run(agent._async_handle_message(
        ConversationInput(text=text, conversation_id=conversation_id), chat_log=None
    ))


def test_multiple_spoken_items_are_independent_and_deduplicated():
    assert split_todo_items("Milch, Brot und Butter sowie Milch") == (
        "Milch", "Brot", "Butter"
    )


def test_todo_parser_extracts_operation_target_and_multiple_items():
    result = parse_productivity_request(
        "Füge Milch, Brot und Butter zur Einkaufsliste hinzu", [SHOPPING, WORK]
    )
    assert result is not None
    assert result.operation is TodoOperation.ADD
    assert result.entity_id == SHOPPING.entity_id
    assert result.items == ("Milch", "Brot", "Butter")


def test_todo_word_order_is_not_fixed():
    first = parse_productivity_request(
        "Setze Äpfel und Bananen auf meine Einkaufsliste", [SHOPPING]
    )
    second = parse_productivity_request(
        "Auf die Einkaufsliste schreib bitte Äpfel und Bananen", [SHOPPING]
    )
    assert first is not None and second is not None
    assert first.items == second.items == ("Äpfel", "Bananen")


def test_multi_item_add_executes_one_native_call_per_item(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING])
    result = _run(agent, "Füge Milch, Brot und Eier zur Einkaufsliste hinzu")
    assert result.response.speech.startswith("3 Einträge")
    assert agent.hass.services.async_call.await_count == 3
    for item, call in zip(("Milch", "Brot", "Eier"), agent.hass.services.async_call.await_args_list):
        assert call.args == ("todo", "add_item", {"item": item})
        assert call.kwargs == {
            "target": {"entity_id": SHOPPING.entity_id}, "blocking": True
        }


def test_ambiguous_list_is_selected_in_followup(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING, WORK])
    question = _run(agent, "Füge Milch und Brot zur Liste hinzu", "list-select")
    answer = _run(agent, "die Einkaufsliste", "list-select")
    assert "Welche Liste" in question.response.speech
    assert "2 Einträge" in answer.response.speech
    assert agent.hass.services.async_call.await_count == 2


def test_list_query_uses_get_items_response(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING])
    agent.hass.services.async_call = AsyncMock(return_value={
        SHOPPING.entity_id: {"items": [
            {"summary": "Milch", "status": "needs_action"},
            {"summary": "Brot", "status": "completed"},
        ]}
    })
    result = _run(agent, "Was steht auf meiner Einkaufsliste?")
    assert result.response.speech == "Auf der Liste stehen: Milch."


def test_timer_start_and_change_are_compositional(monkeypatch):
    start = parse_productivity_request(
        "Starte den Küchentimer für fünf Minuten und 30 Sekunden", [TIMER]
    )
    change = parse_productivity_request(
        "Verkürze den Küchentimer um zwei Minuten", [TIMER]
    )
    assert start is not None and start.operation is TimerOperation.START
    assert start.duration_seconds == 330
    assert change is not None and change.operation is TimerOperation.CHANGE
    assert change.change_seconds == -120


def test_timer_service_and_status(monkeypatch):
    agent = _entity(monkeypatch, [TIMER])
    started = _run(agent, "Stelle den Küchentimer auf 5 Minuten", "timer-start")
    assert "5 Minuten" in started.response.speech
    agent.hass.services.async_call.assert_awaited_once_with(
        "timer", "start", {"duration": "00:05:00"},
        target={"entity_id": TIMER.entity_id}, blocking=True,
    )

    agent.hass.services.async_call.reset_mock()
    status = _run(agent, "Wie lange läuft der Küchentimer noch?", "timer-status")
    assert "00:04:15" in status.response.speech
    agent.hass.services.async_call.assert_not_awaited()
