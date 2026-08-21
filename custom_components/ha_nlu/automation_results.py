"""Hass-free result types returned by automation matching routes."""

from __future__ import annotations

from dataclasses import dataclass

from .automation_summary import AutomationSummary
from .nlu.automation_model import AutomationModel
from .nlu.automation_validator import AutomationValidationError


@dataclass(frozen=True)
class AutomationMatchResult:
    """A parsed automation plus validation and preview/debug information."""

    model: AutomationModel
    response_text: str
    validation_error: AutomationValidationError | None


@dataclass(frozen=True)
class AutomationDeletionMatchResult:
    """A deletion candidate or a refusal response for ambiguous selection."""

    automation: AutomationSummary | None
    response_text: str


@dataclass(frozen=True)
class AutomationToggleMatchResult:
    """An enable/disable candidate and the requested direction."""

    automation: AutomationSummary | None
    enable: bool
    response_text: str
