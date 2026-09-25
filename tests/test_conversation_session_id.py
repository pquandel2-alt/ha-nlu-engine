"""Turns without a caller-supplied ``conversation_id`` must stay isolated.

The REST API and ``conversation.process`` may call the agent with
``conversation_id=None``. Home Assistant still opens a chat session with its
own id (``chat_log.conversation_id``). Without falling back to that id every
such caller shared one dialog state, so an open question from one caller
captured the next command of another.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import homeintent.conversation as ha_conversation  # noqa: E402
from homeintent.conversation import NluConversationEntity  # noqa: E402
from homeintent.entities import EntitySnapshot  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

HOF_LATERNE = EntitySnapshot(
    "light.hof_laterne", "Hof Laterne", "light", "off",
    area_id="hof", area_name="Hof",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
TURM_LATERNE = EntitySnapshot(
    "light.turm_laterne", "Turm Laterne", "light", "off",
    area_id="turm", area_name="Turm",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)


def _make_entity(monkeypatch, tmp_path: Path) -> NluConversationEntity:
    entity = NluConversationEntity(ConfigEntry())
    entity.hass = HomeAssistant()
    entity.hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    monkeypatch.setattr(
        ha_conversation,
        "build_entity_snapshots",
        lambda hass, entry: [HOF_LATERNE, TURM_LATERNE],
    )
    return entity


def _run_without_id(entity: NluConversationEntity, text: str, session_id: str):
    user_input = ConversationInput(text=text, conversation_id=None)  # type: ignore[arg-type]
    chat_log = SimpleNamespace(conversation_id=session_id)
    return asyncio.run(entity._async_handle_message(user_input, chat_log=chat_log))


def _speech(result) -> str:
    return result.response.speech or ""


def test_turn_without_conversation_id_uses_the_chat_session_id(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)

    question = _run_without_id(entity, "Schalte die Laterne ein.", "session-a")

    assert result_id(question) == "session-a"
    assert "Welches meinst du" in _speech(question)
    assert question.continue_conversation is True


def test_open_question_of_one_session_does_not_capture_another(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    _run_without_id(entity, "Schalte die Laterne ein.", "session-a")

    foreign = _run_without_id(entity, "Die im Turm.", "session-b")

    assert result_id(foreign) == "session-b"
    entity.hass.services.async_call.assert_not_awaited()

    answered = _run_without_id(entity, "Die im Turm.", "session-a")

    assert "Turm Laterne" in _speech(answered)
    entity.hass.services.async_call.assert_awaited_once()
    assert entity.hass.services.async_call.await_args.args[2] == {
        "entity_id": "light.turm_laterne"
    }


def test_explicit_conversation_id_still_wins_over_the_session(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    user_input = ConversationInput(text="Schalte die Laterne ein.", conversation_id="caller-id")

    result = asyncio.run(
        entity._async_handle_message(
            user_input, chat_log=SimpleNamespace(conversation_id="session-x")
        )
    )

    assert result_id(result) == "caller-id"


def result_id(result) -> str | None:
    return result.conversation_id
