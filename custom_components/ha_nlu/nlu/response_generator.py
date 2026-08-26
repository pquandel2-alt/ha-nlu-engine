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
from .semantic_state import (
    SemanticState,
    derive_semantic_state,
    evaluate_semantic_state,
)

_SEMANTIC_STATE_SPOKEN_DE = {
    SemanticState.OPEN: "geöffnet",
    SemanticState.CLOSED: "geschlossen",
    SemanticState.ON: "eingeschaltet",
    SemanticState.OFF: "ausgeschaltet",
    SemanticState.ACTIVE: "aktiv",
    SemanticState.INACTIVE: "inaktiv",
}

_DEVICE_CLASS_PLURAL_DE = {
    "window": "Fenster", "door": "Türen", "garage_door": "Garagentore", "motion": "Bewegungsmelder",
}

_DEVICE_CLASS_SINGULAR_DE = {
    "window": "Fenster", "door": "Tür", "garage_door": "Garagentor", "motion": "Bewegungsmelder",
}

_DOMAIN_PLURAL_DE = {
    "light": "Lichter", "switch": "Schalter", "fan": "Ventilatoren",
    "cover": "Rollläden", "climate": "Heizungen", "media_player": "Medienplayer",
    "vacuum": "Saugroboter", "humidifier": "Luftbefeuchter",
    "input_boolean": "Helfer", "valve": "Ventile", "lawn_mower": "Mähroboter",
}
_DOMAIN_SINGULAR_DE = {
    "light": "Licht", "switch": "Schalter", "fan": "Ventilator",
    "cover": "Rollladen", "climate": "Heizung", "media_player": "Medienplayer",
    "vacuum": "Saugroboter", "humidifier": "Luftbefeuchter",
    "input_boolean": "Helfer", "valve": "Ventil", "lawn_mower": "Mähroboter",
}


