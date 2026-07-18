"""Story ages + analyst voice for direct/meta questions (#469).

Live failure: "how old of the data do u have" guessed from as_of because
stories carried no dates; "has it faught back or no?" opened with
"The provided context does not contain…" instead of the verdict.
"""

from datetime import UTC, datetime, timedelta

from app.brain import qa
from tests.test_brain_qa_semantic import _fresh_session
from tests.test_brain_qa_stories import _add_story


def test_age_hours_handles_aware_and_naive():
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    assert qa._age_hours(now - timedelta(hours=5), now) == 5.0
    assert qa._age_hours(now.replace(tzinfo=None) - timedelta(minutes=90), now) == 1.5


def test_stories_carry_age_hours():
    seeded = datetime(2026, 7, 17, 7, 0, tzinfo=UTC)
    asked = seeded + timedelta(hours=5)
    session = _fresh_session()
    _add_story(
        session,
        seeded,
        title="Strikes resume at the border",
        source="reuters",
        source_event_id="e1",
        outlet_count=3,
    )

    out = qa.build_qa_stories(session, now=asked, question="war border")

    assert out[0]["age"] == "5.0 hours ago"  # unit in the value (#475)


def test_prompt_carries_voice_verdict_and_freshness_rules():
    prompt = qa.build_qa_prompt({"stories": []}, "has iran fought back?")
    assert "how long ago the story last moved, always in hours" in prompt
    assert "never say 'the context'" in prompt
    assert "local reporting shows" in prompt
    assert "Direct yes/no questions get a direct opening" in prompt
    assert "Ages are ALWAYS hours" in prompt
    assert "inside the asked window" in prompt
    #: text prompt inherits every rule.
    text = qa.build_qa_text_prompt({"stories": []}, "has iran fought back?")
    assert "Direct yes/no questions get a direct opening" in text
