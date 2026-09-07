from ha_nlu.response_planner import (
    DialogAct,
    GermanResponseRealizer,
    PersonaStyle,
    ResponsePlan,
    Urgency,
)


def test_jarvis_banter_depends_on_dialog_act_and_level():
    realizer = GermanResponseRealizer()

    confirm = realizer.realize(
        ResponsePlan(DialogAct.CONFIRM, "Das Licht ist aus.", banter_level=1),
        style=PersonaStyle.JARVIS,
    )
    question = realizer.realize(
        ResponsePlan(DialogAct.ASK, "Welches Licht?", banter_level=3),
        style=PersonaStyle.JARVIS,
    )

    assert confirm.endswith("Wie gewünscht.")
    assert question == "Welches Licht?"


def test_tts_never_reads_an_unbounded_result_list():
    rendered = GermanResponseRealizer().realize(
        ResponsePlan(DialogAct.INFORM, "; ".join(f"Gerät {i}" for i in range(100)))
    )

    assert len(rendered) < 400
    assert rendered.endswith("Weitere Details sind in Home Assistant sichtbar.")


def test_critical_message_remains_style_address_and_banter_free():
    plan = ResponsePlan(
        DialogAct.WARN,
        "CO erkannt. Verlasse das Gebäude.",
        urgency=Urgency.CRITICAL,
        address="Philipp",
        banter_level=3,
        category="carbon_monoxide",
    )

    assert GermanResponseRealizer().realize(
        plan, style=PersonaStyle.JARVIS
    ) == "CO erkannt. Verlasse das Gebäude."


def test_control_characters_disable_personal_address():
    rendered = GermanResponseRealizer().realize(
        ResponsePlan(DialogAct.INFORM, "Alles bereit.", address="Name\nAlarm")
    )

    assert rendered == "Alles bereit."
