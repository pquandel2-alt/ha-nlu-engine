"""The historical specialist follow-up router must stay retired."""

from __future__ import annotations

import ha_nlu.conversation as conversation
import ha_nlu.engine as engine


def test_legacy_device_followup_parser_is_not_exported() -> None:
    assert not hasattr(conversation, "match_device_control")
    assert not hasattr(engine, "match_device_control")
