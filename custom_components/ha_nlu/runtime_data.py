"""Typed config-entry owned runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field

from .engine import NluEngine
from .nlu.context import ConversationContextStore


@dataclass
class HaNluRuntimeData:
    """State shared by platforms belonging to one integration entry."""

    engine: NluEngine = field(default_factory=NluEngine)
    context_store: ConversationContextStore = field(
        default_factory=ConversationContextStore
    )
