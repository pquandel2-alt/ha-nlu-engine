from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import ha_nlu.conversation as ha_conversation  # noqa: E402
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from ha_nlu.productivity import (  # noqa: E402
    TodoRequest,
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


def test_todo_add_understands_due_date_description_and_portable_priority():
    result = parse_productivity_request(
        "Füge Bericht bis morgen mit Priorität hoch mit der Beschreibung Entwurf prüfen zur Arbeitsliste hinzu",
        [SHOPPING, WORK], datetime(2026, 8, 24, 12),
    )
    assert result is not None
    assert result.entity_id == WORK.entity_id
    assert result.due_date == "2026-08-25"
    assert result.priority == "hoch"
    assert result.description == "Entwurf prüfen"


def test_todo_move_extracts_source_destination_and_payload():
    result = parse_productivity_request(
        "Verschiebe Milch von der Einkaufsliste auf die Arbeitsliste",
        [SHOPPING, WORK],
    )
    assert result is not None
    assert result.operation is TodoOperation.MOVE
    assert result.entity_id == SHOPPING.entity_id
    assert result.destination_entity_id == WORK.entity_id
    assert result.items == ("Milch",)


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


def test_cross_domain_delete_ambiguity_never_calls_a_service(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING])

    result = _run(
        agent,
        "Lösche den Eintrag Termin aus der Einkaufsliste im Kalender",
        "cross-domain",
    )

    assert "Kalender oder eine Liste" in result.response.speech
    agent.hass.services.async_call.assert_not_awaited()


def test_ambiguous_list_is_selected_in_followup(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING, WORK])
    question = _run(agent, "Füge Milch und Brot zur Liste hinzu", "list-select")
    answer = _run(agent, "die Einkaufsliste", "list-select")
    assert "mehrere passende Listen" in question.response.speech
    assert "1. Einkaufsliste" in question.response.speech
    assert "2. Arbeitsliste" in question.response.speech
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


def test_clear_completed_requires_confirmation_and_executes_after_yes(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING])
    agent.hass.services.async_call = AsyncMock(side_effect=[
        {SHOPPING.entity_id: {"items": [
            {"uid": "done-1", "summary": "Brot", "status": "completed"},
        ]}},
        None,
    ])

    question = _run(
        agent, "Alle erledigten Einträge aus der Einkaufsliste löschen", "clear"
    )
    unclear = _run(agent, "vielleicht", "clear")
    result = _run(agent, "ja", "clear")

    assert "wirklich" in question.response.speech
    assert unclear.response.speech == "Bitte antworte mit Ja oder Nein."
    assert result.response.speech == "1 erledigte Einträge wurden gelöscht."
    assert agent.hass.services.async_call.await_count == 2


def test_clear_completed_can_be_declined_without_write(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING])

    _run(agent, "Alle erledigten Einträge aus der Einkaufsliste löschen", "decline")
    result = _run(agent, "nein", "decline")

    assert "nicht verändert" in result.response.speech
    agent.hass.services.async_call.assert_not_awaited()


def test_todo_complete_and_remove_resolve_stable_uids(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING])
    items = {SHOPPING.entity_id: {"items": [
        {"uid": "milk-1", "summary": "[Hoch] Milch", "status": "needs_action"},
        {"uid": "bread-1", "summary": "Brot", "status": "needs_action"},
    ]}}
    agent.hass.services.async_call = AsyncMock(side_effect=[items, None, items, None])

    completed = asyncio.run(agent._async_execute_todo(TodoRequest(
        TodoOperation.COMPLETE, items=("Milch",), entity_id=SHOPPING.entity_id
    )))
    removed = asyncio.run(agent._async_execute_todo(TodoRequest(
        TodoOperation.REMOVE, items=("Brot",), entity_id=SHOPPING.entity_id
    )))

    assert completed == "1 Eintrag wurde als erledigt markiert."
    assert removed == "1 Eintrag wurde aus der Liste entfernt."
    assert agent.hass.services.async_call.await_args_list[1].args[2] == {
        "item": "milk-1", "status": "completed"
    }
    assert agent.hass.services.async_call.await_args_list[3].args[2] == {
        "item": "bread-1"
    }


@pytest.mark.parametrize(
    ("items", "spoken", "message"),
    (
        ([], "Milch", "nicht gefunden"),
        ([
            {"uid": "a", "summary": "Milch", "status": "needs_action"},
            {"uid": "b", "summary": "Milch", "status": "needs_action"},
        ], "Milch", "mehrfach vorhanden"),
        ([{"summary": "Milch", "status": "needs_action"}], "Milch", "stabile Eintrags-ID"),
    ),
)
def test_todo_mutation_refuses_unknown_duplicate_or_unstable_items(
    monkeypatch, items, spoken, message
):
    agent = _entity(monkeypatch, [SHOPPING])
    agent.hass.services.async_call = AsyncMock(return_value={
        SHOPPING.entity_id: {"items": items}
    })

    with pytest.raises(ValueError, match=message):
        asyncio.run(agent._async_execute_todo(TodoRequest(
            TodoOperation.REMOVE, items=(spoken,), entity_id=SHOPPING.entity_id
        )))


def test_todo_move_preserves_metadata_then_removes_source(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING, WORK])
    source = {SHOPPING.entity_id: {"items": [{
        "uid": "report-1", "summary": "Bericht", "status": "needs_action",
        "due_date": "2026-09-01", "description": "Prüfen",
    }]}}
    agent.hass.services.async_call = AsyncMock(side_effect=[source, None, None])

    speech = asyncio.run(agent._async_execute_todo(TodoRequest(
        TodoOperation.MOVE,
        items=("Bericht",),
        entity_id=SHOPPING.entity_id,
        destination_entity_id=WORK.entity_id,
    )))

    assert speech == "1 Eintrag wurde verschoben."
    added = agent.hass.services.async_call.await_args_list[1]
    assert added.args[2] == {
        "item": "Bericht", "due_date": "2026-09-01", "description": "Prüfen"
    }
    assert agent.hass.services.async_call.await_args_list[2].args[1] == "remove_item"


def test_todo_move_requires_destination_before_any_service(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING])

    with pytest.raises(ValueError, match="Zielliste"):
        asyncio.run(agent._async_execute_todo(TodoRequest(
            TodoOperation.MOVE, items=("Milch",), entity_id=SHOPPING.entity_id
        )))
    agent.hass.services.async_call.assert_not_awaited()


def test_productivity_service_failure_is_cleanly_reported(monkeypatch):
    agent = _entity(monkeypatch, [SHOPPING])
    agent.hass.services.async_call = AsyncMock(side_effect=RuntimeError("todo down"))

    result = _run(agent, "Füge Milch zur Einkaufsliste hinzu")

    assert "todo down" in result.response.speech
