from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import context
from app.db_models import Base, JobRunRow, StoryRow


def _session_with_data(now):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        StoryRow(
            title="Border clashes reported",
            first_seen=now - timedelta(hours=3),
            last_seen=now,
            member_count=12,
            outlet_count=7,
            owner_count=3,
            method_version="stories-v1.0",
        )
    )
    session.add(JobRunRow(job="cluster_stories", status="done", heartbeat_at=now))
    session.add(JobRunRow(job="compute_composite", status="failed", heartbeat_at=now))
    session.commit()
    return session


def test_build_snapshot_has_core_sections():
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    session = _session_with_data(now)
    snap = context.build_snapshot(session, now=now)
    assert snap["top_stories"][0]["title"] == "Border clashes reported"
    assert snap["jobs"]["failed"] == 1
    assert "as_of" in snap


def test_input_digest_is_stable_and_prefixed():
    snap = {"top_stories": [], "jobs": {}, "as_of": "x"}
    d1 = context.input_digest(snap)
    d2 = context.input_digest(dict(snap))
    assert d1 == d2
    assert d1.startswith("sha256:")


def test_build_prompt_is_bounded():
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    session = _session_with_data(now)
    prompt = context.build_prompt(context.build_snapshot(session, now=now))
    assert "headline" in prompt  # asks for the schema
    assert len(prompt) < 6000  # stays well inside num_ctx 2048
