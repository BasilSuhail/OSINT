"""Sweeping already-stored gists that carry invented figures (#553)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.brain import enrich, gist_cleanup
from app.db_models import Base, EventRow, StoryGistRow, StoryMemberRow, StoryRow


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _add_story(session, *, titles: list[str], gist: str, method_version: str | None = None) -> int:
    now = datetime.now(UTC)
    story = StoryRow(
        title=titles[0],
        first_seen=now - timedelta(hours=2),
        last_seen=now,
        member_count=len(titles),
        outlet_count=len(titles),
        owner_count=1,
        method_version="stories-v1.0",
    )
    session.add(story)
    session.flush()
    for i, title in enumerate(titles):
        event = EventRow(
            source="gdelt",
            source_event_id=f"e{story.id}-{i}",
            occurred_at=now,
            fetched_at=now,
            category="disaster",
            payload={"title": title},
        )
        session.add(event)
        session.flush()
        session.add(StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0))
    session.add(
        StoryGistRow(
            story_id=story.id,
            gist=gist,
            category="disaster",
            escalating="unclear",
            model="qwen2.5:1.5b",
            method_version=method_version or enrich.METHOD_VERSION,
        )
    )
    session.commit()
    return story.id


def test_finds_a_gist_whose_figure_no_headline_carries():
    session = _session()
    story_id = _add_story(
        session,
        titles=["Magnitude 5.1 earthquake in central Peru leaves at least one dead"],
        gist="A magnitude 5.1 earthquake struck central Peru, killing at least five.",
    )
    offenders = gist_cleanup.find_offenders(session)
    assert [o.story_id for o in offenders] == [story_id]
    assert offenders[0].figures == [5.0]


def test_leaves_a_grounded_gist_alone():
    session = _session()
    _add_story(
        session,
        titles=["Strike kills 12", "Thirty wounded in overnight strike"],
        gist="The strike killed 12 and wounded 30.",
    )
    assert gist_cleanup.find_offenders(session) == []


def test_grounds_against_every_member_headline_not_just_the_prompted_five():
    # The prompt carries MAX_TITLES headlines, but the sweep reads all of them.
    # A figure grounded by a headline the model never saw is a coincidence, not
    # an invention — and the sweep deletes rows, so it errs toward keeping them.
    session = _session()
    titles = [f"Filler headline {i}" for i in range(enrich.MAX_TITLES)]
    titles.append("Death toll reaches 47 in provincial capital")
    _add_story(session, titles=titles, gist="The death toll reached 47.")
    assert gist_cleanup.find_offenders(session) == []


def test_ignores_gists_from_an_older_method_version():
    session = _session()
    _add_story(
        session,
        titles=["One dead in quake"],
        gist="Five dead in quake.",
        method_version="enrich-v0.9",
    )
    assert gist_cleanup.find_offenders(session) == []


def test_delete_offenders_removes_only_the_flagged_rows():
    session = _session()
    bad = _add_story(
        session,
        titles=["One dead in quake"],
        gist="Five dead in quake.",
    )
    good = _add_story(
        session,
        titles=["Twelve dead in flood"],
        gist="12 died in the flood.",
    )
    offenders = gist_cleanup.find_offenders(session)
    assert gist_cleanup.delete_offenders(session, offenders) == 1

    remaining = session.execute(select(StoryGistRow.story_id)).scalars().all()
    assert remaining == [good]
    assert bad not in remaining


def test_delete_offenders_on_an_empty_list_is_a_no_op():
    session = _session()
    _add_story(session, titles=["One dead in quake"], gist="One dead in the quake.")
    assert gist_cleanup.delete_offenders(session, []) == 0
    assert session.execute(select(StoryGistRow)).scalars().all() != []


def test_offender_carries_context_for_review():
    # The script prints these before anything is deleted, so a human can see
    # what the check objected to.
    session = _session()
    _add_story(
        session,
        titles=["Michigan health officials identify potential source of parasite outbreak"],
        gist="Cases in the parasite outbreak have surpassed 2,800.",
    )
    offender = gist_cleanup.find_offenders(session)[0]
    assert offender.figures == [2800.0]
    assert "2,800" in offender.gist
    assert offender.titles and "Michigan" in offender.titles[0]
