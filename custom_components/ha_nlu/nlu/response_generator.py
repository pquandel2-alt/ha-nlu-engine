"""ResponseGenerator (HomeIntent v4.2.1 plan, Section 12/Phase 6): the third
stage of the Query pipeline - ``QueryResult`` -> German response text, kept
as its own step, separate from ``QueryResult`` itself (Section 12's explicit
3-stage split: Parser -> QueryCommand -> QueryExecutor -> QueryResult ->
ResponseGenerator -> text).

WorldModelQuery wave: this is now the **live** response source for
``StateQueryParser``'s four intents (``HassStateQuery``/``HassCheckState``/
``HassExistsQuery``/``HassDeviceQuery``) - ``engine.py::_build_match_result``
calls ``respond()`` whenever ``frame.parameters["query_result"]`` is set,
before it ever reaches ``service_call.py``'s ``QUERY_INTENTS`` response
lambdas (now dead code for those three intents, kept only because
``QueryIntentSpec.response`` is a required field). The wording below is no
longer required to mirror those lambdas byte-for-byte - it is the primary
source now, not a future-caller preview.

All four ``QueryResultStatus`` values are distinguished, each with its own
noun-aware text: ``MATCHED``/``EMPTY`` via ``_respond_single``/
``_respond_exists``/``_respond_list_or_count``/``_respond_device_list``;
``TARGET_NOT_FOUND``/``AMBIGUOUS`` directly in ``respond()``. Neither of the
latter two is reachable via any sentence live today (see
``QueryExecutor._execute_plural``'s own docstring and
``StateQueryParser._parse_check_state``'s "never guess, no clarification
round-trip" precedent, Regel 4) - they stay correct and tested for a future
caller, without changing that existing refuse-early behavior.

Never touches Home Assistant - it doesn't even see a ``hass`` object, only a
``QueryResult``.
"""

from __future__ import annotations

from .query_command import QueryResult, QueryResultStatus, QueryScope, QueryTargetKind
from .semantic_state import SemanticState, matches_semantic_state

_SEMANTIC_STATE_SPOKEN_DE = {
    SemanticState.OPEN: "geöffnet",
    SemanticState.CLOSED: "geschlossen",
    SemanticState.ON: "eingeschaltet",
    SemanticState.OFF: "ausgeschaltet",
}

_DEVICE_CLASS_PLURAL_DE = {
    "window": "Fenster", "door": "Türen", "garage_door": "Garagentore", "motion": "Bewegungsmelder",
}

_DOMAIN_PLURAL_DE = {"light": "Lichter", "switch": "Schalter", "fan": "Ventilatoren", "cover": "Rollläden"}


def _join_names(names: list[str]) -> str:
    """Natural German list-joining ("A und B" for 2, "A, B und C" for 3+)
    instead of a pure comma-join - shared by every multi-result branch below
    (Regel 6: one helper, several call sites)."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} und {names[1]}"
    return ", ".join(names[:-1]) + f" und {names[-1]}"


class ResponseGenerator:
    """Stateless, same as ``QueryExecutor`` - one shared instance is enough."""

    def respond(self, result: QueryResult) -> str:
        command = result.command
        if command is None:
            # Defensive only - every QueryExecutor result carries its
            # originating command; a bare status without one can't be spoken
            # (nothing constructs QueryResult that way).
            return "Das habe ich nicht verstanden."

        if result.status is QueryResultStatus.TARGET_NOT_FOUND:
            return f"Ich konnte keine passenden {self._noun(result)} finden."
        if result.status is QueryResultStatus.AMBIGUOUS:
            return f"Ich habe mehrere passende {self._noun(result)} gefunden."

        if command.target.kind is QueryTargetKind.DEVICE:
            return self._respond_device_list(result)
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
        state = result.command.filter.state
        if state is None:
            return self._respond_list_no_state(result)
        state_word = _SEMANTIC_STATE_SPOKEN_DE[state]
        noun = self._noun(result)
        entities = result.entities
        if not entities:
            return f"Es sind keine {noun} {state_word}."
        if len(entities) == 1:
            return f"{entities[0].friendly_name} ist {state_word}."
        if result.command.scope is QueryScope.COUNT:
            return f"{len(entities)} {noun} sind {state_word}."
        return _join_names([e.friendly_name for e in entities]) + f" sind {state_word}."

    def _respond_list_no_state(self, result: QueryResult) -> str:
        """Stateless listing ("Welche Lampen sind im Wohnzimmer?",
        ``QueryFilter.state=None`` - the user-notation's "state=ANY") - area-
        based phrasing instead of state-based, since there is no state word
        to speak."""
        noun = self._noun(result)
        area = result.command.target.area
        where = f" im {area.name}" if area is not None else ""
        entities = result.entities
        if not entities:
            return f"Keine {noun} gefunden{where}."
        if len(entities) == 1:
            return f"{entities[0].friendly_name} ist{where}."
        return _join_names([e.friendly_name for e in entities]) + f" sind{where}."

    def _respond_device_list(self, result: QueryResult) -> str:
        """DEVICE-scope queries (HassDeviceQuery, "welche Geräte sind im
        Büro?") - always has a resolved area (``_parse_device_query`` refuses
        without one before ever building a ``QueryCommand``).

        Follow-up wave, Phase 4: an optional ``filter.state`` ("Welche Geräte
        sind eingeschaltet im Büro?") switches to state-based phrasing,
        mirroring ``_respond_list_or_count``'s state-word branch exactly -
        same wording pattern, just for devices instead of entities."""
        area_name = result.command.target.area.name
        devices = result.devices
        state = result.command.filter.state
        if state is not None:
            state_word = _SEMANTIC_STATE_SPOKEN_DE[state]
            if not devices:
                return f"Im {area_name} sind keine Geräte {state_word}."
            if len(devices) == 1:
                return f"{devices[0].name} ist {state_word}."
            return _join_names([d.name for d in devices]) + f" sind {state_word}."
        if not devices:
            return f"Im {area_name} sind keine Geräte bekannt."
        if len(devices) == 1:
            return f"{devices[0].name} ist im {area_name}."
        return _join_names([d.name for d in devices]) + f" sind im {area_name}."

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
