"""HomeIntent V5 Teil 9/10 (V5.29, "Automation Query"): the full live
conversation-turn wiring - regex pre-check -> ``AutomationExecutor.
async_list_automations()`` -> ``NluEngine.match_automation_query()`` -
exercised through the real ``NluConversationEntity._async_handle_message()``
orchestration, not a second reimplementation of any of those three (each
already has its own dedicated pure-function/direct-method test file, see
``tests/test_automation_executor.py``/``tests/test_engine_automation_query.py``).

Reuses the exact ``_ha_stub``/``_make_entity``/``_run`` harness
``tests/test_conversation_automation_confirmation.py`` already established
(Regel 6) - including creating a real automation through the existing YES
confirmation round-trip first, so the automations.yaml/metadata-sidecar this
file's queries read back is the real thing that pipeline writes, not a
hand-rolled fixture duplicating its shape.
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

import ha_nlu.automation_executor as ha_automation_executor  # noqa: E402
import ha_nlu.conversation as ha_conversation  # noqa: E402
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402

KUECHE_FENSTER_ZU = EntitySnapshot(
    "binary_sensor.kueche_fenster", "Küchenfenster", "binary_sensor", "off",
    area_id="kueche", area_name="Küche", device_class="window",
)
KUECHE_LICHT = EntitySnapshot(
    "light.kueche_licht", "Küchenlicht", "light", "off",
    area_id="kueche", area_name="Küche",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
BUERO_LICHT = EntitySnapshot(
    "light.buero_licht", "Bürolicht", "light", "off",
    area_id="buero", area_name="Büro",
    capabilities=frozenset({"TURN_ON", "TURN_OFF"}),
)
BUERO_ROLLLADE = EntitySnapshot(
    "cover.buero_rollladen", "Büro Rollladen", "cover", "closed",
    area_id="buero", area_name="Büro",
    capabilities=frozenset({"POSITION"}),
)
ALL_ENTITIES = [KUECHE_FENSTER_ZU, KUECHE_LICHT, BUERO_LICHT, BUERO_ROLLLADE]

AUTOMATION_SENTENCE = "Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein."


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


# --- bare listing -----------------------------------------------------------


def test_bare_listing_with_no_automations_yet(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)

    result = _run(entity, "Welche Automationen gibt es?")

    assert result.response.speech == "Es sind keine Automationen vorhanden."
    entity.hass.services.async_call.assert_not_awaited()


def test_bare_listing_lists_a_created_automation(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, AUTOMATION_SENTENCE, conversation_id="create")
    _run(entity, "Ja", conversation_id="create")

    result = _run(entity, "Welche Automationen gibt es?", conversation_id="query")

    assert AUTOMATION_SENTENCE in result.response.speech


# --- entity-filtered ("was schaltet X") --------------------------------------


def test_entity_filtered_query_finds_the_matching_automation(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, AUTOMATION_SENTENCE, conversation_id="create")
    _run(entity, "Ja", conversation_id="create")

    result = _run(entity, "Was schaltet Küchenlicht?", conversation_id="query")

    assert AUTOMATION_SENTENCE in result.response.speech


def test_entity_filtered_query_with_no_matching_automation(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, AUTOMATION_SENTENCE, conversation_id="create")
    _run(entity, "Ja", conversation_id="create")

    result = _run(entity, "Was schaltet Bürolicht?", conversation_id="query")

    assert result.response.speech == "Ich habe keine Automation gefunden, die Bürolicht steuert."


# --- causal wording ("warum ist/geht X ...") --------------------------------


def test_causal_query_uses_hedged_wording(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, AUTOMATION_SENTENCE, conversation_id="create")
    _run(entity, "Ja", conversation_id="create")

    result = _run(entity, "Warum ist Küchenlicht an?", conversation_id="query")

    assert "könnte" in result.response.speech


# --- cost gate: the blocking automations.yaml/metadata read is skipped -----
# for ordinary turns that don't look like an automation query -----------------


def test_an_ordinary_command_never_triggers_the_automations_yaml_read(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)

    async def _fail_if_called(self):
        raise AssertionError(
            "async_list_automations() must not be called for a sentence "
            "that doesn't match the automation-query regex gate"
        )

    monkeypatch.setattr(
        ha_automation_executor.AutomationExecutor, "async_list_automations", _fail_if_called
    )

    result = _run(entity, "Schalte das Küchenlicht ein.")

    entity.hass.services.async_call.assert_awaited_once()
    assert result.response.speech != "Das habe ich nicht verstanden."


def test_lists_only_homeintent_automations(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, AUTOMATION_SENTENCE, conversation_id="create")
    _run(entity, "Ja", conversation_id="create")

    result = _run(entity, "Zeige nur HomeIntent-Automationen", conversation_id="query")

    assert "HomeIntent-Automationen:" in result.response.speech
    assert AUTOMATION_SENTENCE in result.response.speech


def test_planned_query_when_query_and_reschedule_round_trip(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ha_conversation.dt_util,
        "now",
        lambda: datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
    )
    _run(
        entity,
        "Fahre in 5 Stunden die Büro Rolllade auf 40 Prozent",
        conversation_id="create",
    )
    _run(entity, "Ja", conversation_id="create")

    planned = _run(
        entity,
        "Welche einmaligen Aufträge sind noch geplant?",
        conversation_id="planned",
    )
    when = _run(
        entity,
        "Wann wird Büro Rolllade gefahren?",
        conversation_id="when",
    )
    moved = _run(
        entity,
        "Verschiebe den Auftrag für Büro Rolllade auf 20 Uhr",
        conversation_id="move",
    )

    assert "21.08.2026 um 17:00 Uhr" in planned.response.speech
    assert "21.08.2026 um 17:00 Uhr" in when.response.speech
    assert "21.08.2026 um 20:00 Uhr" in moved.response.speech


def test_targetless_reschedule_asks_for_device_when_multiple_jobs_match(
    monkeypatch, tmp_path
):
    entity = _make_entity(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ha_conversation.dt_util,
        "now",
        lambda: datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc),
    )
    for conversation_id, sentence in (
        ("one", "In einer Stunde schalte das Küchenlicht ein"),
        ("two", "In zwei Stunden schalte das Bürolicht ein"),
    ):
        _run(entity, sentence, conversation_id=conversation_id)
        _run(entity, "Ja", conversation_id=conversation_id)

    result = _run(entity, "Verschiebe den Auftrag auf 20 Uhr", conversation_id="move")

    assert "Mehrere Aufträge passen" in result.response.speech
    assert "Bitte nenne das Gerät" in result.response.speech


def test_existing_automation_can_be_limited_to_three_runs(monkeypatch, tmp_path):
    entity = _make_entity(monkeypatch, tmp_path)
    _run(entity, AUTOMATION_SENTENCE, conversation_id="create")
    _run(entity, "Ja", conversation_id="create")

    result = _run(
        entity,
        "Wiederhole die Automation für Küchenlicht nur dreimal",
        conversation_id="limit",
    )

    automations = pyyaml.safe_load(
        (tmp_path / "automations.yaml").read_text(encoding="utf-8")
    )
    assert "nur noch 3 Mal" in result.response.speech
    assert automations[0]["actions"][-1] == {
        "action": "ha_nlu.record_automation_run",
        "data": {"automation_id": automations[0]["id"], "max_runs": 3},
    }
