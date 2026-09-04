"""Typed config-entry owned runtime state."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Any

from .engine import NluEngine
from .audit_log import AuditTrail
from .nlu.context import ConversationContextStore
from .memory import MemoryStore
from .situation import RoutineStatistics, SituationEvaluator
from .dialog_manager import DialogManager
from .effect_monitor import EffectMonitor
from .adapters import AdapterEvidence


@dataclass
class HaNluRuntimeData:
    """State shared by platforms belonging to one integration entry."""

    engine: NluEngine = field(default_factory=NluEngine)
    context_store: ConversationContextStore = field(
        default_factory=ConversationContextStore
    )
    audit_trail: AuditTrail = field(default_factory=AuditTrail)
    proactive_agent: Any | None = None
    situation_runtime: Any | None = None
    memory: MemoryStore | None = None
    situation_evaluator: SituationEvaluator = field(default_factory=SituationEvaluator)
    routine_statistics: dict[str, RoutineStatistics] = field(default_factory=dict)
    dialog_manager: DialogManager = field(default_factory=DialogManager)
    document_index: Any | None = None
    effect_monitor: EffectMonitor = field(default_factory=EffectMonitor)
    adapter_evidence: deque[AdapterEvidence] = field(
        default_factory=lambda: deque(maxlen=512)
    )
    adapter_runtime: Any | None = None
