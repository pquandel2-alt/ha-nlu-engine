"""Structured explanations for deterministic NLU rejections.

The public conversation response remains deliberately small and German, but
internally callers must be able to distinguish "no grammar" from a known
sentence whose target is ambiguous or whose requested operation is unsafe.
This module is Home-Assistant- and hassil-free so parsers and diagnostics can
share the same vocabulary without creating a second routing system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Mapping


class ParseFailureReason(Enum):
    """Why a recognized-looking utterance could not become a command."""

    NO_GRAMMAR = auto()
    UNKNOWN_ENTITY = auto()
    UNKNOWN_LOCATION = auto()
    AMBIGUOUS_TARGET = auto()
    UNSUPPORTED_PROPERTY = auto()
    UNSUPPORTED_CAPABILITY = auto()
    INVALID_VALUE = auto()
    UNSAFE_INFERENCE = auto()
    INCOMPLETE_REQUEST = auto()


@dataclass(frozen=True)
class UnderstandingFeedback:
    """A non-action outcome with a safe, user-facing explanation.

    ``details`` is intentionally structured and contains no raw Home
    Assistant objects. It is suitable for opt-in local diagnostics while the
    default configuration stores no utterances or diagnostics persistently.
    """

    reason: ParseFailureReason
    speech: str
    details: Mapping[str, Any] = field(default_factory=dict)
