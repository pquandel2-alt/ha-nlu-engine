"""Deterministic, compositional language support for lists and timers.

The parser deliberately extracts operation, target and payload separately.
Consequently word order may vary without maintaining one full sentence
template per formulation.  It remains local, inspectable and LLM-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum, auto

from .entities import EntitySnapshot, normalize_for_compare
from .nlu.entity_clarification import CandidateReplyKind, resolve_candidate_reply
from .nlu.language_frontend import LanguageDocument


class TodoOperation(Enum):
    ADD = auto()
    LIST = auto()
    COMPLETE = auto()
    REMOVE = auto()
    CLEAR_COMPLETED = auto()
    MOVE = auto()


class TimerOperation(Enum):
    START = auto()
    CHANGE = auto()
    PAUSE = auto()
    RESUME = auto()
    CANCEL = auto()
    FINISH = auto()
    STATUS = auto()


@dataclass(frozen=True)
class TodoRequest:
    operation: TodoOperation
    items: tuple[str, ...] = ()
    entity_id: str | None = None
    candidates: tuple[EntitySnapshot, ...] = ()
    due_date: str | None = None
    description: str | None = None
    priority: str | None = None
    destination_entity_id: str | None = None


@dataclass(frozen=True)
class TimerRequest:
    operation: TimerOperation
    duration_seconds: int | None = None
    change_seconds: int | None = None
    entity_id: str | None = None
    candidates: tuple[EntitySnapshot, ...] = ()


ProductivityRequest = TodoRequest | TimerRequest

_TODO_NOUN_RE = re.compile(
    r"\b(?:einkaufslisten?|einkaufszettel|todo(?:listen?)?|to-do(?:-listen?)?|"
    r"aufgabenlisten?|listen?)\b", re.IGNORECASE
)
_TIMER_NOUN_RE = re.compile(
    r"\b(?:[a-zäöüß]*timer|zeitmesser|countdown|kurzzeitwecker)\b", re.IGNORECASE
)
_ADD_RE = re.compile(
    r"\b(?:füg(?:e|t)|fueg(?:e|t)|hinzufügen|hinzufuegen|setz(?:e|t)?|"
    r"schreib(?:e|t)?|pack(?:e|t)?|notier(?:e|t)?|trag(?:e|t)?)\b", re.IGNORECASE
)
_LIST_RE = re.compile(
    r"\b(?:zeig(?:e|t)?|lies|lese|nenne|was\s+(?:steht|ist|fehlt)|welche\s+(?:sachen|dinge|"
    r"artikel|einträge|eintraege|punkte))\b", re.IGNORECASE
)
_COMPLETE_RE = re.compile(
    r"\b(?:erledig(?:e|t|en)|hak(?:e|t)?\s+ab|abhaken|markier(?:e|t)?(?:\s+als\s+erledigt)?)\b",
    re.IGNORECASE,
)
_REMOVE_RE = re.compile(
    r"\b(?:entfern(?:e|t|en)|lösch(?:e|t|en)|loesch(?:e|t|en)|streich(?:e|t|en))\b",
    re.IGNORECASE,
)
_CLEAR_COMPLETED_RE = re.compile(
    r"\b(?:alle\s+)?erledigten?\b.*\b(?:entfern|lösch|loesch|aufräum|aufraeum|weg)",
    re.IGNORECASE,
)
_PREPOSITION_RE = re.compile(
    r"\b(?:auf|in|zu|zur|von|aus)\s+(?:(?:die|der|den|meine[rmn]?)\s+)?",
    re.IGNORECASE,
)
_LEADING_FILLER_RE = re.compile(
    r"^(?:bitte\s+|doch\s+|mal\s+|noch\s+|mir\s+|für\s+mich\s+|fuer\s+mich\s+)+",
    re.IGNORECASE,
)
_TRAILING_FILLER_RE = re.compile(
    r"\s+(?:bitte|hinzu|dazu|drauf|darauf|rein|ein)\s*$", re.IGNORECASE
)
_ARTICLE_RE = re.compile(r"^(?:die|der|das|den|dem|ein|eine|einen)\s+", re.IGNORECASE)
_ITEM_SEPARATOR_RE = re.compile(r"\s*(?:[,;]|\bund\b|\bsowie\b|\baußerdem\b|\bausserdem\b)\s*", re.IGNORECASE)

_NUMBER_WORDS = {
    "null": 0, "ein": 1, "eins": 1, "eine": 1, "einen": 1,
    "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "fuenf": 5,
    "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "elf": 11, "zwölf": 12, "zwoelf": 12, "dreizehn": 13,
    "vierzehn": 14, "fünfzehn": 15, "fuenfzehn": 15,
    "sechzehn": 16, "siebzehn": 17, "achtzehn": 18,
    "neunzehn": 19, "zwanzig": 20, "dreißig": 30, "dreissig": 30,
    "vierzig": 40, "fünfzig": 50, "fuenfzig": 50, "sechzig": 60,
}
_DURATION_PART_RE = re.compile(
    r"\b(\d+|[a-zäöüß]+)\s*(stunden?|std\.?|h|minuten?|min\.?|sekunden?|sek\.?)\b",
    re.IGNORECASE,
)
_MOVE_RE = re.compile(r"\bverschieb(?:e|en|t)?\b", re.IGNORECASE)
_DESCRIPTION_RE = re.compile(
    r"\bmit\s+(?:der\s+)?beschreibung\s+(.+?)(?=\s+\b(?:bis|mit\s+priorität|mit\s+prioritaet|"
    r"auf|in|zu|zur)\b|[.!?]?$)", re.IGNORECASE
)
_PRIORITY_RE = re.compile(
    r"\b(?:mit\s+)?(?:priorität|prioritaet)\s+(hoch|mittel|niedrig)\b", re.IGNORECASE
)
_DUE_RE = re.compile(
    r"\bbis\s+(heute|morgen|übermorgen|uebermorgen|montag|dienstag|mittwoch|"
    r"donnerstag|freitag|samstag|sonntag|\d{1,2}\.\d{1,2}\.(?:\d{2,4})?)\b",
    re.IGNORECASE,
)
_WEEKDAYS = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonntag": 6,
}


def _entity_names(entity: EntitySnapshot) -> tuple[str, ...]:
    return (entity.friendly_name, *entity.aliases, entity.entity_id.split(".", 1)[1].replace("_", " "))


def _mentioned_entities(text: str, entities: tuple[EntitySnapshot, ...]) -> tuple[EntitySnapshot, ...]:
    normalized = normalize_for_compare(text)
    exact: list[EntitySnapshot] = []
    for entity in entities:
        for name in _entity_names(entity):
            candidate = normalize_for_compare(name)
            if candidate and re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", normalized):
                exact.append(entity)
                break
    unique: dict[str, EntitySnapshot] = {}
    for entity in exact:
        unique.setdefault(entity.entity_id, entity)
    return tuple(unique.values())


def _select_target(
    text: str, entities: list[EntitySnapshot], domain: str
) -> tuple[str | None, tuple[EntitySnapshot, ...]]:
    available = tuple(entity for entity in entities if entity.domain == domain)
    if not available:
        return None, ()
    mentioned = _mentioned_entities(text, available)
    if len(mentioned) == 1:
        return mentioned[0].entity_id, ()
    if mentioned:
        return None, mentioned
    if domain == "todo" and re.search(r"\beinkauf", text, re.IGNORECASE):
        shopping = tuple(
            entity for entity in available
            if "einkauf" in normalize_for_compare(entity.friendly_name)
            or any("einkauf" in normalize_for_compare(alias) for alias in entity.aliases)
        )
        if len(shopping) == 1:
            return shopping[0].entity_id, ()
        if shopping:
            return None, shopping
    if len(available) == 1:
        return available[0].entity_id, ()
    return None, available


def _clean_payload(raw: str) -> str:
    value = raw.strip(" \t.,;:!?")
    value = _LEADING_FILLER_RE.sub("", value)
    value = _TRAILING_FILLER_RE.sub("", value)
    return value.strip(" \t.,;:!?")


def split_todo_items(raw: str) -> tuple[str, ...]:
    """Split one spoken payload into independently stored todo items."""
    result: list[str] = []
    seen: set[str] = set()
    for part in _ITEM_SEPARATOR_RE.split(_clean_payload(raw)):
        item = _ARTICLE_RE.sub("", part.strip(" \t.,;:!?"))
        item = re.sub(r"\s+", " ", item).strip()
        key = normalize_for_compare(item)
        if not item or len(item) > 100 or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result[:20])


def _todo_payload(text: str, operation_match: re.Match[str]) -> str:
    """Remove operation and list-target phrases, preserving only item text."""
    spans = [operation_match.span()]
    for noun in _TODO_NOUN_RE.finditer(text):
        start, end = noun.span()
        prefix = list(_PREPOSITION_RE.finditer(text[:start]))
        if prefix and prefix[-1].end() == start:
            start = prefix[-1].start()
        spans.append((start, end))
    value = text
    for start, end in sorted(spans, reverse=True):
        value = value[:start] + " " + value[end:]
    value = re.sub(r"\b(?:als\s+erledigt|ab)\b", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:soll(?:en)?|möchte|moechte|ich|du|kannst)\b", " ", value, flags=re.IGNORECASE)
    return _clean_payload(re.sub(r"\s+", " ", value))


def _extract_todo_metadata(
    text: str, now: datetime | None
) -> tuple[str, str | None, str | None, str | None]:
    description_match = _DESCRIPTION_RE.search(text)
    priority_match = _PRIORITY_RE.search(text)
    due_match = _DUE_RE.search(text)
    description = (
        description_match.group(1).strip(" ,.!?") if description_match else None
    )
    priority = priority_match.group(1).casefold() if priority_match else None
    due_date: str | None = None
    if due_match and now is not None:
        raw = due_match.group(1).casefold()
        if raw == "heute":
            target = now.date()
        elif raw == "morgen":
            target = now.date() + timedelta(days=1)
        elif raw in {"übermorgen", "uebermorgen"}:
            target = now.date() + timedelta(days=2)
        elif raw in _WEEKDAYS:
            days = (_WEEKDAYS[raw] - now.weekday()) % 7 or 7
            target = now.date() + timedelta(days=days)
        else:
            day, month, year = (int(part) for part in raw.split("."))
            if year < 100:
                year += 2000
            try:
                target = now.date().replace(year=year, month=month, day=day)
            except ValueError:
                target = None
        due_date = target.isoformat() if target is not None else None
    cleaned = text
    for match in sorted(
        (match for match in (description_match, priority_match, due_match) if match),
        key=lambda item: item.start(), reverse=True,
    ):
        cleaned = cleaned[:match.start()] + " " + cleaned[match.end():]
    return re.sub(r"\s+", " ", cleaned), due_date, description, priority


def parse_todo_request(
    text: str, entities: list[EntitySnapshot], now: datetime | None = None
) -> TodoRequest | None:
    todo_entities = tuple(entity for entity in entities if entity.domain == "todo")
    mentioned_lists = _mentioned_entities(text, todo_entities)
    if not _TODO_NOUN_RE.search(text) and not mentioned_lists:
        return None
    move_match = _MOVE_RE.search(text)
    if move_match is not None and len(mentioned_lists) == 2:
        ordered = sorted(
            mentioned_lists,
            key=lambda entity: min(
                (
                    normalize_for_compare(text).find(normalize_for_compare(name))
                    for name in _entity_names(entity)
                    if normalize_for_compare(name) in normalize_for_compare(text)
                ),
                default=10**9,
            ),
        )
        payload_match = re.search(
            r"\bverschieb(?:e|en|t)?\s+(.+?)\s+von\b", text, re.IGNORECASE
        )
        items = split_todo_items(payload_match.group(1)) if payload_match else ()
        if items:
            return TodoRequest(
                TodoOperation.MOVE,
                items=items,
                entity_id=ordered[0].entity_id,
                destination_entity_id=ordered[1].entity_id,
            )
    text, due_date, description, priority = _extract_todo_metadata(text, now)
    entity_id, candidates = _select_target(text, entities, "todo")
    if _CLEAR_COMPLETED_RE.search(text):
        return TodoRequest(TodoOperation.CLEAR_COMPLETED, entity_id=entity_id, candidates=candidates)
    checks = (
        (TodoOperation.COMPLETE, _COMPLETE_RE),
        (TodoOperation.REMOVE, _REMOVE_RE),
        (TodoOperation.ADD, _ADD_RE),
        (TodoOperation.LIST, _LIST_RE),
    )
    for operation, pattern in checks:
        match = pattern.search(text)
        if match is None:
            continue
        items = () if operation is TodoOperation.LIST else split_todo_items(_todo_payload(text, match))
        if operation is not TodoOperation.LIST and not items:
            return None
        return TodoRequest(
            operation, items, entity_id, candidates,
            due_date=due_date, description=description, priority=priority,
        )
    # Natural list query: "Was ist auf meiner Einkaufsliste?"
    if re.search(r"\b(?:was|welche)\b", text, re.IGNORECASE):
        return TodoRequest(TodoOperation.LIST, entity_id=entity_id, candidates=candidates)
    return None


def _number(raw: str) -> int | None:
    try:
        return int(raw)
    except ValueError:
        return _NUMBER_WORDS.get(raw.casefold())


def parse_duration_seconds(text: str) -> int | None:
    total = 0
    for match in _DURATION_PART_RE.finditer(text):
        value = _number(match.group(1))
        if value is None:
            continue
        unit = match.group(2).casefold()
        total += value * (3600 if unit.startswith(("st", "h")) else 60 if unit.startswith("min") else 1)
    if total:
        return total
    clock = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", text)
    if clock:
        hours, minutes, seconds = int(clock.group(1)), int(clock.group(2)), int(clock.group(3) or 0)
        if minutes < 60 and seconds < 60:
            return hours * 3600 + minutes * 60 + seconds
    return None


def parse_timer_request(text: str, entities: list[EntitySnapshot]) -> TimerRequest | None:
    if not _TIMER_NOUN_RE.search(text):
        return None
    lowered = text.casefold()
    entity_id, candidates = _select_target(text, entities, "timer")
    duration = parse_duration_seconds(text)
    if re.search(r"\b(?:wie\s+lange|restzeit|status|stand|läuft|laeuft)\b", lowered):
        operation = TimerOperation.STATUS
    elif re.search(r"\b(?:pausier(?:e|en|t)?|anhalten|halte\s+.*\s+an)\b", lowered):
        operation = TimerOperation.PAUSE
    elif re.search(r"\b(?:fortsetzen|weiterlaufen|weiter\s+laufen|resume)\b", lowered):
        operation = TimerOperation.RESUME
    elif re.search(r"\b(?:abbrechen|stopp(?:e|en|t)?|stop(?:pe|pen|pt)?|zurücksetzen|zuruecksetzen|lösch(?:e|en|t)?|loesch(?:e|en|t)?)\b", lowered):
        operation = TimerOperation.CANCEL
    elif re.search(r"\b(?:beenden|beende|fertig|ablaufen\s+lassen)\b", lowered):
        operation = TimerOperation.FINISH
    elif re.search(r"\b(?:verlänger(?:e|n|t)?|verlaenger(?:e|n|t)?|verkürz(?:e|en|t)?|verkuerz(?:e|en|t)?|änder(?:e|n|t)?|aender(?:e|n|t)?)\b", lowered):
        if duration is None:
            return None
        sign = -1 if re.search(r"\b(?:verkürz|verkuerz|weniger|abziehen)", lowered) else 1
        operation = TimerOperation.CHANGE
        return TimerRequest(operation, change_seconds=sign * duration, entity_id=entity_id, candidates=candidates)
    elif duration is not None and re.search(r"\b(?:stell(?:e|en|t)?|setz(?:e|en|t)?|start(?:e|en|et)?|mach(?:e|en|t)?|[a-zäöüß]*timer)\b", lowered):
        operation = TimerOperation.START
    else:
        return None
    return TimerRequest(operation, duration_seconds=duration, entity_id=entity_id, candidates=candidates)


def parse_productivity_request(
    text: str,
    entities: list[EntitySnapshot],
    now: datetime | None = None,
    document: LanguageDocument | None = None,
) -> ProductivityRequest | None:
    if document is not None:
        text = document.source_text
    return parse_todo_request(text, entities, now) or parse_timer_request(text, entities)


def select_productivity_candidate(
    request: ProductivityRequest, reply: str
) -> ProductivityRequest | None:
    selection = resolve_candidate_reply(
        reply, request.candidates, list(request.candidates)
    )
    if (
        selection.kind is not CandidateReplyKind.SELECTED
        or selection.entity is None
    ):
        return None
    return replace(
        request, entity_id=selection.entity.entity_id, candidates=()
    )


def format_duration(seconds: int) -> str:
    parts: list[str] = []
    hours, remainder = divmod(abs(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        parts.append(f"{hours} Stunde" + ("n" if hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} Minute" + ("n" if minutes != 1 else ""))
    if secs or not parts:
        parts.append(f"{secs} Sekunde" + ("n" if secs != 1 else ""))
    return " und ".join(parts)
