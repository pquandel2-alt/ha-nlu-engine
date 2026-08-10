"""Unit tests for nlu.context (v2 plan Phase 24, "Conversation State") -
hass-free, no engine/hassil involved. Not wired into conversation.py yet
(see nlu/context.py's module docstring), so these tests exercise the
dataclasses and store directly.
"""

from __future__ import annotations

from ha_nlu.entities import EntitySnapshot
from ha_nlu.nlu.context import (
    ClarificationRequest,
    ConversationContext,
    ConversationContextStore,
)

LIGHT_WOHNZIMMER = EntitySnapshot("light.wohnzimmer", "Wohnzimmerlicht", "light", "on")
LIGHT_KUECHE = EntitySnapshot("light.kueche", "Küchenlicht", "light", "on")

EMPTY_CONTEXT = ConversationContext(
    last_command=None,
    last_entities=(),
    last_area=None,
    pending_clarification=None,
)


def _clarification() -> ClarificationRequest:
    return ClarificationRequest(
        pending_intent="HassTurnOn",
        pending_target="Licht",
        candidates=(LIGHT_KUECHE, LIGHT_WOHNZIMMER),
    )


def test_store_returns_none_for_unknown_conversation_id():
    store = ConversationContextStore()
    assert store.get("unknown") is None


def test_store_roundtrips_a_context():
    store = ConversationContextStore()
    context = ConversationContext(
        last_command=None,
        last_entities=(LIGHT_WOHNZIMMER,),
        last_area=None,
        pending_clarification=_clarification(),
    )
    store.set("conv-1", context)
    assert store.get("conv-1") == context


def test_store_clear_removes_the_entry():
    store = ConversationContextStore()
    store.set("conv-1", EMPTY_CONTEXT)
    store.clear("conv-1")
    assert store.get("conv-1") is None


def test_store_expires_entries_older_than_ttl():
    fake_time = [0.0]
    store = ConversationContextStore(ttl_seconds=30.0, clock=lambda: fake_time[0])
    store.set("conv-1", EMPTY_CONTEXT)

    fake_time[0] = 29.0
    assert store.get("conv-1") is not None

    fake_time[0] = 31.0
    assert store.get("conv-1") is None


def test_store_keeps_separate_conversation_ids_independent():
    store = ConversationContextStore()
    context_a = ConversationContext(
        last_command=None, last_entities=(LIGHT_WOHNZIMMER,), last_area=None, pending_clarification=None,
    )
    context_b = ConversationContext(
        last_command=None, last_entities=(LIGHT_KUECHE,), last_area=None, pending_clarification=None,
    )
    store.set("conv-a", context_a)
    store.set("conv-b", context_b)
    assert store.get("conv-a") == context_a
    assert store.get("conv-b") == context_b
