"""ServiceMapper (v2 plan Phase 12/13): the last pipeline step,
SemanticCommand -> ServiceMapper -> ServiceCallPlan. Domain-specific
"which HA service, which data key" logic belongs here, not in the parsers
(plan: "Die Domain-spezifische Logik gehört hierher, nicht in den Parser") -
parsers.py only recognizes text and resolves entities/areas.

The actual per-domain build callables already live in ``service_call.py``'s
``INTENTS``/``PERCENT_INTENTS`` registries (``light.turn_on``, ``cover.
set_cover_position`` + ``brightness_pct``/``position`` data, ...) - this
module doesn't duplicate that logic, it owns the one decision of *which*
registry/entry applies to a given command, replacing the inline dispatch
that used to sit directly in ``engine.py``.

Callers must run ``nlu.validator.validate_command()`` first (``engine.py``
does, in ``_build_match_result``) - ``map_to_service_call`` assumes an
already-valid command and does not re-check domain/capability itself; that
is the Validator's job, not this module's.
"""

from __future__ import annotations

from ..service_call import INTENTS, PERCENT_INTENTS, ServiceCallPlan
from .command import SemanticCommand


def map_to_service_call(command: SemanticCommand) -> ServiceCallPlan | None:
    entities = list(command.entities)
    percent = command.parameters.get("percent")
    if percent is not None:
        spec = PERCENT_INTENTS.get(entities[0].domain)
        return spec.build(entities, percent) if spec is not None else None

    spec = INTENTS.get(command.intent)
    return spec.build(entities) if spec is not None else None
