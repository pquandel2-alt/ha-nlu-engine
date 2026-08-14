"""ResponseGenerator (HomeIntent v4.2.1 plan, Section 12/Phase 6): the third
stage of the Query pipeline - ``QueryResult`` -> German response text, kept
as its own step, separate from ``QueryResult`` itself (Section 12's explicit
3-stage split: Parser -> QueryCommand -> QueryExecutor -> QueryResult ->
ResponseGenerator -> text).

Wording mirrors ``service_call.py``'s existing ``_speak_state_query``/
``_speak_check_state``/``_speak_exists`` lambdas exactly (today's
pre-Phase-7 pipeline, still in use) - the small vocabulary dicts below are a
deliberate, temporary duplication rather than an import from that module's
private names; Phase 7 migrates ``StateQueryParser``'s callers onto this
class non-destructively and consolidates the vocabulary into one place at
that point (Section 13: additive first, no premature refactor of code still
serving production).

``TARGET_NOT_FOUND``/``AMBIGUOUS`` have no equivalent in today's pipeline -
``StateQueryParser`` never produces a ``ParseResult`` for those cases at all
(a plain ``None``, which ``conversation.py`` renders as the generic
``NOT_UNDERSTOOD_TEXT``). This class gives them their own, more specific
text, ready for a future caller - it does not itself trigger a
clarification round-trip (``resolve_clarification()``'s scope stays
unchanged, per ``StateQueryParser``'s own "no clarification round-trip for
HassCheckState" precedent, Regel 4).

Never touches Home Assistant - it doesn't even see a ``hass`` object, only a
``QueryResult``.
"""

from __future__ import annotations

from .query_command import QueryResult, QueryResultStatus, QueryScope
from .semantic_state import SemanticState, matches_semantic_state

_SEMANTIC_STATE_SPOKEN_DE = {
    SemanticState.OPEN: "offen",
    SemanticState.CLOSED: "geschlossen",
    SemanticState.ON: "eingeschaltet",
    SemanticState.OFF: "ausgeschaltet",
}

_DEVICE_CLASS_PLURAL_DE = {
    "window": "Fenster", "door": "Türen", "garage_door": "Garagentore", "motion": "Bewegungsmelder",
}

_DOMAIN_PLURAL_DE = {"light": "Lichter", "switch": "Schalter", "fan": "Ventilatoren", "cover": "Rollläden"}


class ResponseGenerator:
    """Stateless, same as ``QueryExecutor`` - one shared instance is enough."""

    def respond(self, result: QueryResult) -> str:
        if result.status is QueryResultStatus.TARGET_NOT_FOUND:
            return "Das habe ich nicht gefunden."
        if result.status is QueryResultStatus.AMBIGUOUS:
            return "Das ist nicht eindeutig - mehrere Geräte passen darauf."

        command = result.command
        if command is None:
            # Defensive only - every QueryExecutor result carries its
            # originating command; a bare MATCHED/EMPTY status without one
            # can't be spoken (nothing constructs QueryResult that way).
            return "Das habe ich nicht verstanden."

        if command.scope is QueryScope.SINGLE:
            return self._respond_single(result)
        if command.scope is QueryScope.EXISTS:
            return self._respond_exists(result)
        return self._respond_list_or_count(result)

    @staticmethod
    def _noun(result: QueryResult) -> str:
        target = result.command.target
        if target.device_class is not None:
            return _DEVICE_CLASS_PLURAL_DE.get(target.device_class, "Geräte")
        return _DOMAIN_PLURAL_DE.get(target.domain, "Geräte")

    def _respond_list_or_count(self, result: QueryResult) -> str:
        state_word = _SEMANTIC_STATE_SPOKEN_DE[result.command.filter.state]
        noun = self._noun(result)
        entities = result.entities
        if not entities:
            return f"Keine {noun} sind {state_word}."
        if len(entities) == 1:
            return f"{entities[0].friendly_name} ist {state_word}."
        if result.command.scope is QueryScope.COUNT:
            return f"{len(entities)} {noun} sind {state_word}."
        return ", ".join(e.friendly_name for e in entities) + f" sind {state_word}."

    def _respond_exists(self, result: QueryResult) -> str:
        noun = self._noun(result)
        if not result.entities:
            return f"Nein, es gibt keine {noun}."
        return f"Ja, es gibt {len(result.entities)} {noun}."

    @staticmethod
    def _respond_single(result: QueryResult) -> str:
        entity = result.entities[0]
        requested = result.command.filter.state
        state_word = _SEMANTIC_STATE_SPOKEN_DE[requested]
        if matches_semantic_state(entity, requested):
            return f"Ja, {entity.friendly_name} ist {state_word}."
        return f"Nein, {entity.friendly_name} ist nicht {state_word}."
