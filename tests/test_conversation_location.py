from __future__ import annotations

from ha_nlu.areas import AreaSnapshot
from ha_nlu.conversation_location import materialize_local_reference


AREA = AreaSnapshot("wohnzimmer", "Wohnzimmer", aliases=("Stube",))


def test_materializes_supported_local_references():
    assert materialize_local_reference("Mach hier das Licht aus", AREA) == (
        "Mach im Wohnzimmer das Licht aus"
    )
    assert materialize_local_reference(
        "Wie warm ist es in diesem Raum?", AREA
    ) == "Wie warm ist es im Wohnzimmer?"
    assert materialize_local_reference(
        "Sind in diesem Zimmer Fenster offen?", AREA
    ) == "Sind im Wohnzimmer Fenster offen?"


def test_local_reference_stays_untouched_without_area():
    assert materialize_local_reference("Mach hier das Licht aus", None) == (
        "Mach hier das Licht aus"
    )
