"""Debug trace (v2 plan Phase 22, "Debug-Modus"): a structured, human-
readable record of every pipeline stage for one utterance - parser
selection, intent, target/area text, resolved entities, capabilities, the
built ``SemanticCommand``, validation outcome, and the resulting service
call. Purely a read-only view built alongside ``NluEngine.respond()`` - it
changes no matching behaviour and is not wired into ``conversation.py``
(see ``NluEngine.debug()``'s docstring for why).

Field granularity intentionally matches what ``respond()``/``NluResponse``
already exposes rather than exceeding it: a no-template-match and an
unresolved/ambiguous ``{name}`` both collapse to "kein Treffer" inside
``parsers.py`` today (see ``nlu/response.py``'s module docstring) - the six
``IntentParser`` implementations return ``ParseResult | None``, not the
richer ``ResolveResult``/``AreaResolveResult`` they compute internally.
Surfacing per-candidate scores for a *failed* resolution would need every
parser's return type restructured just for debug output; given the plan
itself calls this feature optional and explicitly not required for normal
users, that restructuring is left for a later pass if actually needed
in practice, rather than done speculatively here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from .command import SemanticCommand


def format_command(command: SemanticCommand) -> str:
    """Compact ``intent(k=v, ...)`` rendering for the trace's COMMAND line -
    the plan's own example ("adjust_brightness(+small)") is this shape, not
    a full dataclass repr (which would also dump every resolved
    ``EntitySnapshot`` verbatim)."""
    params = ", ".join(f"{key}={value!r}" for key, value in command.parameters.items())
    return f"{command.intent}({params})" if params else command.intent


@dataclass(frozen=True)
class DebugTrace:
    input: str
    normalized: str
    parser: str
    intent: str | None
    target: str | None
    area: str | None
    candidates: tuple[str, ...]
    resolution: str | None
    capabilities: tuple[str, ...]
    command: str | None
    validation: str
    service: str | None
    data: Mapping[str, Any] | None

    def format(self) -> str:
        lines = [
            f"INPUT: {self.input!r}",
            f"NORMALIZED: {self.normalized!r}",
            f"PARSER: {self.parser}",
            f"INTENT: {self.intent or '-'}",
            f"TARGET: {self.target or '-'}",
            f"AREA: {self.area or '-'}",
            f"CANDIDATES: {', '.join(self.candidates) if self.candidates else '-'}",
            f"RESOLUTION: {self.resolution or '-'}",
            f"CAPABILITIES: {', '.join(self.capabilities) if self.capabilities else '-'}",
            f"COMMAND: {self.command or '-'}",
            f"VALIDATION: {self.validation}",
            f"SERVICE: {self.service or '-'}",
            f"DATA: {dict(self.data) if self.data is not None else '-'}",
        ]
        return "\n".join(lines)
