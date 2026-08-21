"""Parse date-bound, single-clause German commands into one-shot schedules."""

from __future__ import annotations

import re

from .automation_action_parser import AutomationActionParser
from .nlu.action_model import ActionGroup, ActionModel
from .nlu.automation_model import CalendarReference, CalendarSchedule
from .nlu.parser import ParseContext

_WEEKDAYS = {
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,
    "samstag": 5,
    "sonnabend": 5,
    "sonntag": 6,
}
_MONTHS = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}
_DAY_PERIOD_HOURS = {
    "früh": 8,
    "morgens": 8,
    "vormittags": 10,
    "mittags": 12,
    "nachmittags": 15,
    "abends": 20,
    "abend": 20,
    "nachts": 23,
}
_CLOCK_HOURS = {
    "eins": 1, "ein": 1, "zwei": 2, "drei": 3, "vier": 4,
    "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9,
    "zehn": 10, "elf": 11, "zwölf": 12,
}
_CLOCK_WORD = "|".join(_CLOCK_HOURS)

_DATE_PART = rf"""
    (?P<relative_date>heute|morgen|übermorgen)
    |
    (?:am|nächsten?|kommenden?)\s+(?P<weekday>{'|'.join(_WEEKDAYS)})
    |
    am\s+(?P<day>\d{{1,2}})\.?\s+(?P<month>{'|'.join(_MONTHS)})
       (?:\s+(?P<year>\d{{4}}))?
"""
_SCHEDULE_RE = re.compile(
    rf"""
    (?P<whole>
      (?:{_DATE_PART})
      (?:\s+(?P<period>{'|'.join(_DAY_PERIOD_HOURS)}))?
      (?:\s+(?:um\s+)?(?P<clock>
          \d{{1,2}}(?::\d{{1,2}})?\s*(?:uhr)?
          |halb\s+(?:{_CLOCK_WORD})
          |viertel\s+(?:nach|vor)\s+(?:{_CLOCK_WORD})
      ))?
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


class ScheduledTimeCommandParser:
    """Compose calendar phrase parsing with the existing action parser."""

    def __init__(self, action_parser: AutomationActionParser) -> None:
        self._action_parser = action_parser

    def parse(
        self, text: str, context: ParseContext
    ) -> tuple[tuple[ActionModel | ActionGroup, ...], CalendarSchedule] | None:
        match = _SCHEDULE_RE.search(text)
        if match is None:
            return None
        period = (match.group("period") or "").casefold()
        raw_clock = (match.group("clock") or "").casefold().strip()
        if not raw_clock and not period:
            return None
        if raw_clock:
            clock = raw_clock.removesuffix("uhr").strip()
            numeric = re.fullmatch(r"(?P<hour>\d{1,2})(?::(?P<minute>\d{1,2}))?", clock)
            if numeric is not None:
                hour = int(numeric.group("hour"))
                minute = int(numeric.group("minute") or 0)
            elif clock.startswith("halb "):
                hour = (_CLOCK_HOURS[clock.removeprefix("halb ").strip()] - 1) % 24
                minute = 30
            elif clock.startswith("viertel nach "):
                hour = _CLOCK_HOURS[clock.removeprefix("viertel nach ").strip()]
                minute = 15
            else:
                hour = (_CLOCK_HOURS[clock.removeprefix("viertel vor ").strip()] - 1) % 24
                minute = 45
        else:
            hour = _DAY_PERIOD_HOURS[period]
            minute = 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None

        relative_date = (match.group("relative_date") or "").casefold()
        weekday_name = (match.group("weekday") or "").casefold()
        if relative_date:
            reference = {
                "heute": CalendarReference.TODAY,
                "morgen": CalendarReference.TOMORROW,
                "übermorgen": CalendarReference.DAY_AFTER_TOMORROW,
            }[relative_date]
            schedule = CalendarSchedule(
                reference=reference,
                hour=hour,
                minute=minute,
                spoken=match.group("whole").strip(),
            )
        elif weekday_name:
            schedule = CalendarSchedule(
                reference=CalendarReference.WEEKDAY,
                weekday=_WEEKDAYS[weekday_name],
                hour=hour,
                minute=minute,
                spoken=match.group("whole").strip(),
            )
        else:
            month_name = (match.group("month") or "").casefold()
            schedule = CalendarSchedule(
                reference=CalendarReference.DATE,
                day=int(match.group("day")),
                month=_MONTHS[month_name],
                year=int(match.group("year")) if match.group("year") else None,
                hour=hour,
                minute=minute,
                spoken=match.group("whole").strip(),
            )

        command_text = f"{text[:match.start()]} {text[match.end():]}"
        command_text = re.sub(r"\s+", " ", command_text).strip(" ,.")
        actions = self._action_parser.parse(command_text, context)
        if not actions:
            return None
        return actions, schedule
