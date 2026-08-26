import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components"))
sys.path.insert(0, str(Path(__file__).parent))

import _ha_stub  # noqa: E402

_ha_stub.install()

from ha_nlu.alias_learning import append_alias_rule, parse_alias_learning  # noqa: E402
from ha_nlu.entities import EntitySnapshot  # noqa: E402
import ha_nlu.conversation as ha_conversation  # noqa: E402
from ha_nlu.conversation import NluConversationEntity  # noqa: E402
from homeassistant.components.conversation import ConversationInput  # noqa: E402
from homeassistant.config_entries import ConfigEntry  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402


ENTITIES = [
    EntitySnapshot("light.desk", "Schreibtischlampe", "light", "off"),
    EntitySnapshot("light.ceiling", "Deckenlampe", "light", "off"),
]


def test_explicit_alias_teaching_creates_a_bounded_draft():
    draft = parse_alias_learning(
        "Mit Bürolicht meine ich Schreibtischlampe.", ENTITIES
    )

    assert draft is not None
    assert draft.alias == "Bürolicht"
    assert draft.entity_id == "light.desk"
    assert append_alias_rule("", draft) == "Bürolicht = light.desk"


def test_alias_rule_is_idempotent_and_conflicts_are_rejected():
    draft = parse_alias_learning(
        "Nenne Schreibtischlampe künftig Bürolicht", ENTITIES
    )
    assert draft is not None
    existing = "Bürolicht = light.desk"
    assert append_alias_rule(existing, draft) == existing

    with pytest.raises(ValueError):
        append_alias_rule(
            "Bürolicht = light.ceiling", draft
        )


def test_implicit_or_colliding_alias_learning_is_refused():
    assert parse_alias_learning("Bürolicht Schreibtischlampe", ENTITIES) is None
    assert parse_alias_learning(
        "Mit Deckenlampe meine ich Schreibtischlampe", ENTITIES
    ) is None


def test_alias_learning_requires_confirmation_before_persistence(monkeypatch):
    entry = ConfigEntry(options={})
    agent = NluConversationEntity(entry)
    agent.hass = HomeAssistant()
    monkeypatch.setattr(
        ha_conversation, "build_entity_snapshots", lambda hass, config_entry: ENTITIES
    )
    monkeypatch.setattr(
        ha_conversation, "build_device_snapshots", lambda hass, config_entry: []
    )

    def update_entry(config_entry, *, options):
        config_entry.options = options

    agent.hass.config_entries = SimpleNamespace(async_update_entry=update_entry)

    preview = asyncio.run(agent._async_handle_message(
        ConversationInput(
            text="Mit Bürolicht meine ich Schreibtischlampe",
            conversation_id="alias-dialog",
        ),
        chat_log=None,
    ))
    assert "Soll ich" in preview.response.speech
    assert entry.options == {}

    saved = asyncio.run(agent._async_handle_message(
        ConversationInput(text="ja", conversation_id="alias-dialog"),
        chat_log=None,
    ))
    assert "Gespeichert" in saved.response.speech
    assert entry.options["custom_aliases"] == "Bürolicht = light.desk"
