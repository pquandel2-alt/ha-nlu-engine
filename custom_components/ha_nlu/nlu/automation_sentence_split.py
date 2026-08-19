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
