"""Text normalization: runs once, before any parser sees the sentence (see
v2 plan Phase 3). Kept intentionally small - hassil's ``recognize()``
already tolerates mixed case, extra whitespace, trailing punctuation and
spelled-out German numbers natively (verified empirically against
hassil==3.11.0), so this module only covers what hassil does *not* handle:
the "%" and "°" symbols, which have no built-in meaning for
``RangeSlotList``, and (HomeIntent plan V4.1, "Advanced German Language")
most of a fixed set of German filler particles that carry no command
meaning of their own.

Must never make a semantic decision (e.g. never resolve a spoken name like
"Wohnzimmerlampe" towards an entity_id here) - that is Entity Resolution's
job, further down the pipeline. Pure text-to-text, no HA/hassil imports.
Filler-word removal stays within that rule: it never picks between
candidate intents/entities, it just deletes particles that are already
proven meaningless to this grammar (see context_followup/brightness.yaml's
pre-existing "etwas heller" == "heller" pair) - stripping them once here
replaces adding "[mal|doch|kurz|etwas|ein bisschen]" to every single
sentence across all 8 grammar groups (the plan's own "keine YAML-
Kombinatorik" goal), a fully general fix instead of a per-file one.

"bitte" is deliberately NOT stripped here even though the plan lists it as
a filler word: several sentences (e.g. light_switch.yaml's "bitte {name}
an") use it as their only imperative marker with no separate verb - it is
already handled per-sentence via existing "[bitte]"/"[kannst du|bitte]"
grammar branches, and blanket-stripping it here breaks those verb-less
imperatives instead of just being redundant.
"""

from __future__ import annotations

import re

# Real users type "30%"/"30 %" in the Assist chat UI, not the word
# "Prozent" - normalizing it to the word form up front keeps hassil's
# grammar (and RangeSlotList, which has no built-in "%"-symbol parsing -
# RangeType.PERCENTAGE is just a label) the single source of truth for the
# sentence shape.
_PERCENT_SYMBOL_RE = re.compile(r"(\d)\s*%")

# Same reasoning as the "%" case above (HomeIntent plan V4.2, "Number
# Normalization": "21 Grad", "21°" must normalize to the same value) -
# climate_extended/temperature.yaml's grammar only knows the literal word
# "Grad", never the "°" symbol.
_DEGREE_SYMBOL_RE = re.compile(r"(\d)\s*°")

# "ein bisschen" listed before the single-word particles only for
# readability - alternation order doesn't matter here since none of the
# other words are prefixes of each other's tokens. "bitte" excluded, see
# module docstring.
_FILLER_RE = re.compile(r"\b(ein bisschen|mal|doch|kurz|etwas)\b", re.IGNORECASE)

_POLITE_MODAL_RE = re.compile(
    r"\b(?:könntest|koenntest|würdest|wuerdest)\s+du\b", re.IGNORECASE
)
_TRIGGER_DISCOURSE_RE = re.compile(r"\b(?:jedes\s+mal|immer)\s+wenn\b", re.IGNORECASE)

# Frequent speech-to-text tokenizations. These are orthographic rewrites,
# not semantic guesses: both sides are the same German device/unit/verb.
_STT_REWRITES = (
    (re.compile(r"\bpro\s+cent\b", re.IGNORECASE), "Prozent"),
    (re.compile(r"\broll[\s-]+laden\b", re.IGNORECASE), "Rollladen"),
    (re.compile(r"\bgrad\s+(?:c|celsius)\b", re.IGNORECASE), "Grad"),
    (re.compile(r"\b(an|aus)\s+machen\b", re.IGNORECASE), r"\1machen"),
    (re.compile(r"\b(hoch|runter|herunter)\s+fahren\b", re.IGNORECASE), r"\1fahren"),
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = _PERCENT_SYMBOL_RE.sub(r"\1 Prozent", text)
    text = _DEGREE_SYMBOL_RE.sub(r"\1 Grad", text)
    text = _POLITE_MODAL_RE.sub("kannst du", text)
    text = _TRIGGER_DISCOURSE_RE.sub("wenn", text)
    for pattern, replacement in _STT_REWRITES:
        text = pattern.sub(replacement, text)
    text = _FILLER_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()
