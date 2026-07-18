"""Member headlines + keywords in the Q&A story context (#482).

Live 2026-07-18 hard-QA: "where did iran launch them" could not be
answered because the model only ever saw title + one-line gist. The
cluster's member articles carry the specifics — now the model sees them.
"""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import qa
from app.db_models import Base, EventRow, StoryMemberRow
from tests.test_brain_qa_stories import _add_story

NOW = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


def _fresh_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _add_member(session, story_id, *, source, event_id, title, keywords=()):
    event = EventRow(
        source=source,
        source_event_id=event_id,
        occurred_at=NOW,
        fetched_at=NOW,
        category="conflict",
        keywords=list(keywords),
        payload={"title": title},
    )
    session.add(event)
    session.flush()
    session.add(StoryMemberRow(event_id=event.id, story_id=story_id, similarity=0.9))
    session.commit()


def test_stories_carry_member_headlines_and_keywords():
    session = _fresh_session()
    sid = _add_story(
        session,
        NOW,
        title="Iran launches fresh attacks on American facilities in Gulf",
        source="aj",
        source_event_id="e1",
        outlet_count=3,
        keywords=["iran", "gulf"],
    )
    _add_member(
        session,
        sid,
        source="reuters",
        event_id="e2",
        title="Iran strikes US base near Bandar Abbas, ships hit in Strait of Hormuz",
        keywords=["bandar abbas", "hormuz", "iran"],
    )

    out = qa.build_qa_stories(session, now=NOW, question="iran gulf attacks")

    story = out[0]
    #: The story title itself is not repeated in details.
    assert story["details"] == [
        "Iran strikes US base near Bandar Abbas, ships hit in Strait of Hormuz"
    ]
    #: "iran" appears in two members — frequency puts it first.
    assert story["keywords"][0] == "iran"
    assert "bandar abbas" in story["keywords"]


def test_details_deduplicate_and_cap():
    session = _fresh_session()
    sid = _add_story(
        session,
        NOW,
        title="Iran attacks Gulf facilities",
        source="aj",
        source_event_id="e1",
        outlet_count=3,
    )
    #: Same headline (different case) collapses; distinct ones cap at three.
    _add_member(session, sid, source="bbc", event_id="d1", title="IRAN ATTACKS GULF FACILITIES")
    for i in range(4):
        _add_member(session, sid, source=f"s{i}", event_id=f"d{i + 2}", title=f"Angle {i}")

    out = qa.build_qa_stories(session, now=NOW, question="iran gulf attacks")

    details = out[0]["details"]
    assert len(details) == 3
    assert all(d.startswith("Angle") for d in details)


def test_prompt_documents_details_and_specifics_rule():
    prompt = qa.build_qa_prompt({"stories": []}, "where did iran launch them?")
    assert "headlines from the cluster's own member articles" in prompt
    assert "mine the stories' details and keywords" in prompt
    text = qa.build_qa_text_prompt({"stories": []}, "where did iran launch them?")
    assert "mine the stories' details and keywords" in text