def _automation_label(automation) -> str:
    """The spoken name for one automation (V5.29) - its own ``source_text``
    (the exact sentence that created it, HomeIntent-made automations only)
    when available, since that's more recognizable to the user than an
    auto-generated ``alias``; falls back to ``alias`` for automations this
    integration didn't create (every HA automation has one, whether made by
    hand in the UI or by HomeIntent - see ``AutomationSummary``'s docstring).
    """
    return automation.source_text or automation.alias


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
        if command.target.kind is QueryTargetKind.AUTOMATION:
            return self._respond_automation(result)
        if command.scope is QueryScope.SINGLE:
            return self._respond_single(result)
        if command.scope is QueryScope.EXISTS:
            return self._respond_exists(result)
        if command.scope is QueryScope.ALL:
            return self._respond_all(result)
        if command.scope is QueryScope.NONE:
            return self._respond_none(result)
        if command.scope is QueryScope.LOCATIONS:
            return self._respond_locations(result)
        return self._respond_list_or_count(result)

    @staticmethod
    def _noun(result: QueryResult) -> str:
        target = result.command.target
        if target.device_class is not None:
            return _DEVICE_CLASS_PLURAL_DE.get(target.device_class, "Geräte")
        return _DOMAIN_PLURAL_DE.get(target.domain, "Geräte")

    @staticmethod
    def _noun_singular(result: QueryResult) -> str:
        target = result.command.target
        if target.device_class is not None:
            return _DEVICE_CLASS_SINGULAR_DE.get(target.device_class, "Gerät")
        return _DOMAIN_SINGULAR_DE.get(target.domain, "Gerät")

    def _respond_list_or_count(self, result: QueryResult) -> str:
        state = result.command.filter.state
        if state is None:
            return self._respond_list_no_state(result)
        state_word = _SEMANTIC_STATE_SPOKEN_DE[state]
        noun = self._noun(result)
        entities = result.entities
        if not entities:
            return f"Es sind keine {noun} {state_word}."
        if result.command.scope is QueryScope.COUNT:
            verb = "ist" if len(entities) == 1 else "sind"
            count_noun = self._noun_singular(result) if len(entities) == 1 else noun
            return f"{len(entities)} {count_noun} {verb} {state_word}."
        if len(entities) == 1:
            return f"{entities[0].friendly_name} ist {state_word}."
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

    def _respond_automation(self, result: QueryResult) -> str:
        """AUTOMATION-scope queries (HassAutomationQuery/HassAutomationWhyQuery,
        V5.29). Three shapes: a bare "welche Automationen gibt es?" listing
        (no ``target.entity_id``), and two entity-filtered phrasings sharing
        the exact same ``QueryResult`` shape but different wording depending
        on ``command.intent`` - HassAutomationQuery's plain "wird gesteuert
        von" vs. HassAutomationWhyQuery's hedged "könnte beeinflusst werden"
        (deliberately non-committal: this only reports automations that
        *mention* the entity somewhere, see ``AutomationSummary``'s
        docstring - it is not a causation proof).
        """
        command = result.command
        labels = [_automation_label(a) for a in result.automations]

        if command.target.entity_id is None:
            if not labels:
                return "Es sind keine Automationen vorhanden."
            return f"Es gibt folgende Automationen: {_join_names(labels)}."

        entity_name = result.entities[0].friendly_name if result.entities else "das"
        causal = command.intent == "HassAutomationWhyQuery"
        if not labels:
            if causal:
                return f"Ich habe keine Automation gefunden, die {entity_name} beeinflussen könnte."
            return f"Ich habe keine Automation gefunden, die {entity_name} steuert."

        joined = _join_names(labels)
        plural = len(labels) > 1
        if causal:
            noun = "Automationen" if plural else "Automation"
            return f"{entity_name} könnte durch folgende {noun} beeinflusst werden: {joined}."
        if plural:
            return f"{entity_name} wird von folgenden Automationen gesteuert: {joined}."
        return f"{entity_name} wird von folgender Automation gesteuert: {joined}."

    def _respond_exists(self, result: QueryResult) -> str:
        noun = self._noun(result)
        if not result.entities:
            return f"Nein, es gibt keine {noun}."
        return f"Ja, es gibt {len(result.entities)} {noun}."

    def _respond_all(self, result: QueryResult) -> str:
        noun = self._noun(result)
        if not result.entities:
            return f"Ich habe keine {noun} gefunden."
        state = result.command.filter.state
        state_word = _SEMANTIC_STATE_SPOKEN_DE[state]
        if result.status is QueryResultStatus.MATCHED:
            return f"Ja, alle {noun} sind {state_word}."
        return f"Nein, nicht alle {noun} sind {state_word}."

    def _respond_none(self, result: QueryResult) -> str:
        noun = self._noun(result)
        if not result.entities:
            return f"Ich habe keine {noun} gefunden."
        state_word = _SEMANTIC_STATE_SPOKEN_DE[result.command.filter.state]
        if result.status is QueryResultStatus.MATCHED:
            return f"Ja, es sind keine {noun} {state_word}."
        return f"Nein, mindestens eines der {noun} ist {state_word}."

    def _respond_locations(self, result: QueryResult) -> str:
        noun = self._noun(result)
        state_word = _SEMANTIC_STATE_SPOKEN_DE[result.command.filter.state]
        areas = sorted({entity.area_name for entity in result.entities if entity.area_name})
        if not areas:
            return f"In keinem bekannten Raum sind {noun} {state_word}."
        if len(areas) == 1:
            return f"Im Raum {areas[0]} sind {noun} {state_word}."
        return f"In {_join_names(areas)} sind {noun} {state_word}."

    @staticmethod
    def _respond_single(result: QueryResult) -> str:
        entity = result.entities[0]
        requested = result.command.filter.state
        if requested is None:
            current = derive_semantic_state(entity)
            if current is SemanticState.UNKNOWN:
                return f"Der Zustand von {entity.friendly_name} ist unbekannt."
            return f"{entity.friendly_name} ist {_SEMANTIC_STATE_SPOKEN_DE[current]}."
        state_word = _SEMANTIC_STATE_SPOKEN_DE[requested]
        evaluation = evaluate_semantic_state(entity, requested)
        if evaluation is None:
            return (
                f"Ob {entity.friendly_name} {state_word} ist, kann ich aus dem "
                f"aktuellen Zustand „{entity.state}“ nicht sicher ableiten."
            )
        if evaluation:
            return f"Ja, {entity.friendly_name} ist {state_word}."
        return f"Nein, {entity.friendly_name} ist nicht {state_word}."
