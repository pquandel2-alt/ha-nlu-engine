"""Reasoning Engine (V6 architecture plan, V6.25, section 29): the central
component that composes ``SemanticFrame`` + ``ConversationContext`` +
World Model/Constraints (``nlu/constraint_resolver.py``) + Capabilities
(``nlu/capabilities.py``) into one ``ResolvedSemanticIntent`` (V6.26,
section 30) - a fully-resolved semantic meaning (action, entities, property,
direction, degree, area), still one abstraction level above any HA side
effect.

Must NEVER execute an HA service call or build a ``ServiceCallPlan`` ("Darf
KEINE HA-Service-Aufrufe ausführen, produziert nur semantische Ergebnisse" -
plan text, V6.25): this module has no import from ``service_call.py``/
``service_mapper.py`` and produces nothing but a ``ResolvedSemanticIntent``.
Per the plan's own ordering ("Erst danach: Command Validator ->
ServiceMapper"), this is explicitly the step that runs *before* the existing
Command Validator/ServiceMapper stage, not a replacement for either.

Deliberately does not reimplement entity filtering (Regel 6, "no parallel
search system"): all domain/area/floor/device_class/capability filtering is
delegated to ``constraint_resolver.resolve_candidates()``, the same World
Model + Capability Reasoning entry point ``nlu/constraint_resolver.py``
already exposes. Only the ``Constraints`` assembly (reading ``SemanticFrame``'s
``target``/``area``/``property`` fields, with an optional
``ConversationContext`` fallback for area/floor scoping on a follow-up turn)
is this module's own logic.

Not yet wired into ``engine.py``/``conversation.py`` - same build-ahead-of-
consumer pattern as ``nlu/context.py``'s ``ConversationContext`` (Phase 24),
``nlu/primitives.py``'s ``SemanticDegree``/``NumericValue``, and
``nlu/frame.py``'s V6.2 primitive fields (populated only by the also-unwired
``SemanticComposer``, V6.4). Full pipeline integration - engine.py actually
calling ``ReasoningEngine.resolve()`` ahead of the Command Validator - is
planned for a later "Wave 7: Integration" step of this same architecture
effort, not this phase.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..entities import EntitySnapshot
from .constraint_resolver import Constraints, resolve_candidates
from .context import ConversationContext
from .frame import AreaReference, SemanticFrame
from .primitives import SemanticAction, SemanticDegree, SemanticDirection, SemanticProperty


@dataclass(frozen=True)
class ResolvedSemanticIntent:
    """Fully-resolved meaning of one turn - the plan's own field list (V6.26,
    section 30): action, entities, property, direction, degree, area. Reuses
    ``nlu/frame.py``'s ``AreaReference`` for ``area`` rather than inventing a
    second area type (same "one type per concept" rule ``primitives.py``'s
    own docstring documents for ``Target``/``Comparison``/etc.).

    ``entities`` is the already-constraint-filtered candidate list (World
    Model output), not yet reduced by any ``SemanticFrame.quantity``/
    ``quantifier`` - applying Quantity to this list stays a caller's job,
    same scoping ``constraint_resolver.resolve_candidates()`` itself
    documents.
    """

    action: SemanticAction | None
    entities: tuple[EntitySnapshot, ...]
    property: SemanticProperty | None
    direction: SemanticDirection | None
    degree: SemanticDegree | None
    area: AreaReference | None


class ReasoningEngine:
    """Composes a ``ResolvedSemanticIntent`` from a ``SemanticFrame`` and the
    full candidate entity pool. Stateless, same shape as
    ``composer.SemanticComposer`` - one static entry point, no instance
    state to construct around."""

    @staticmethod
    def resolve(
        frame: SemanticFrame,
        entities: list[EntitySnapshot],
        context: ConversationContext | None = None,
    ) -> ResolvedSemanticIntent:
        """Builds ``Constraints`` from ``frame`` (falling back to ``context``'s
        ``last_area``/``last_floor`` for area/floor scoping only when the
        frame itself named none - a follow-up turn like "Und im Büro?" has no
        explicit target of its own, so context is the only source of area
        scoping there), resolves candidates via ``resolve_candidates()``, and
        passes ``frame``'s own action/property/direction/degree straight
        through (no reinterpretation - composing those primitives is the
        Semantic Composer's job, already done by the time a frame reaches
        here)."""
        domain = frame.target.domain if frame.target is not None else None
        device_class = frame.target.device_class if frame.target is not None else None

        area = frame.area
        area_id = area.area_id if area is not None else None
        if area is None and context is not None and context.last_area is not None:
            area_id = context.last_area.area_id
            area = AreaReference(text=context.last_area.name, area_id=area_id)

        floor_id: str | None = None
        if context is not None and context.last_floor is not None:
            floor_id = context.last_floor.floor_id

        constraints = Constraints(
            domain=domain,
            area_id=area_id,
            floor_id=floor_id,
            device_class=device_class,
            property=frame.property,
        )
        resolved_entities = tuple(resolve_candidates(entities, constraints))

        return ResolvedSemanticIntent(
            action=frame.action,
            entities=resolved_entities,
            property=frame.property,
            direction=frame.direction,
            degree=frame.degree,
            area=area,
        )
