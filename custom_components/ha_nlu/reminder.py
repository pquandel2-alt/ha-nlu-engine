"""Deterministic reminder language mapped onto one-shot automations."""

from __future__ import annotations

import re


_REMINDER_RE = re.compile(
    r"^\s*(?:bitte\s+)?erinner(?:e|st)?\s+(?P<recipient>mich|uns|[A-Za-zÄÖÜäöüß-]+)\s+"
    r"(?P<when>.+?)\s+(?:daran\s+)?(?:an|dass)\s+(?P<message>.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_TELL_RE = re.compile(
    r"^\s*(?:bitte\s+)?sag\s+(?P<recipient>[A-Za-zÄÖÜäöüß-]+)\s+"
    r"(?P<when>.+?)\s+bescheid\s*,?\s*(?:dass|über|ueber)\s+(?P<message>.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_QUIET_RE = re.compile(
    r"\s*(?:,?\s*(?:aber\s+)?nicht\s+zwischen|,?\s*außerhalb\s+der\s+ruhezeit\s+von)\s+"
    r"(?P<start>\d{1,2})(?::\d{2})?\s*(?:uhr)?\s+(?:und|bis)\s+"
    r"(?P<end>\d{1,2})(?::\d{2})?\s*(?:uhr)?\s*$",
    re.IGNORECASE,
)


def reminder_automation_text(text: str) -> str | None:
    """Return an equivalent scheduled notification sentence.

    Timing and action parsing deliberately stay in the existing automation
    parsers. This adapter only extracts the reminder payload, so word-order
    variants do not need a second date or duration grammar.
    """
    cleaned = _QUIET_RE.sub("", text)
    match = _REMINDER_RE.match(cleaned) or _TELL_RE.match(cleaned)
    if match is None:
        return None
    when = match.group("when").strip(" ,")
    message = match.group("message").strip(" ,.!?")
    if not when or not message or len(message) > 500:
        return None
    return f"{when} sende mir eine Nachricht dass {message}"


def reminder_recipient(text: str) -> str | None:
    cleaned = _QUIET_RE.sub("", text)
    match = _REMINDER_RE.match(cleaned) or _TELL_RE.match(cleaned)
    if match is None:
        return None
    recipient = match.group("recipient")
    return None if recipient.casefold() in {"mich", "uns"} else recipient


def reminder_quiet_hours(text: str) -> tuple[int, int] | None:
    match = _QUIET_RE.search(text)
    if match is None:
        return None
    start, end = int(match.group("start")), int(match.group("end"))
    return (start, end) if 0 <= start <= 23 and 0 <= end <= 23 and start != end else None
