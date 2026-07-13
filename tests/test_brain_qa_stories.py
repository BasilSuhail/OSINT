from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import enrich, qa
from app.db_models import (
    Base,
    EventRow,
    StoryCorroborationRow,
    StoryDisagreementRow,
    StoryGistRow,
    StoryMemberRow,
    StoryRow,
    StorySensorCheckRow,
)


def _seed(now):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    s = Session(engine)
    story = StoryRow(
        title="Border clashes reported",
        first_seen=now - timedelta(hours=2),
        last_seen=now,
        member_count=3,
        outlet_count=8,
        owner_count=4,
        method_version="stories-v1.0",
    )
    s.add(story)
    s.flush()
    sid = story.id
    ev = EventRow(
        source="reuters",
        source_event_id="e1",
        occurred_at=now,
        fetched_at=now,
        category="conflict",
        payload={"title": "Border clashes reported"},
    )
    s.add(ev)
    s.flush()
    s.add_all(
        [
            StoryMemberRow(event_id=ev.id, story_id=sid, similarity=1.0),
            StoryCorroborationRow(
                story_id=sid,
                score=0.82,
                components={},
                method_version="corroboration-v1.0",
                computed_at=now,
            ),
            StoryDisagreementRow(
                story_id=sid,
                divergence=0.7,
                components={},
                method_version="disagreement-v1.0",
                computed_at=now,
            ),
            StorySensorCheckRow(
                story_id=sid,
                claim_type="earthquake",
                verdict="confirmed",
                method_version="corroboration-v1.0",
                checked_at=now,
            ),
            StoryGistRow(
                story_id=sid,
                gist="Clashes at the frontier.",
                category="conflict",
                escalating="yes",
                model="m",
                method_version=enrich.METHOD_VERSION,
                created_at=now,
            ),
        ]
    )
    s.commit()
    return s, sid


def _add_story(
    session,
    now,
    *,
    title,
    source,
    source_event_id,
    outlet_count,
    member_count=2,
    owner_count=2,
    payload=None,
    keywords=None,
    category="conflict",
    country=None,
    gist=None,
):
    story = StoryRow(
        title=title,
        first_seen=now - timedelta(hours=2),
        last_seen=now,
        member_count=member_count,
        outlet_count=outlet_count,
        owner_count=owner_count,
        method_version="stories-v1.0",
    )
    session.add(story)
    session.flush()
    event = EventRow(
        source=source,
        source_event_id=source_event_id,
        occurred_at=now,
        fetched_at=now,
        category=category,
        keywords=keywords or [],
        country=country,
        payload=payload or {"title": title},
    )
    session.add(event)
    session.flush()
    session.add(StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0))
    if gist is not None:
        session.add(
            StoryGistRow(
                story_id=story.id,
                gist=gist,
                category=category,
                escalating="no",
                model="m",
                method_version=enrich.METHOD_VERSION,
                created_at=now,
            )
        )
    session.commit()
    return story.id


def test_build_qa_stories_carries_trust_signals_and_sources():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    session, sid = _seed(now)
    out = qa.build_qa_stories(session, now=now)
    assert len(out) == 1
    st = out[0]
    assert st["n"] == 1 and st["story_id"] == sid
    assert st["gist"] == "Clashes at the frontier."
    assert st["corroboration"] == 0.82
    assert st["divergence"] == 0.7
    assert st["contested"] is True  # 0.7 >= threshold
    assert st["sensor"] == {"earthquake": "confirmed"}
    assert "reuters" in [o.lower() for o in st["sources"]]


def test_build_qa_context_includes_stories():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    session, _ = _seed(now)
    ctx = qa.build_qa_context(session, now=now)
    assert isinstance(ctx["stories"], list) and ctx["stories"]


def test_build_qa_stories_prefers_question_relevant_story_over_louder_story():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    loud_id = _add_story(
        session,
        now,
        title="Flooding reported across coastal towns",
        source="bbc",
        source_event_id="loud",
        outlet_count=20,
    )
    iran_id = _add_story(
        session,
        now,
        title="Iran border clashes intensify",
        source="reuters",
        source_event_id="iran",
        outlet_count=3,
    )

    out = qa.build_qa_stories(session, now=now, question="what is happening with Iran?")

    assert [story["story_id"] for story in out] == [iran_id]
    assert loud_id not in [story["story_id"] for story in out]


def test_build_qa_stories_matches_member_event_metadata():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    story_id = _add_story(
        session,
        now,
        title="Regional security alert",
        source="aljazeera",
        source_event_id="metadata",
        outlet_count=4,
        country="IR",
        keywords=["strait", "hormuz"],
        payload={"title": "Shipping disruption near the Strait of Hormuz"},
    )

    out = qa.build_qa_stories(session, now=now, question="hormuz shipping")

    assert [story["story_id"] for story in out] == [story_id]

    by_country_code = qa.build_qa_stories(session, now=now, question="what about IR?")

    assert [story["story_id"] for story in by_country_code] == [story_id]


def test_build_qa_stories_falls_back_to_loudest_for_general_question():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    quiet_id = _add_story(
        session,
        now,
        title="Quiet story",
        source="reuters",
        source_event_id="quiet",
        outlet_count=2,
    )
    loud_id = _add_story(
        session,
        now,
        title="Loud story",
        source="bbc",
        source_event_id="loud",
        outlet_count=9,
    )

    out = qa.build_qa_stories(session, now=now, question="what is happening today?")

    assert [story["story_id"] for story in out] == [loud_id, quiet_id]


def test_build_qa_stories_returns_empty_when_specific_question_has_no_match():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    _add_story(
        session,
        now,
        title="Flooding reported across coastal towns",
        source="bbc",
        source_event_id="flood",
        outlet_count=20,
    )

    out = qa.build_qa_stories(session, now=now, question="iran hormuz shipping")

    assert out == []
