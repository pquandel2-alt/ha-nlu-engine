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
from ..floors import FloorSnapshot
from .automation_model import AutomationModel
from .command import SemanticCommand
from .parser import ClarificationRequest
from .primitives import SemanticProperty
from .semantic_state import SemanticState

__all__ = [
    "ClarificationRequest",
    "ConversationContext",
    "ConversationContextStore",
    "DEFAULT_CONTEXT_TTL_SECONDS",
    "PendingAutomationConfirmation",
]


@dataclass(frozen=True)
class PendingAutomationConfirmation:
    """A pending "Soll diese Automation erstellt werden?" Dry-Run gate
    (HomeIntent V5 Teil 7/10, V5.23) - the automation-creation counterpart
    to ``ClarificationRequest`` above, stored on ``ConversationContext`` the
    same way and resolved the same way (a dedicated reply-classification
    step, see ``nlu/automation_confirmation.py``, run before any fresh
    sentence is even attempted - same priority ``pending_clarification``
    already has in ``conversation.py``).

    Carries only the already-``validate_automation()``-clean
    ``AutomationModel`` itself - not a copy of the entities it was resolved
    against. The confirming reply turn already re-fetches a fresh entity
    list the same way every other turn does (``conversation.py``'s
    ``build_entity_snapshots()``), so the later HA Generator (V5.25) always
    resolves any still-abstract domain/area/quantifier target (see
    ``automation_action_parser.py``'s ``_build_quantified_target()``
    docstring: "re-validation against live HA state at execution time is a
    future HA-generator wave's job") against current state, not a
    confirmation-time snapshot that could already be stale.
    """

    model: AutomationModel

# No TTL value is specified anywhere in the plan (only the test case name
# "context expiration", brain node 9ced4390, section 26). 30s covers a
# natural spoken follow-up ("Mach das Licht an." <pause> "Etwas heller.")
# without keeping stale state around for unrelated later commands in the
# same HA conversation_id. Revisit if Phase 26/27 wiring shows it's wrong.
DEFAULT_CONTEXT_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class ConversationContext:
    """Per plan brain node e2946a55, section 24 - field names match exactly
    for the original four fields.

    V6 architecture plan, V6.12 ("Semantic Context", Brain node
    2a0871f8-05a4-4e0d-8cb6-80a8ff939480): the plan's minimum field list adds
    last_intent/last_action/last_target/last_query on top of the four fields
    above - deliberately **not** added here as separate fields, since all
    four are already fully recoverable from ``last_command`` (``.intent``,
    ``.parameters`` for query_command, etc. - see ``engine.py``'s
    ``match_query_followup()`` reading ``last_command.parameters.get(
    "query_command")`` today) and duplicating them here would be a second,
    driftable copy of the same state (Regel 6, "no parallel search/state
    system"). Only genuinely new, not-yet-tracked-anywhere information is
    added: ``last_floor``/``last_property``/``last_value``/``last_state``
    (the plan's remaining minimum-list fields) and ``pending_reference``
    (an unresolved *reference*, e.g. an ambiguous "die andere" with no
    matching candidate - distinct from ``pending_clarification``, which is
    entity-candidate ambiguity from Phase 25's ``ClarificationRequest``).

    All five are ``None``-defaulted and, same as ``SemanticFrame``'s V6.2
    primitive fields, not populated by any pipeline step yet - populating
    them is the Reasoning Engine's job (V6.25, later Wave), which is the
    first component that will actually compute a resolved property/value/
    state per turn. Every existing ``ConversationContext(...)`` call site
    uses keyword args (verified across conversation.py and all context/
    reference/query-followup tests), so this stays fully backward
    compatible.
    """

    last_command: SemanticCommand | None
    last_entities: tuple[EntitySnapshot, ...]
    last_area: AreaSnapshot | None
    pending_clarification: ClarificationRequest | None
    last_floor: FloorSnapshot | None = None
    last_property: SemanticProperty | None = None
    last_value: float | None = None
    last_state: SemanticState | None = None
    pending_reference: str | None = None
    # V5 Teil 7/10 (V5.23, "Dry Run") - a spoken automation awaiting its
    # "ja"/"nein" confirmation before it may ever be persisted to Home
    # Assistant (see PendingAutomationConfirmation's own docstring).
    pending_automation_confirmation: PendingAutomationConfirmation | None = None


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
