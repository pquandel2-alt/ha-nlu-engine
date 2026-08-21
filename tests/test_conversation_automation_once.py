"""Wave 12 ("Einmalige Automation"): the full spoken create/confirm round
trip for a fire-once, self-deleting automation, exercised through the real
``NluConversationEntity._async_handle_message()`` orchestration - not a
second reimplementation of ``engine.py``'s ``_AUTOMATION_ONCE_RE`` detection,
``ha_automation_generator.py``'s self-delete action injection, or
``ha_nlu/__init__.py``'s ``ha_nlu.delete_automation`` service handler (each
already has its own dedicated unit test file; this file's job is to prove
the whole live pipeline wires them together correctly turn-to-turn, for both
a state-based and a time-based trigger - the user explicitly asked for both,
not just time-based).

Reuses the exact ``_ha_stub``/``_make_entity``/``_run``/``_automations_yaml``
harness ``tests/test_conversation_automation_delete.py`` already established
(Regel 6). The self-delete service handler is invoked directly via
``ha_nlu._async_delete_automation()`` (the real production function, same
one ``__init__.py`` registers as the ``ha_nlu.delete_automation`` service) to
simulate the generated automation's action step firing, since this test
harness has no real HA automation/trigger engine to actually fire the
automation end-to-end.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml as pyyaml

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

import ha_nlu as ha_nlu_init  # noqa: E402
import ha_nlu.conversation as ha_conversation  # noqa: E402
from ha_nlu.conversation import AUTOMATION_CREATED_TEXT, NluConversationEntity  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant, ServiceCall  # noqa: E402
from homeassistant.helpers import category_registry as cr, entity_registry as er, intent  # noqa: E402

KUECHE_FENSTER_ZU = EntitySnapshot(
    "binary_sensor.kueche_fenster", "Küchenfenster", "binary_sensor", "off",
    area_id="kueche", area_name="Küche", device_class="window",
)
KUECHE_LICHT = EntitySnapshot(
    "light.kueche_licht", "Küchenlicht", "light", "off",
    area_id="kueche", area_name="Küche",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
WOHNZIMMER_ROLLLADEN = EntitySnapshot(
    "cover.wohnzimmer_rollladen", "Wohnzimmer Rollladen", "cover", "closed",
    area_id="wohnzimmer", area_name="Wohnzimmer",
    capabilities=frozenset({"POSITION"}),
)
ALL_ENTITIES = [KUECHE_FENSTER_ZU, KUECHE_LICHT, WOHNZIMMER_ROLLLADEN]

STATE_BASED_ONCE_SENTENCE = (
    "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht einmalig ein."
)
TIME_BASED_ONCE_SENTENCE = "Wenn es 20 Uhr ist, schalte das Küchenlicht nur einmal ein."
ORDINARY_SENTENCE = "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein."
RELATIVE_TIME_SENTENCE = "Fahre in 5 Minuten die Wohnzimmer Rolllade auf 30%"

ONCE_NOTE = "Diese Automation wird nach der ersten Ausführung automatisch gelöscht."


def _make_entity(monkeypatch, tmp_path: Path) -> NluConversationEntity:
    entry = ConfigEntry()
    entity = NluConversationEntity(entry)
    entity.hass = HomeAssistant()
    entity.hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda hass, entry: ALL_ENTITIES
    )
    return entity


def _run(entity: NluConversationEntity, text: str, conversation_id: str = "conv-1"):
    user_input = ConversationInput(text=text, conversation_id=conversation_id)
    return asyncio.run(entity._async_handle_message(user_input, chat_log=None))


def _automations_yaml(tmp_path: Path) -> list[dict]:
    path = tmp_path / "automations.yaml"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as handle:
        return pyyaml.safe_load(handle) or []


# --- preview: the spoken confirmation names the self-delete behaviour ------


def test_the_confirmation_preview_names_the_self_delete_behaviour(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)

    preview_result = _run(entity, STATE_BASED_ONCE_SENTENCE)

    assert ONCE_NOTE in preview_result.response.speech
    assert _automations_yaml(tmp_path) == []


def test_an_ordinary_automation_preview_has_no_once_note(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)

    preview_result = _run(entity, ORDINARY_SENTENCE)

    assert ONCE_NOTE not in preview_result.response.speech


# --- confirming creates the automation with a trailing self-delete action --


def test_confirming_a_state_based_once_automation_appends_the_matching_self_delete_action(
    monkeypatch, tmp_path
):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, STATE_BASED_ONCE_SENTENCE)

    create_result = _run(entity, "Ja")

    assert create_result.response.speech == AUTOMATION_CREATED_TEXT
    automations = _automations_yaml(tmp_path)
    assert len(automations) == 1
    automation = automations[0]
    assert automation["actions"][-1] == {
        "action": "ha_nlu.delete_automation",
        "data": {"automation_id": automation["id"]},
    }
    # The turn-on action is still present ahead of the self-delete step.
    assert automation["actions"][0]["action"] == "homeassistant.turn_on"


def test_confirming_a_time_based_once_automation_also_appends_the_self_delete_action(
    monkeypatch, tmp_path
):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, TIME_BASED_ONCE_SENTENCE)

    create_result = _run(entity, "Ja")

    assert create_result.response.speech == AUTOMATION_CREATED_TEXT
    automations = _automations_yaml(tmp_path)
    assert len(automations) == 1
    automation = automations[0]
    assert automation["triggers"][0]["trigger"] == "time"
    assert automation["actions"][-1] == {
        "action": "ha_nlu.delete_automation",
        "data": {"automation_id": automation["id"]},
    }


def test_confirming_an_ordinary_automation_appends_no_self_delete_action(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, ORDINARY_SENTENCE)

    create_result = _run(entity, "Ja")

    assert create_result.response.speech == AUTOMATION_CREATED_TEXT
    automations = _automations_yaml(tmp_path)
    assert len(automations) == 1
    assert all(
        action.get("action") != "ha_nlu.delete_automation" for action in automations[0]["actions"]
    )


# --- firing the self-delete action removes exactly the once-automation -----


def test_firing_the_self_delete_action_removes_the_once_automation_and_reloads(
    monkeypatch, tmp_path
):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, STATE_BASED_ONCE_SENTENCE)
    _run(entity, "Ja")
    automation_id = _automations_yaml(tmp_path)[0]["id"]
    entity.hass.services.async_call.reset_mock()

    asyncio.run(
        ha_nlu_init._async_delete_automation(
            entity.hass, ServiceCall({"automation_id": automation_id})
        )
    )

    assert _automations_yaml(tmp_path) == []
    entity.hass.services.async_call.assert_awaited_once_with(
        "automation", "reload", {}, blocking=True
    )


def test_firing_the_self_delete_action_never_touches_an_unrelated_ordinary_automation(
    monkeypatch, tmp_path
):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, ORDINARY_SENTENCE)
    _run(entity, "Ja")
    _run(entity, STATE_BASED_ONCE_SENTENCE, conversation_id="once")
    _run(entity, "Ja", conversation_id="once")
    automations_before = _automations_yaml(tmp_path)
    assert len(automations_before) == 2
    once_id = next(a["id"] for a in automations_before if a["actions"][-1].get("action") == "ha_nlu.delete_automation")

    asyncio.run(
        ha_nlu_init._async_delete_automation(entity.hass, ServiceCall({"automation_id": once_id}))
    )

    remaining = _automations_yaml(tmp_path)
    assert len(remaining) == 1
    assert remaining[0]["actions"][-1].get("action") != "ha_nlu.delete_automation"


def test_an_ordinary_automation_is_never_auto_removed_because_it_has_no_self_delete_action(
    monkeypatch, tmp_path
):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, ORDINARY_SENTENCE)
    _run(entity, "Ja")

    assert len(_automations_yaml(tmp_path)) == 1
    # No delete_automation action exists to ever fire for this automation -
    # nothing in this pipeline removes it on its own.


# --- cost gate / unrelated flows stay unaffected ----------------------------


def test_a_stray_unmatched_reply_after_a_once_confirmation_is_not_swallowed(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, STATE_BASED_ONCE_SENTENCE)
    _run(entity, "Ja")

    stray_result = _run(entity, "Wie ist das Wetter?")

    assert stray_result.response.error_code == intent.IntentResponseErrorCode.NO_INTENT_MATCH


def test_relative_time_command_round_trip_writes_valid_time_action_and_self_delete(
    monkeypatch, tmp_path
):
    entity = _make_entity(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ha_conversation.dt_util,
        "now",
        lambda: datetime(2026, 8, 21, 12, 0, 42, tzinfo=timezone.utc),
    )

    preview_result = _run(entity, RELATIVE_TIME_SENTENCE)

    assert ONCE_NOTE in preview_result.response.speech
    assert _automations_yaml(tmp_path) == []

    create_result = _run(entity, "Ja")

    assert create_result.response.speech == AUTOMATION_CREATED_TEXT
    automation = _automations_yaml(tmp_path)[0]
    assert automation["triggers"] == [{"trigger": "time", "at": "12:05:42"}]
    assert automation["actions"][0] == {
        "action": "cover.set_cover_position",
        "target": {"entity_id": "cover.wohnzimmer_rollladen"},
        "data": {"position": 30},
    }
    assert automation["actions"][-1] == {
        "action": "ha_nlu.delete_automation",
        "data": {"automation_id": automation["id"]},
    }
    entity.hass.services.async_call.assert_awaited_once_with(
        "automation", "reload", {}, blocking=True
    )
    categories = list(cr.async_get(entity.hass).async_list_categories(scope="automation"))
    assert len(categories) == 1 and categories[0].name == "Homeintent"
    entity_id = er.async_get(entity.hass).async_get_entity_id(
        "automation", "automation", automation["id"]
    )
    assert er.async_get(entity.hass).async_get(entity_id).categories == {
        "automation": categories[0].category_id
    }
