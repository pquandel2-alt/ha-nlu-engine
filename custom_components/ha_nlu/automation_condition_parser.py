"""AutomationConditionParser (HomeIntent V5 plan, Teil 3/10, V5.4-V5.6):
turns a spoken automation-condition sentence - possibly logically combined
with "und"/"oder"/"nicht", possibly nested in parentheses - into a
``nlu.condition_model.ConditionNode`` tree.

Top-level, hassil-aware - sibling of ``automation_trigger_parser.py``/
``parsers.py``, not part of ``nlu/`` (which stays hassil-/HA-import-free,
see ``nlu/frame.py``'s docstring). Its own separately-compiled ``Intents``
grammar lives under ``intents/de/automation_condition/`` (9 YAML files, one
per ``ConditionType``), loaded the same way ``automation_trigger_parser.py``
loads its own 7. No caller in ``engine.py``/``conversation.py`` in this
wave either - same "HA-Schreibzugriff: erst nach explizitem Go" scope
decision Wave 1 already made.

Two layers, per the plan:

1. A pure-Python boolean-expression layer (no hassil) - ``_tokenize()``
   splits the raw text on 5 structural tokens (``(``, ``)``, "und", "oder",
   "nicht"), all ``\\b``-word-boundary-anchored so "Grund"/"Sekunde"/
   "München" are never mis-split (neither side of "und"/"nicht" inside
   those words is itself a word boundary, so ``\\bund\\b``/``\\bnicht\\b``
   never matches inside them). Everything between structural tokens is an
   untouched leaf text span. A recursive-descent parser on top gives NOT
   (unary, tightest) > AND > OR (loosest) precedence - standard
   programming-language convention (confirmed via AskUserQuestion) -
   explicit parentheses are the only way to override it.
2. Leaf parsing via hassil: each leaf text span goes to ``_parse_leaf()``,
   which runs ``recognize()`` against **one** ``Intents`` object built from
   all 9 ``automation_condition/*.yaml`` grammars and dispatches on
   ``result.intent.name`` - the exact same "one Intents object, one
   dispatch dict" shape ``AutomationTriggerParser.parse()`` already
   established.

Reuses existing resolvers/vocabulary throughout (Regel 6) rather than
inventing new ones - see the per-``_parse_*_condition`` methods below for
which piece of ``areas.py``/``entities.py``/``constraint_resolver.py``/
``parsers.py``/``world_model.py`` each condition type reuses. Mirrors
``AutomationTriggerParser``'s own ``_resolve_area``/
``_build_device_class_target``/``_build_named_target`` helpers structurally
(architectural precedent, Wave 1 is the direct model) rather than importing
them - they are thin, condition-vs-trigger-agnostic wrappers around shared
primitives, not a parallel resolution system.
"""

from __future__ import annotations

import re
from pathlib import Path

from hassil import Intents, RangeSlotList, RangeType, WildcardSlotList, recognize

from .areas import AreaResolutionStatus, resolve_area_scored
from .entities import EntitySnapshot, ResolutionStatus, resolve_entity_scored
from .nlu.automation_model import NumericComparator, SunEvent, TriggerTarget
from .nlu.condition_model import ConditionModel, ConditionNode, ConditionType, LogicalOperator, TimeComparator, condition_tree_depth
from .nlu.constraint_resolver import Constraints, resolve_candidates
from .nlu.lexicon import (
    _COMPARATOR_SLOT_LIST,
    _DAY_PART_WINDOW_SLOT_LIST,
    _DEVICE_CLASS_SLOT_LIST,
    _MONTH_SLOT_LIST,
    _NUMERIC_UNIT_SLOT_LIST,
    _PRESENCE_STATE_SLOT_LIST,
    _RAW_ENTITY_STATE_SLOT_LIST,
    _STATE_SLOT_LIST,
    _STATE_VERB_SLOT_LIST,
    _SUN_EVENT_SLOT_LIST,
    _TIME_OFFSET_DIRECTION_SLOT_LIST,
    _WEEKDAY_SLOT_LIST,
)
from .nlu.parser import ParseContext
from .parsers import StateQueryParser, _STATE_NAME_TO_SEMANTIC, _strip_locative_prepositions

