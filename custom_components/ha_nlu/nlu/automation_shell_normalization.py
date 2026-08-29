"""Strip optional automation meta-shells from utterances.

Automations in natural German can be wrapped in meta-directives:
  - "Erstelle eine Automation, die ..."
  - "Lege eine Regel an, die ..."
  - "Ich möchte eine Automation, die ..."

These shells are not part of the trigger/action semantics and must be removed
before trigger/action clause analysis, so the ClauseRole assignment recognizes
the true trigger/action boundary.

Returns the stripped text and whether normalization occurred, so callers can
preserve the original for preview/alias purposes.
"""

from __future__ import annotations

import re

_AUTOMATION_SHELL_RE = re.compile(
    r"^(?:"
    r"(?:erstelle|erstell|create)\s+(?:eine\s+)?(?:automation|regel)"
    r"|(?:lege|leg)\s+(?:eine\s+)?(?:automation|regel)\s+an"
    r"|(?:ich\s+)?(?:möchte|moechte|will|wünsche\s+mir)\s+(?:eine\s+)?(?:automation|regel)"
    r"|(?:ich\s+)?(?:hätte|haette|wäre|waere)\s+gern(?:e)?\s+(?:eine\s+)?(?:automation|regel)"
    r")(?:\s*,)?\s+"
    r"(?:die|welche|die\s+mir)\s+"
    ,
    re.IGNORECASE,
)


def strip_automation_shell(text: str) -> tuple[str, bool]:
    """Remove optional automation meta-shell wrapper.

    Returns:
      (stripped_text, was_modified)
    """
    match = _AUTOMATION_SHELL_RE.match(text)
    if match is not None:
        stripped = text[match.end():].strip()
        if stripped:
            return stripped, True
    return text, False
