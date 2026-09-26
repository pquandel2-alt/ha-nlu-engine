"""Deterministic reminder language mapped onto one-shot automations.

Only the *timing* and optional quiet hours are separated here.  The reminder
clause itself ("erinnere mich daran, den Backofen zu prüfen", "sag mir
Bescheid, dass ...", "benachrichtige mich, dass ...") is handed back to the
shared notification language (``notification_language.py``), so reminders,
spoken notifications and notification automations share one meaning.
"""

from __future__ import annotations

import re


_REMINDER_RE = re.compile(
    r"^\s*(?:bitte\s+)?(?P<verb>erinner(?:e|st)?)\s+(?P<recipient>mich|uns|[A-Za-zÄÖÜäöüß-]+)\s+"
    r"(?P<when>.+?)\s*,?\s+(?P<rest>(?:daran|an|dass)\b.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_TELL_RE = re.compile(
    r"^\s*(?:bitte\s+)?(?P<verb>sag)\s+(?P<recipient>[A-Za-zÄÖÜäöüß-]+)\s+"
    r"(?P<when>.+?)\s+bescheid\s*,?\s*(?:dass|über|ueber)\s+(?P<message>.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_NOTIFY_RE = re.compile(
    r"^\s*(?:bitte\s+)?(?P<verb>benachrichtige|informiere)\s+(?P<recipient>mich|uns|[A-Za-zÄÖÜäöüß-]+)\s+"
    r"(?P<when>.+?)\s*,?\s+dass\s+(?P<message>.+?)\s*[.!?]*$",
    re.IGNORECASE,
)
_QUIET_RE = re.compile(
    r"\s*(?:,?\s*(?:aber\s+)?nicht\s+zwischen|,?\s*außerhalb\s+der\s+ruhezeit\s+von)\s+"
    r"(?P<start>\d{1,2})(?::\d{2})?\s*(?:uhr)?\s+(?:und|bis)\s+"
    r"(?P<end>\d{1,2})(?::\d{2})?\s*(?:uhr)?\s*$",
    re.IGNORECASE,
)


def _match(text: str) -> re.Match[str] | None:
    cleaned = _QUIET_RE.sub("", text)
    return _REMINDER_RE.match(cleaned) or _TELL_RE.match(cleaned) or _NOTIFY_RE.match(cleaned)


def reminder_automation_text(text: str) -> str | None:
    """Return the same request with its timing moved to the front.

    Timing and action parsing deliberately stay in the existing automation
    parsers and the shared notification language; this adapter only removes
    the quiet-hours suffix and restores a word order the one-shot parsers
    read ("in fünf Minuten erinnere mich an die Waschmaschine").
    """
    match = _match(text)
    if match is None:
        return None
    when = match.group("when").strip(" ,")
    verb = match.group("verb").casefold()
    recipient = match.group("recipient")
    if "rest" in match.groupdict() and match.group("rest") is not None:
        body = match.group("rest").strip(" ,.!?")
        clause = f"erinnere {recipient} {body}"
    else:
        message = match.group("message").strip(" ,.!?")
        if not message:
            return None
        clause = (
            f"sag {recipient} Bescheid, dass {message}" if verb == "sag"
            else f"{verb} {recipient}, dass {message}"
        )
    if not when or len(clause) > 520:
        return None
    return f"{when} {clause}"


def reminder_recipient(text: str) -> str | None:
    match = _match(text)
    if match is None:
        return None
    recipient = match.group("recipient")
    return None if recipient.casefold() in {"mich", "mir", "uns"} else recipient


def reminder_quiet_hours(text: str) -> tuple[int, int] | None:
    match = _QUIET_RE.search(text)
    if match is None:
        return None
    start, end = int(match.group("start")), int(match.group("end"))
    return (start, end) if 0 <= start <= 23 and 0 <= end <= 23 and start != end else None
