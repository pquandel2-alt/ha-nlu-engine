"""Semantic Composer (V6 architecture plan, V6.4): assembles the small,
independently-recognized linguistic building blocks captured in
nlu/lexicon.py's candidate dicts into one semantic structure, instead of
adding one parser rule per full sentence pattern - see
docs/architecture-v6.md section 1 (Leitprinzip) and section 3
(Zielarchitektur). Worked example from the plan (Brain node
755ef579-e0ba-43b7-bba9-1596c11854cd): "die beiden Lampen" composes the
domain word "Lampen" (-> TARGET=LIGHT, already handled by
lexicon._DOMAIN_SLOT_LIST/parsers.py) together with the quantifier word
"beide" (-> QUANTITY=EXACTLY(2)) into one combined meaning, rather than a
sentence rule for "die beiden Lampen" as a whole.

Grounding boundary (same "niemals raten" rule enforced throughout this
package - see nlu/lexicon.py's SEMANTIC_PROPERTY_CANDIDATES/
SEMANTIC_QUANTITY_CANDIDATES docstrings and Wave 2a's own findings): only
PROPERTY and QUANTITY are composed here, because those are the only two
candidate dicts nlu/lexicon.py currently derives from real hassil
TextSlotList vocabulary. ACTION/DIRECTION/DEGREE have no equivalent
word->candidate table yet (those words live only inside hassil grammar
YAML/regex, not as Python vocabulary constants) - composing them is future
work once nlu/lexicon.py gains that mapping, not something to guess at here.

Not yet wired into engine.py/parsers.py: this module only composes
SemanticFrame's V6.2 primitive fields from an already-tokenized word list;
feeding it real matched words from a sentence (replacing hassil bit by bit,
per the plan's fallback cascade) is later migration work, not V6.4 itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .lexicon import SEMANTIC_PROPERTY_CANDIDATES, SEMANTIC_QUANTITY_CANDIDATES
from .primitives import SemanticProperty, SemanticQuantity


@dataclass(frozen=True)
class ComposedPrimitives:
    """The subset of SemanticFrame's V6.2 primitive fields the Composer can
    fill in from lexicon candidates alone. Intent/target/area are resolved
    elsewhere (World Model/Constraint Resolver, not the Composer's job)."""

    property: SemanticProperty | None = None
    quantity: SemanticQuantity | None = None


class SemanticComposer:
    """Composes ``ComposedPrimitives`` from a bag of already-tokenized
    words, using nlu/lexicon.py's word->candidate tables. Stateless."""

    @staticmethod
    def compose(words: Iterable[str]) -> ComposedPrimitives:
        """Looks up each word as a Semantic Lexicon candidate and combines
        the results. Unrecognized words are ignored (candidates are
        optional hints, not requirements - see nlu/lexicon.py). The first
        matching word for a given primitive wins; later matches for the
        same primitive are ignored rather than overwriting it."""
        property_: SemanticProperty | None = None
        quantity: SemanticQuantity | None = None
        for word in words:
            if property_ is None and word in SEMANTIC_PROPERTY_CANDIDATES:
                property_ = SEMANTIC_PROPERTY_CANDIDATES[word]
            if quantity is None and word in SEMANTIC_QUANTITY_CANDIDATES:
                quantity = SEMANTIC_QUANTITY_CANDIDATES[word]
        return ComposedPrimitives(property=property_, quantity=quantity)
