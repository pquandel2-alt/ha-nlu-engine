"""Integration Wave Migration Step 2: isolated tests for
nlu/automation_sentence_split.py's split_trigger_action() - pure text
splitting, no parser/entity involvement (see that module's own docstring
for the scope decision this covers: trigger+action only, first comma
only).
"""

from __future__ import annotations

from ha_nlu.nlu.automation_sentence_split import split_trigger_action


def test_splits_simple_trigger_and_action():
    result = split_trigger_action("Wenn das Küchenfenster geöffnet wird, schalte das Küchenlicht ein.")
    assert result == ("Wenn das Küchenfenster geöffnet wird", "schalte das Küchenlicht ein.")


def test_splits_only_on_first_comma_leaving_multi_action_text_intact():
    result = split_trigger_action("Wenn das Fenster aufgeht, schalte das Licht ein, schalte den Ventilator aus.")
    assert result == ("Wenn das Fenster aufgeht", "schalte das Licht ein, schalte den Ventilator aus.")


def test_no_comma_returns_none():
    assert split_trigger_action("Wenn das Fenster aufgeht schalte das Licht ein") is None


def test_empty_trigger_half_returns_none():
    assert split_trigger_action(", schalte das Licht ein") is None


def test_empty_action_half_returns_none():
    assert split_trigger_action("Wenn das Fenster aufgeht,") is None


def test_whitespace_only_halves_return_none():
    assert split_trigger_action("Wenn das Fenster aufgeht,   ") is None


def test_strips_surrounding_whitespace_from_both_halves():
    result = split_trigger_action("  Wenn das Fenster aufgeht  ,  schalte das Licht ein  ")
    assert result == ("Wenn das Fenster aufgeht", "schalte das Licht ein")
