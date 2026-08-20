"""HomeIntent V5 Teil 7/10 (V5.23, "Dry Run"): nlu/automation_confirmation.py's
classify_confirmation_reply() - the closed-vocabulary yes/no/unclear gate
for the "Soll diese Automation erstellt werden?" confirmation dialog.

Hass-free, pure-function module (see its own docstring) - tests call
classify_confirmation_reply() directly, same "exercise the pure function
directly" style tests/test_automation_validator.py already established.
"""

from __future__ import annotations

from ha_nlu.nlu.automation_confirmation import ConfirmationReply, classify_confirmation_reply


# ============================================================================
# Section 1: YES phrases
# ============================================================================


def test_ja_is_yes():
    assert classify_confirmation_reply("Ja") is ConfirmationReply.YES


def test_ja_bitte_is_yes():
    assert classify_confirmation_reply("Ja bitte") is ConfirmationReply.YES


def test_ok_is_yes():
    assert classify_confirmation_reply("Ok") is ConfirmationReply.YES


def test_passt_is_yes():
    assert classify_confirmation_reply("passt") is ConfirmationReply.YES


def test_yes_is_case_and_whitespace_insensitive():
    assert classify_confirmation_reply("  JA   ") is ConfirmationReply.YES


def test_yes_with_trailing_punctuation():
    assert classify_confirmation_reply("Ja!") is ConfirmationReply.YES
    assert classify_confirmation_reply("Ja.") is ConfirmationReply.YES
    assert classify_confirmation_reply("Ja,") is ConfirmationReply.YES


# ============================================================================
# Section 2: NO phrases
# ============================================================================


def test_nein_is_no():
    assert classify_confirmation_reply("Nein") is ConfirmationReply.NO


def test_nein_danke_is_no():
    assert classify_confirmation_reply("Nein danke") is ConfirmationReply.NO


def test_abbrechen_is_no():
    assert classify_confirmation_reply("Abbrechen") is ConfirmationReply.NO


def test_vergiss_es_is_no():
    assert classify_confirmation_reply("Vergiss es") is ConfirmationReply.NO


def test_no_is_case_and_whitespace_insensitive():
    assert classify_confirmation_reply("  NEIN  ") is ConfirmationReply.NO


# ============================================================================
# Section 3: UNCLEAR - Regel 4, "niemals raten" applied to the confirmation
# dialog itself
# ============================================================================


def test_unrelated_sentence_is_unclear():
    assert classify_confirmation_reply("Wie ist das Wetter?") is ConfirmationReply.UNCLEAR


def test_empty_string_is_unclear():
    assert classify_confirmation_reply("") is ConfirmationReply.UNCLEAR


def test_a_longer_sentence_merely_containing_ja_is_not_guessed_as_yes():
    # Substring "ja" appears inside "Garage" - exact-phrase match only
    # (Regel 4), never a "contains a yes-word" heuristic.
    assert classify_confirmation_reply("Mach das Garagenlicht an") is ConfirmationReply.UNCLEAR


def test_a_new_command_sentence_is_not_guessed_as_either():
    assert classify_confirmation_reply("Mach das Licht an") is ConfirmationReply.UNCLEAR
