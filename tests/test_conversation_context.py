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
    PendingAutomationConfirmation,
)
from ha_nlu.nlu.automation_model import AutomationModel

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


def test_automation_confirmation_uses_a_longer_ttl():
    fake_time = [0.0]
    store = ConversationContextStore(
        ttl_seconds=30.0,
        automation_confirmation_ttl_seconds=120.0,
        clock=lambda: fake_time[0],
    )
    context = ConversationContext(
        last_command=None,
        last_entities=(),
        last_area=None,
        pending_clarification=None,
        pending_automation_confirmation=PendingAutomationConfirmation(
            model=AutomationModel()
        ),
    )
    store.set("automation", context)

    fake_time[0] = 60.0
    assert store.get("automation") == context
    fake_time[0] = 121.0
    assert store.get("automation") is None


def test_v6_context_fields_default_to_none_for_existing_call_sites():
    # V6.12 ("Semantic Context"): last_floor/last_property/last_value/
    # last_state/pending_reference are additive - every pre-V6 construction
    # (like EMPTY_CONTEXT above) must keep working unchanged.
    assert EMPTY_CONTEXT.last_floor is None
    assert EMPTY_CONTEXT.last_property is None
    assert EMPTY_CONTEXT.last_value is None
    assert EMPTY_CONTEXT.last_state is None
    assert EMPTY_CONTEXT.pending_reference is None


def test_conversation_context_accepts_v6_fields_directly():
    from ha_nlu.floors import FloorSnapshot
    from ha_nlu.nlu.primitives import SemanticProperty
    from ha_nlu.nlu.semantic_state import SemanticState

    context = ConversationContext(
        last_command=None,
        last_entities=(),
        last_area=None,
        pending_clarification=None,
        last_floor=FloorSnapshot(floor_id="og", name="Obergeschoss", level=1),
        last_property=SemanticProperty.BRIGHTNESS,
        last_value=42.0,
        last_state=SemanticState.OPEN,
        pending_reference="die andere",
    )
    assert context.last_floor.floor_id == "og"
    assert context.last_property is SemanticProperty.BRIGHTNESS
    assert context.last_value == 42.0
    assert context.last_state is SemanticState.OPEN
    assert context.pending_reference == "die andere"
