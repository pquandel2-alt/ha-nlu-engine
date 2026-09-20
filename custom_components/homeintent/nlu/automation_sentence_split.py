"""Splits a combined spoken automation sentence ("Wenn das Küchenfenster
geöffnet wird, schalte das Küchenlicht ein.") into its trigger-clause and
action-clause halves, so each half can be handed to its own dedicated
parser (``AutomationTriggerParser``/``AutomationActionParser``) exactly the
way each already expects to be called - a full, self-contained sentence
(neither parser splits a combined sentence itself, see the Integration
Plan's Section 9/16 - this was the one genuinely novel piece this
integration needed, no existing parser or test does it today).

Scope decision (stated plainly, not hidden): only the trigger+action
combination is split this wave - no trigger+condition+action. That is the
only combination the Integration Plan's 8 end-to-end test cases actually
exercise. A three-way split (condition clause too) is deferred, not
attempted here; it would need a distinct, dedicated qualifier ("wenn ...
und ...", "aber nur wenn ...") this codebase has no precedent for yet -
inventing one now would guess at a shape nothing downstream has validated.

Pure text-to-text, no hassil/entity awareness - same "make no semantic
decision here" rule ``nlu/normalize.py`` already documents for itself: this
module only finds *where* the sentence splits, never *what* either half
means (that is each dedicated parser's job, further down the pipeline).
"""

from __future__ import annotations

from .german_structure import ClauseKind, StructuralRelationKind
from .language_frontend import LanguageDocument


def split_automation_document(document: LanguageDocument) -> tuple[str, str] | None:
    """Select trigger/action source spans from the authoritative structure.

    No text is synthesized and no clause boundary is rediscovered. Dedicated
    automation projectors receive unchanged substrings only after one unique
    IF relation has identified the trigger and action roles.
    """
    if_relations = tuple(
        relation
        for relation in document.structure.relations
        if relation.kind is StructuralRelationKind.IF
    )
    if len(if_relations) != 1:
        return None
    clauses = {clause.clause_id: clause for clause in document.structure.clauses}
    relation = if_relations[0]
    endpoints = tuple(
        clause
        for clause_id in (relation.source_clause, relation.target_clause)
        if (clause := clauses.get(clause_id)) is not None
    )
    if len(endpoints) != 2:
        return None
    condition = next(
        (clause for clause in endpoints if clause.kind is ClauseKind.CONDITION),
        None,
    )
    action = next(
        (clause for clause in endpoints if clause.kind is ClauseKind.MAIN),
        None,
    )
    if condition is None or action is None:
        return None

    condition_ids = {condition.clause_id}
    changed = True
    while changed:
        changed = False
        for edge in document.structure.relations:
            if edge.kind not in {StructuralRelationKind.AND, StructuralRelationKind.OR}:
                continue
            if edge.source_clause in condition_ids and edge.target_clause not in condition_ids:
                candidate = clauses.get(edge.target_clause)
                if candidate is not None and candidate.char_end <= action.char_start:
                    condition_ids.add(candidate.clause_id)
                    changed = True
    condition_clauses = tuple(clauses[item] for item in condition_ids)
    trigger_start = min(
        relation.connector_start,
        *(clause.char_start for clause in condition_clauses),
    )
    trigger_end = max(clause.char_end for clause in condition_clauses)
    trigger_text = document.source_text[trigger_start:trigger_end].strip(" ,")
    action_text = document.source_text[action.char_start:action.char_end].strip(" ,")
    if not trigger_text or not action_text:
        return None
    return trigger_text, action_text


def structured_automation_condition_clauses(
    document: LanguageDocument,
) -> tuple[str, ...]:
    """Return the structurally bounded IF-side clauses in source order.

    This is deliberately only a boundary projection: trigger/condition
    meaning remains owned by the established automation domain parsers.  A
    caller gets no result unless there is one unique IF relation and every
    returned clause is connected to its condition endpoint by the shared
    structural AND/OR graph before the action clause.
    """
    if_relations = tuple(
        relation
        for relation in document.structure.relations
        if relation.kind is StructuralRelationKind.IF
    )
    if len(if_relations) != 1:
        return ()
    clauses = {clause.clause_id: clause for clause in document.structure.clauses}
    relation = if_relations[0]
    condition = clauses.get(relation.source_clause)
    action = clauses.get(relation.target_clause)
    if (
        condition is None
        or action is None
        or condition.kind is not ClauseKind.CONDITION
    ):
        return ()

    condition_ids = {condition.clause_id}
    changed = True
    while changed:
        changed = False
        for edge in document.structure.relations:
            if edge.kind not in {
                StructuralRelationKind.AND,
                StructuralRelationKind.OR,
            }:
                continue
            if edge.source_clause not in condition_ids:
                continue
            candidate = clauses.get(edge.target_clause)
            if (
                candidate is not None
                and candidate.char_end <= action.char_start
                and candidate.clause_id not in condition_ids
            ):
                condition_ids.add(candidate.clause_id)
                changed = True

    ordered = sorted((clauses[item] for item in condition_ids), key=lambda item: item.char_start)
    result: list[str] = []
    for index, clause in enumerate(ordered):
        start = relation.connector_start if index == 0 else clause.char_start
        text = document.source_text[start:clause.char_end].strip(" ,")
        if not text:
            return ()
        result.append(text)
    return tuple(result)


def split_trigger_action(text: str) -> tuple[str, str] | None:
    """Splits on the first top-level comma - the only separator every one
    of the Integration Plan's automation test sentences uses between its
    trigger-clause and its action-clause(s) ("Wenn X, schalte Y ein.",
    "Wenn X, schalte Y ein und schalte Z aus."). A second/third comma (one
    per additional action) is left untouched here - ``AutomationActionParser``
    already splits multiple comma/"und"-joined actions on its own side (see
    its ``_split_chunks``), so only the *first* comma is this function's
    business.

    Returns ``None`` (never guesses) when there is no comma at all, or when
    either resulting half is empty after stripping - a sentence with no
    reliable split point has no split this codebase can derive without
    inventing a new heuristic no test covers.
    """
    if "," not in text:
        return None
    trigger_text, _, action_text = text.partition(",")
    trigger_text = trigger_text.strip()
    action_text = action_text.strip()
    if not trigger_text or not action_text:
        return None
    return trigger_text, action_text