AUTOMATION_CONDITION_DIR = Path(__file__).parent / "intents" / "de" / "automation_condition"

# V5 Wave 5 (V5.18, "Context in Automations") - same closed pronoun set
# ``automation_trigger_parser.py`` establishes (Regel 6, not a second
# vocabulary).
_PRONOUN_WORDS = frozenset({"es"})

# \b-anchored so "Grund"/"Sekunde"/"München" are never mis-split - neither
# side of the embedded "und"/"nicht" substring in those words is itself a
# word boundary (both neighbouring characters are word characters), so the
# \b assertions on both ends of each alternative never match inside them.
_STRUCTURAL_TOKEN_RE = re.compile(r"\(|\)|\bund\b|\boder\b|\bnicht\b", re.IGNORECASE)

# V5 Wave 4 (V5.15, "Time Windows") - "zwischen {hour} und {hour2} Uhr" has
# its own embedded "und" that _STRUCTURAL_TOKEN_RE would otherwise split on
# (producing two malformed leaves, "zwischen 18" AND "22 Uhr", instead of one
# HassTimeWindowCondition leaf). Masked before _tokenize() ever sees the
# text, unmasked again in _parse_leaf() right before the hassil-level
# recognize() call (which needs the literal "und" back to match
# time_window_condition.yaml's own "{hour} und {hour2}" sentence) - the
# boolean-expression layer only ever sees the masked marker, never the real
# word, so it can't misinterpret it as a second top-level "und".
_TIME_WINDOW_SPAN_RE = re.compile(r"\bzwischen\b.*?\buhr\b", re.IGNORECASE)
_TIME_WINDOW_AND_MARKER = "UNDZWISCHENMARKER"


def _mask_time_window_and(text: str) -> str:
    def _mask_span(match: re.Match[str]) -> str:
        return re.sub(r"\bund\b", _TIME_WINDOW_AND_MARKER, match.group(0), count=1, flags=re.IGNORECASE)

    return _TIME_WINDOW_SPAN_RE.sub(_mask_span, text)


def _unmask_time_window_and(text: str) -> str:
    return re.sub(_TIME_WINDOW_AND_MARKER, "und", text, flags=re.IGNORECASE)


def _tokenize(text: str) -> list[tuple[str, str]]:
    """Splits ``text`` into structural tokens (``LPAREN``/``RPAREN``/``AND``/
    ``OR``/``NOT``) and the untouched leaf text spans (``TEXT``) between
    them - the input to the recursive-descent parser below."""
    tokens: list[tuple[str, str]] = []
    pos = 0
    for match in _STRUCTURAL_TOKEN_RE.finditer(text):
        leaf_text = text[pos : match.start()].strip()
        if leaf_text:
            tokens.append(("TEXT", leaf_text))
        token_text = match.group(0)
        if token_text == "(":
            tokens.append(("LPAREN", token_text))
        elif token_text == ")":
            tokens.append(("RPAREN", token_text))
        elif token_text.lower() == "und":
            tokens.append(("AND", token_text))
        elif token_text.lower() == "oder":
            tokens.append(("OR", token_text))
        else:
            tokens.append(("NOT", token_text))
        pos = match.end()
    trailing = text[pos:].strip()
    if trailing:
        tokens.append(("TEXT", trailing))
    return tokens


