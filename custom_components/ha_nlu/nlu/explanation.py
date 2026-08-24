"""User-facing explanation of the last structured semantic command."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .command import SemanticCommand
from .normalize import normalize


_EXPLANATION_RE = re.compile(
    r"^(?:bitte\s+)?(?:"
    r"was\s+hast\s+du\s+(?:gerade\s+)?verstanden|"
    r"wie\s+hast\s+du\s+(?:das|mich)\s+verstanden|"
    r"was\s+willst\s+du\s+(?:jetzt\s+)?machen|"
    r"welchen\s+befehl\s+hast\s+du\s+verstanden"
    r")[?.!]*$",
    re.I,
)

_ACTION_LABELS = {
    "HassTurnOn": "einschalten",
    "HassTurnOff": "ausschalten",
    "HassToggle": "umschalten",
    "HassOpenCover": "öffnen",
    "HassCloseCover": "schließen",
    "HassRunScript": "ausführen",
    "HassSetPercentage": "auf einen Prozentwert stellen",
    "HassClimateSetTemperature": "auf eine Temperatur stellen",
    "HassLightBrighten": "heller stellen",
    "HassLightDim": "dunkler stellen",
    "HassFanSetSpeed": "auf eine Geschwindigkeit stellen",
}


def is_explanation_request(text: str) -> bool:
    """Whether the user explicitly asks for the previous interpretation."""
    return _EXPLANATION_RE.fullmatch(normalize(text)) is not None


def _value_description(parameters: Mapping[str, object]) -> str | None:
    for key, unit in (
        ("percent", "Prozent"),
        ("brightness_pct", "Prozent Helligkeit"),
        ("temperature", "Grad"),
        ("step_percent", "Prozent"),
        ("step", "Grad"),
    ):
        value = parameters.get(key)
        if isinstance(value, (int, float)):
            return f"{value:g} {unit}"
    return None


def explain_command(command: SemanticCommand) -> str:
    """Render resolved facts only; never reinterpret the original utterance."""
    names = tuple(entity.friendly_name for entity in command.entities)
    target = ", ".join(names) if names else "kein konkretes Gerät"
    action = _ACTION_LABELS.get(command.intent)
    if action is None and (
        command.intent == "HassGetState" or "Query" in command.intent
    ):
        action = "den aktuellen Zustand abfragen"
    elif action is None:
        action = command.intent

    parts = [f"Aktion: {action}", f"Ziel: {target}"]
    if command.area is not None:
        parts.append(f"Bereich: {command.area.name}")
    locations = command.parameters.get("locations")
    if isinstance(locations, tuple):
        spoken = tuple(
            str(location.get("text"))
            for location in locations
            if isinstance(location, dict) and location.get("text")
        )
        if spoken:
            parts.append("Orte: " + ", ".join(spoken))
    value = _value_description(command.parameters)
    if value is not None:
        parts.append(f"Wert: {value}")
    excluded = command.parameters.get("excluded")
    if isinstance(excluded, tuple) and excluded:
        parts.append("Ausgenommen: " + ", ".join(str(item) for item in excluded))
    return "Ich habe Folgendes verstanden: " + "; ".join(parts) + "."
