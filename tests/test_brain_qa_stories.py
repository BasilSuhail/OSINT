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
