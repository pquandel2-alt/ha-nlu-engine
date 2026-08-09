"""Text normalization: runs once, before any parser sees the sentence (see
v2 plan Phase 3). Kept intentionally small - hassil's ``recognize()``
already tolerates mixed case, extra whitespace, trailing punctuation and
spelled-out German numbers natively (verified empirically against
hassil==3.11.0), so this module only covers what hassil does *not* handle:
the "%" symbol, which has no built-in meaning for ``RangeSlotList``.

Must never make a semantic decision (e.g. never resolve a spoken name like
"Wohnzimmerlampe" towards an entity_id here) - that is Entity Resolution's
job, further down the pipeline. Pure text-to-text, no HA/hassil imports.
"""

from __future__ import annotations

import re

# Real users type "30%"/"30 %" in the Assist chat UI, not the word
# "Prozent" - normalizing it to the word form up front keeps hassil's
# grammar (and RangeSlotList, which has no built-in "%"-symbol parsing -
# RangeType.PERCENTAGE is just a label) the single source of truth for the
# sentence shape.
_PERCENT_SYMBOL_RE = re.compile(r"(\d)\s*%")

_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = _PERCENT_SYMBOL_RE.sub(r"\1 Prozent", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()
