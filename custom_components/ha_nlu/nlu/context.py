"""Conversation state (v2 plan Phase 24, "Conversation State"). Foundation for
the dialog-capability phases that build on top of it: Phase 25 ("Clarification")
wires ``ClarificationRequest`` into a real "Welches Licht meinst du?" round-trip,
Phase 26 ("Context") wires ``last_command``/``last_entities``/``last_area`` into
follow-up merging ("Mach das Wohnzimmerlicht an." -> "Etwas heller."), Phase 27
("Pronomen/Referenzen") resolves "es"/"die andere"/etc. against the same context.

This module only defines the state shape and its per-conversation storage -
deliberately not wired into ``conversation.py``/``engine.py`` yet, same
build-ahead-of-consumer pattern as ``SemanticCommand``/``EntityIndex`` in their
own phases (see docs/architecture-v2-phase22.md).

Kept free of Home Assistant/hassil imports, same boundary as the rest of
``nlu/``: ``EntitySnapshot``/``AreaSnapshot``/``SemanticCommand`` are already
hass-free by this point, and storage below only needs a monotonic clock.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from ..areas import AreaSnapshot
from ..entities import EntitySnapshot
from .command import SemanticCommand

# No TTL value is specified anywhere in the plan (only the test case name
# "context expiration", brain node 9ced4390, section 26). 30s covers a
# natural spoken follow-up ("Mach das Licht an." <pause> "Etwas heller.")
# without keeping stale state around for unrelated later commands in the
# same HA conversation_id. Revisit if Phase 26/27 wiring shows it's wrong.
DEFAULT_CONTEXT_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class ClarificationRequest:
    """A pending disambiguation question, per the plan's ``ConversationState``
    sketch (brain node e2946a55, section 23) - field names match it exactly.
    """

    pending_intent: str
    pending_target: str | None
    candidates: tuple[EntitySnapshot, ...]


@dataclass(frozen=True)
class ConversationContext:
    """Per plan brain node e2946a55, section 24 - field names match exactly."""

    last_command: SemanticCommand | None
    last_entities: tuple[EntitySnapshot, ...]
    last_area: AreaSnapshot | None
    pending_clarification: ClarificationRequest | None


class ConversationContextStore:
    """In-memory ``ConversationContext`` storage keyed by HA's
    ``conversation_id`` (already available as ``user_input.conversation_id``
    in ``conversation.py``, just not consumed yet), with TTL-based expiration
    so an old, unrelated context never leaks into a much later turn.

    Not thread-safety-hardened beyond what HA's single-event-loop model
    already guarantees (same assumption the rest of this integration makes -
    no other module here uses locks either).
    """

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_CONTEXT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[float, ConversationContext]] = {}

    def get(self, conversation_id: str) -> ConversationContext | None:
        entry = self._entries.get(conversation_id)
        if entry is None:
            return None
        stored_at, context = entry
        if self._clock() - stored_at > self._ttl_seconds:
            del self._entries[conversation_id]
            return None
        return context

    def set(self, conversation_id: str, context: ConversationContext) -> None:
        self._entries[conversation_id] = (self._clock(), context)

    def clear(self, conversation_id: str) -> None:
        self._entries.pop(conversation_id, None)