class _TokenCursor:
    """Minimal single-pass cursor over the token list - no lookahead beyond
    one token is ever needed by the recursive-descent parser below."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._pos = 0

    def peek(self) -> tuple[str, str] | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def advance(self) -> tuple[str, str] | None:
        token = self.peek()
        self._pos += 1
        return token


class AutomationConditionParser:
    """Wraps the 9 ``intents/de/automation_condition/*.yaml`` grammars (one
    ``Intents`` object, 9 intents) plus the boolean-expression layer around
    them. ``parse()`` is the sole public entry point - even a single
    condition with no "und"/"oder"/"nicht" comes back as a depth-1 leaf
    ``ConditionNode``, never a separate union type.
    """

    def __init__(self, intents: Intents, max_depth: int = 3) -> None:
        self._intents = intents
        self._max_depth = max_depth
        self._slot_lists = {
            "device_class": _DEVICE_CLASS_SLOT_LIST,
            "area": WildcardSlotList(name="area"),
            "name": WildcardSlotList(name="name"),
            "state": _STATE_SLOT_LIST,
            "state_verb": _STATE_VERB_SLOT_LIST,
            "comparator": _COMPARATOR_SLOT_LIST,
            # words=False (hassil default True): mirrors
            # AutomationTriggerParser's own {threshold} - a 0-5000 range is
            # too wide to also spell out in words.
            "threshold": RangeSlotList(name="threshold", start=0, stop=5000, step=1, type=RangeType.NUMBER, words=False),
            "numeric_unit": _NUMERIC_UNIT_SLOT_LIST,
            "time_comparator": _TIME_OFFSET_DIRECTION_SLOT_LIST,
            "sun_comparator": _TIME_OFFSET_DIRECTION_SLOT_LIST,
            "hour": RangeSlotList(name="hour", start=0, stop=23, step=1, type=RangeType.NUMBER),
            "minute": RangeSlotList(name="minute", start=0, stop=59, step=1, type=RangeType.NUMBER),
            # V5 Wave 4 (V5.15, "Time Windows") - {hour2} is a second,
            # independent instance of the same 0-23 range, only ever used
            # together with {hour} in time_window_condition.yaml's
            # "zwischen {hour} und {hour2} Uhr" sentence (same "two distinct
            # slot names for two positions of the same vocabulary" precedent
            # AutomationTriggerParser's own {weekday2} already established).
            "hour2": RangeSlotList(name="hour2", start=0, stop=23, step=1, type=RangeType.NUMBER),
            "day_part_window": _DAY_PART_WINDOW_SLOT_LIST,
            # words=True default kept (plan's own note): 1-31 is a small
            # range, comparable to other small existing RangeSlotLists.
            "day_of_month": RangeSlotList(name="day_of_month", start=1, stop=31, step=1, type=RangeType.NUMBER),
            "month": _MONTH_SLOT_LIST,
            "weekday": _WEEKDAY_SLOT_LIST,
            "sun_event": _SUN_EVENT_SLOT_LIST,
            "offset": RangeSlotList(name="offset", start=0, stop=120, step=1, type=RangeType.NUMBER),
            "presence_state": _PRESENCE_STATE_SLOT_LIST,
            "raw_state": _RAW_ENTITY_STATE_SLOT_LIST,
            # "daylight"/"device_condition_type" are declared inline in
            # their own grammar files' "lists:" sections (sun_condition.yaml/
            # device_condition.yaml), not here - recognize() merges
            # intents.slot_lists with this dict automatically.
        }
        self._dispatch = {
            "HassStateCondition": self._parse_state_condition,
            "HassNumericCondition": self._parse_numeric_condition,
            "HassTimeCondition": self._parse_time_condition,
            "HassTimeWindowCondition": self._parse_time_window_condition,
            "HassDateCondition": self._parse_date_condition,
            "HassWeekdayCondition": self._parse_weekday_condition,
            "HassSunCondition": self._parse_sun_condition,
            "HassPresenceCondition": self._parse_presence_condition,
            "HassDeviceCondition": self._parse_device_condition,
            "HassEntityCondition": self._parse_entity_condition,
        }

    def parse(self, text: str, context: ParseContext) -> ConditionNode | None:
        tokens = _tokenize(_mask_time_window_and(text))
        if not tokens:
            return None
        cursor = _TokenCursor(tokens)
        root = self._parse_or(cursor, context)
        if root is None:
            return None
        if cursor.peek() is not None:
            return None  # leftover tokens (e.g. a dangling ")") - malformed expression
        if condition_tree_depth(root) > self._max_depth:
            return None  # Post-validation on the fully-built tree (see module docstring) - never a live counter
        return root

    # -- boolean-expression layer (precedence: NOT > AND > OR) ----------------

    def _parse_or(self, cursor: _TokenCursor, context: ParseContext) -> ConditionNode | None:
        left = self._parse_and(cursor, context)
        if left is None:
            return None
        children = [left]
        while cursor.peek() is not None and cursor.peek()[0] == "OR":
            cursor.advance()
            right = self._parse_and(cursor, context)
            if right is None:
                return None
            children.append(right)
        if len(children) == 1:
            return children[0]
        return ConditionNode(operator=LogicalOperator.OR, children=tuple(children))

    def _parse_and(self, cursor: _TokenCursor, context: ParseContext) -> ConditionNode | None:
        left = self._parse_not(cursor, context)
        if left is None:
            return None
        children = [left]
        while cursor.peek() is not None and cursor.peek()[0] == "AND":
            cursor.advance()
            right = self._parse_not(cursor, context)
            if right is None:
                return None
            children.append(right)
        if len(children) == 1:
            return children[0]
        return ConditionNode(operator=LogicalOperator.AND, children=tuple(children))

    def _parse_not(self, cursor: _TokenCursor, context: ParseContext) -> ConditionNode | None:
        if cursor.peek() is not None and cursor.peek()[0] == "NOT":
            cursor.advance()
            child = self._parse_not(cursor, context)
            if child is None:
                return None
            return ConditionNode(operator=LogicalOperator.NOT, children=(child,))
        return self._parse_atom(cursor, context)

    def _parse_atom(self, cursor: _TokenCursor, context: ParseContext) -> ConditionNode | None:
        token = cursor.peek()
        if token is None:
            return None
        kind, value = token
        if kind == "LPAREN":
            cursor.advance()
            node = self._parse_or(cursor, context)
            if node is None:
                return None
            closing = cursor.advance()
            if closing is None or closing[0] != "RPAREN":
                return None  # unbalanced parentheses - malformed, refuse
            return node
        if kind == "TEXT":
            cursor.advance()
            return self._parse_leaf(value, context)
        return None  # a stray ")"/AND/OR/NOT with no operand - malformed, refuse

    # -- leaf parsing via hassil -----------------------------------------------

    def _parse_leaf(self, text: str, context: ParseContext) -> ConditionNode | None:
        text = _unmask_time_window_and(text)
        result = recognize(text, self._intents, slot_lists=self._slot_lists, language="de")
        if result is None or result.intent is None:
            return None
        handler = self._dispatch.get(result.intent.name)
        if handler is None:
            return None
        return handler(result.entities, context)

    # -- shared helpers (architectural precedent: AutomationTriggerParser) ----

    @staticmethod
    def _resolve_area(slots: dict, entities: list[EntitySnapshot]) -> tuple[str | None, str | None] | None:
        area_slot = slots.get("area")
        if area_slot is None:
            return None, None
        area_text = _strip_locative_prepositions(str(area_slot.value))
        if not area_text:
            return None, None
        resolved = resolve_area_scored(area_text, entities)
        if resolved.status is not AreaResolutionStatus.RESOLVED or resolved.area is None:
            return None  # named but not a known/unambiguous room - never guess
        return resolved.area.area_id, resolved.area.name

    def _build_device_class_target(self, device_class_value: str, slots: dict, context: ParseContext) -> TriggerTarget | None:
        resolved_area = self._resolve_area(slots, context.entities)
        if resolved_area is None:
            return None
        area_id, _area_name = resolved_area
        domain, device_class, _candidates = StateQueryParser._device_class_candidates(
            device_class_value, context.entities, area_id
        )
        return TriggerTarget(domain=domain, device_class=device_class, area_id=area_id)

    @staticmethod
    def _build_pronoun_target(context: ParseContext) -> TriggerTarget | None:
        """V5 Wave 5 (V5.18) - mirrors ``AutomationTriggerParser``'s own
        ``_build_pronoun_target`` byte-for-byte (Regel 6, same architectural
        precedent every other shared helper in this file already follows -
        see the module docstring). "es" resolves against
        ``context.last_entities``; refuses on nothing remembered or a mixed
        remembered set."""
        last_entities = context.last_entities
        if not last_entities:
            return None
        if len(last_entities) == 1:
            entity = last_entities[0]
            candidates = resolve_candidates(
                context.entities,
                Constraints(domain=entity.domain, device_class=entity.device_class, area_id=entity.area_id),
            )
            if len(candidates) == 1:
                return TriggerTarget(domain=entity.domain, device_class=entity.device_class, area_id=entity.area_id)
            return TriggerTarget(
                domain=entity.domain,
                device_class=entity.device_class,
                area_id=entity.area_id,
                entity_id=entity.entity_id,
            )
        domains = {e.domain for e in last_entities}
        device_classes = {e.device_class for e in last_entities}
        area_ids = {e.area_id for e in last_entities}
        if len(domains) != 1 or len(device_classes) != 1 or len(area_ids) != 1:
            return None
        return TriggerTarget(domain=next(iter(domains)), device_class=next(iter(device_classes)), area_id=next(iter(area_ids)))

    @staticmethod
    def _build_named_target(name_slot, context: ParseContext) -> TriggerTarget | None:
        name = _strip_locative_prepositions(str(name_slot.value))
        if name.strip().lower() in _PRONOUN_WORDS:
            return AutomationConditionParser._build_pronoun_target(context)
        resolved = resolve_entity_scored(name, context.entities, index=context.index)
        if resolved.status is not ResolutionStatus.RESOLVED or resolved.entity is None:
            return None  # not found or ambiguous - never guess (Regel 4)
        entity = resolved.entity

        # Same semantic-equivalence recheck AutomationTriggerParser's own
        # _build_named_target documents: entity_id only stays set when the
        # spoken name did real disambiguation beyond domain/device_class/area.
        candidates = resolve_candidates(
            context.entities,
            Constraints(domain=entity.domain, device_class=entity.device_class, area_id=entity.area_id),
        )
        if len(candidates) == 1:
            return TriggerTarget(domain=entity.domain, device_class=entity.device_class, area_id=entity.area_id)
        return TriggerTarget(
            domain=entity.domain,
            device_class=entity.device_class,
            area_id=entity.area_id,
            entity_id=entity.entity_id,
        )

    # -- per-intent leaf parsing ------------------------------------------------

    def _parse_state_condition(self, slots: dict, context: ParseContext) -> ConditionNode | None:
        state_slot = slots.get("state")
        state_verb_slot = slots.get("state_verb")
        if state_slot is not None:
            semantic_state = _STATE_NAME_TO_SEMANTIC[str(state_slot.value)]
        elif state_verb_slot is not None:
            semantic_state = _STATE_NAME_TO_SEMANTIC[str(state_verb_slot.value)]
        else:
            return None  # structurally unreachable - HassStateCondition's grammar always captures one of the two

        device_class_slot = slots.get("device_class")
        if device_class_slot is not None:
            target = self._build_device_class_target(str(device_class_slot.value), slots, context)
        else:
            name_slot = slots.get("name")
            if name_slot is None:
                return None
            target = self._build_named_target(name_slot, context)
        if target is None:
            return None
        condition = ConditionModel(type=ConditionType.STATE, target=target, state=semantic_state)
        return ConditionNode(condition=condition)

    def _parse_numeric_condition(self, slots: dict, context: ParseContext) -> ConditionNode | None:
        name_slot = slots.get("name")
        comparator_slot = slots.get("comparator")
        threshold_slot = slots.get("threshold")
        if name_slot is None or comparator_slot is None or threshold_slot is None:
            return None

        comparator_value = str(comparator_slot.value)
        if comparator_value == "gt":
            comparator = NumericComparator.ABOVE
        elif comparator_value == "lt":
            comparator = NumericComparator.BELOW
        else:
            # "gte"/"lte" still match {comparator} (shared _COMPARATOR_SLOT_LIST)
            # but HA's numeric condition has no inclusive comparator - refuse,
            # never guess an approximation (same precedent numeric_state
            # trigger's own comment documents).
            return None

        target = self._build_named_target(name_slot, context)
        if target is None:
            return None

        unit_slot = slots.get("numeric_unit")
        unit = str(unit_slot.value) if unit_slot is not None else None
        condition = ConditionModel(
            type=ConditionType.NUMERIC, target=target, comparator=comparator, threshold=float(threshold_slot.value), unit=unit
        )
        return ConditionNode(condition=condition)

    @staticmethod
    def _parse_time_condition(slots: dict, context: ParseContext) -> ConditionNode | None:
        hour_slot = slots.get("hour")
        comparator_slot = slots.get("time_comparator")
        if hour_slot is None or comparator_slot is None:
            return None
        minute_slot = slots.get("minute")
        minute = int(minute_slot.value) if minute_slot is not None else 0
        time_comparator = TimeComparator.BEFORE if str(comparator_slot.value) == "before" else TimeComparator.AFTER
        condition = ConditionModel(
            type=ConditionType.TIME, time_hour=int(hour_slot.value), time_minute=minute, time_comparator=time_comparator
        )
        return ConditionNode(condition=condition)

    @staticmethod
    def _build_time_window_node(start_hour: int, end_hour: int) -> ConditionNode:
        """"zwischen 18 und 22 Uhr" -> two TIME leaves (after start, before
        end). Non-wrapping windows (start <= end, the common case) compose
        as AND - both must hold. Wrapping windows (start > end, e.g.
        "nachts" 22->6) must compose as OR: AND(after 22, before 6) is
        permanently false (no hour is both >= 22 and < 6), whereas OR(after
        22, before 6) correctly matches 22:00-23:59 and 00:00-05:59 - see
        lexicon.py's _DAY_PART_WINDOW_SLOT_LIST docstring for the same point.
        """
        after = ConditionModel(type=ConditionType.TIME, time_hour=start_hour, time_minute=0, time_comparator=TimeComparator.AFTER)
        before = ConditionModel(type=ConditionType.TIME, time_hour=end_hour, time_minute=0, time_comparator=TimeComparator.BEFORE)
        after_node = ConditionNode(condition=after)
        before_node = ConditionNode(condition=before)
        operator = LogicalOperator.AND if start_hour <= end_hour else LogicalOperator.OR
        return ConditionNode(operator=operator, children=(after_node, before_node))

    @staticmethod
    def _parse_time_window_condition(slots: dict, context: ParseContext) -> ConditionNode | None:
        day_part_slot = slots.get("day_part_window")
        if day_part_slot is not None:
            start_str, end_str = str(day_part_slot.value).split(",")
            window_node = AutomationConditionParser._build_time_window_node(int(start_str), int(end_str))
        else:
            hour_slot = slots.get("hour")
            hour2_slot = slots.get("hour2")
            if hour_slot is None or hour2_slot is None:
                return None
            window_node = AutomationConditionParser._build_time_window_node(int(hour_slot.value), int(hour2_slot.value))

        # "werktags zwischen 7 und 9 Uhr" - an optional {weekday} slot on the
        # same leaf (see time_window_condition.yaml's own compound sentence)
        # composes as a further AND, reusing ConditionType.WEEKDAY verbatim
        # (Regel 6) rather than inventing a combined condition type.
        weekday_slot = slots.get("weekday")
        if weekday_slot is None:
            return window_node
        weekday_condition = ConditionModel(type=ConditionType.WEEKDAY, weekdays=tuple(str(weekday_slot.value).split(",")))
        weekday_node = ConditionNode(condition=weekday_condition)
        return ConditionNode(operator=LogicalOperator.AND, children=(weekday_node, window_node))

    @staticmethod
    def _parse_date_condition(slots: dict, context: ParseContext) -> ConditionNode | None:
        day_slot = slots.get("day_of_month")
        month_slot = slots.get("month")
        if day_slot is None or month_slot is None:
            return None
        condition = ConditionModel(type=ConditionType.DATE, date_day=int(day_slot.value), date_month=int(month_slot.value))
        return ConditionNode(condition=condition)

    @staticmethod
    def _parse_weekday_condition(slots: dict, context: ParseContext) -> ConditionNode | None:
        weekday_slot = slots.get("weekday")
        if weekday_slot is None:
            return None
        weekdays = tuple(str(weekday_slot.value).split(","))
        condition = ConditionModel(type=ConditionType.WEEKDAY, weekdays=weekdays)
        return ConditionNode(condition=condition)

    @staticmethod
    def _parse_sun_condition(slots: dict, context: ParseContext) -> ConditionNode | None:
        daylight_slot = slots.get("daylight")
        if daylight_slot is not None:
            # "es ist dunkel/hell" - modeled as "after sunset"/"after
            # sunrise" (see sun_condition.yaml's own comment on this
            # judgment call).
            sun_event = SunEvent.SUNSET if str(daylight_slot.value) == "dark" else SunEvent.SUNRISE
            condition = ConditionModel(type=ConditionType.SUN, sun_event=sun_event, sun_comparator=TimeComparator.AFTER)
            return ConditionNode(condition=condition)

        event_slot = slots.get("sun_event")
        if event_slot is None:
            return None
        sun_event = SunEvent.SUNRISE if str(event_slot.value) == "sunrise" else SunEvent.SUNSET

        comparator_slot = slots.get("sun_comparator")
        sun_comparator = None
        if comparator_slot is not None:
            sun_comparator = TimeComparator.BEFORE if str(comparator_slot.value) == "before" else TimeComparator.AFTER

        offset_slot = slots.get("offset")
        offset_minutes = int(offset_slot.value) if offset_slot is not None else None

        condition = ConditionModel(
            type=ConditionType.SUN, sun_event=sun_event, sun_comparator=sun_comparator, offset_minutes=offset_minutes
        )
        return ConditionNode(condition=condition)

    @staticmethod
    def _parse_presence_condition(slots: dict, context: ParseContext) -> ConditionNode | None:
        name_slot = slots.get("name")
        presence_slot = slots.get("presence_state")

        if name_slot is None and presence_slot is None:
            # "niemand [mehr] zuhause [ist]" - lexical negation (architecture
            # addendum): built here as a NOT-wrapped node, the expression
            # parser itself stays unaware which leaf grammars have built-in
            # negation.
            home_condition = ConditionModel(type=ConditionType.PRESENCE, raw_state="home")
            return ConditionNode(operator=LogicalOperator.NOT, children=(ConditionNode(condition=home_condition),))

        if presence_slot is None:
            return None  # structurally unreachable - every non-"niemand" sentence captures {presence_state}
        # ConditionModel has no dedicated presence-state field (only
        # ``raw_state`` is a free-form closed-vocabulary string) - reused
        # here for "home"/"not_home" rather than inventing a 19th field.
        raw_state = str(presence_slot.value)

        target = None
        if name_slot is not None:
            name = _strip_locative_prepositions(str(name_slot.value))
            resolved = resolve_entity_scored(name, context.entities, domain="person", index=context.index)
            if resolved.status is not ResolutionStatus.RESOLVED or resolved.entity is None:
                return None
            if resolved.entity.domain != "person":
                return None  # named entity resolved, but isn't a person - never guess
            target = TriggerTarget(domain="person", entity_id=resolved.entity.entity_id)

        condition = ConditionModel(type=ConditionType.PRESENCE, target=target, raw_state=raw_state)
        return ConditionNode(condition=condition)

    @staticmethod
    def _parse_device_condition(slots: dict, context: ParseContext) -> ConditionNode | None:
        name_slot = slots.get("name")
        type_slot = slots.get("device_condition_type")
        if name_slot is None or type_slot is None:
            return None
        if context.world_model is None:
            return None  # no entity->device mapping available - never guess a device_id

        name = _strip_locative_prepositions(str(name_slot.value))
        resolved = resolve_entity_scored(name, context.entities, index=context.index)
        if resolved.status is not ResolutionStatus.RESOLVED or resolved.entity is None:
            return None
        device = context.world_model.device_for_entity(resolved.entity.entity_id)
        if device is None:
            return None
        condition = ConditionModel(
            type=ConditionType.DEVICE, device_id=device.device_id, device_condition_type=str(type_slot.value)
        )
        return ConditionNode(condition=condition)

    @staticmethod
    def _parse_entity_condition(slots: dict, context: ParseContext) -> ConditionNode | None:
        name_slot = slots.get("name")
        raw_state_slot = slots.get("raw_state")
        if name_slot is None or raw_state_slot is None:
            return None

        name = _strip_locative_prepositions(str(name_slot.value))
        resolved = resolve_entity_scored(name, context.entities, index=context.index)
        if resolved.status is not ResolutionStatus.RESOLVED or resolved.entity is None:
            return None  # not found or ambiguous - never guess
        entity = resolved.entity

        # entity_id is mandatory for ENTITY (unlike STATE/NUMERIC's
        # device_class+area target) - the spoken name must resolve to
        # exactly one candidate.
        target = TriggerTarget(
            domain=entity.domain, device_class=entity.device_class, area_id=entity.area_id, entity_id=entity.entity_id
        )
        condition = ConditionModel(type=ConditionType.ENTITY, target=target, raw_state=str(raw_state_slot.value))
        return ConditionNode(condition=condition)
