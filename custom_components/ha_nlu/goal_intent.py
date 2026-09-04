"""Closed household goal meanings after the shared language frontend."""

from __future__ import annotations

import re

from .nlu.language_frontend import LanguageDocument
from .planner import Goal, GoalKind


def interpret_goal(document: LanguageDocument) -> Goal | None:
    text = document.normalized_text.casefold()
    if re.search(r"\b(?:bereite|mach)\b.*\bhaus\b.*\b(?:für\s+die\s+)?nacht\b", text):
        return Goal(GoalKind.PREPARE_NIGHT)
    if re.search(r"\b(?:bereite|mach)\b.*\bfilmabend\b", text):
        return Goal(GoalKind.PREPARE_MOVIE)
    if re.search(r"\b(?:bereite|schalte)\b.*\babwesenheit", text):
        return Goal(GoalKind.PREPARE_AWAY)
    if re.search(r"\bunbesetzte\b.*\b(?:bereiche|räume)\b.*\benergiespar", text):
        return Goal(GoalKind.SAVE_UNOCCUPIED)
    if re.search(r"\buntersuch(?:e|en)\b.*\b(?:zustand|ursache)\b", text):
        return Goal(GoalKind.INVESTIGATE_STATE)
    if re.search(r"\b(?:mach|mache)\b.*\b(?:raum|zimmer)\b.*\bkomfortabler\b", text):
        return Goal(GoalKind.IMPROVE_COMFORT)
    return None
