"""RSS identity normalization and retained duplicate repair (#751)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import EventRow, StoryGistRow, StoryMemberRow, StoryRow
from app.housekeeping import prune_events
from app.persistence import upsert_events
from app.sources.rss_identity import (
    canonical_rss_event_id,
    changed_assigned_rss_story_ids,
    lock_rss_identity_keys,
    reconcile_rss_fragment_duplicates,
)
from app.sources.rss_news_fetcher import RssFeedConfig, entry_to_event

BBC_ARTICLE = "https://www.bbc.co.uk/news/articles/c1w1nnzgg2no"
BBC_LINK = f"{BBC_ARTICLE}?at_medium=RSS&at_campaign=rss"


def _rss_row(
    source_event_id: str,
    *,
    guid: str | None = None,
    link: str = BBC_LINK,
    fetched_at: datetime,
    occurred_at: datetime,
    title: str,
) -> EventRow:
    return EventRow(
        source="rss-bbc-uk",
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category="news",
        severity=0.15,
        confidence=None,
        keywords=["news"],
        country="GB",
        lat=None,
        lon=None,
        payload={
            "guid": guid if guid is not None else source_event_id,
            "source_url": link,
            "title": title,
        },
    )


def _story(title: str) -> StoryRow:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    return StoryRow(
        method_version="stories-v1.0",
        title=title,
        first_title=title,
        first_seen=now,
        last_seen=now,
        member_count=1,
        outlet_count=1,
        owner_count=1,
    )


def test_numeric_guid_fragment_matching_article_link_is_generated() -> None:
    assert canonical_rss_event_id(f"{BBC_ARTICLE}#4", BBC_LINK) == BBC_ARTICLE


def test_non_numeric_publisher_anchor_is_preserved() -> None:
    guid = f"{BBC_ARTICLE}#live-updates"
    assert canonical_rss_event_id(guid, BBC_LINK) == guid


def test_link_anchor_makes_numeric_fragment_meaningful() -> None:
    guid = f"{BBC_ARTICLE}#4"
    assert canonical_rss_event_id(guid, f"{BBC_ARTICLE}#4") == guid


def test_different_article_link_does_not_collapse() -> None:
    guid = f"{BBC_ARTICLE}#4"
    assert canonical_rss_event_id(guid, "https://www.bbc.co.uk/news/articles/other") == guid


def test_identity_bearing_link_query_does_not_collapse() -> None:
    guid = "https://www.bbc.co.uk/view#4"
    assert canonical_rss_event_id(guid, "https://www.bbc.co.uk/view?id=123") == guid


def test_other_publishers_are_not_canonicalized() -> None:
    guid = "https://example.com/article#4"
    assert canonical_rss_event_id(guid, "https://example.com/article") == guid


def test_non_url_guid_is_preserved() -> None:
    assert canonical_rss_event_id("publisher-story#4", BBC_LINK) == "publisher-story#4"


def test_different_scheme_or_port_does_not_collapse() -> None:
    assert canonical_rss_event_id(
        "http://www.bbc.co.uk/news/articles/c1w1nnzgg2no#4", BBC_LINK
    ).endswith("#4")
    assert canonical_rss_event_id(
        "https://www.bbc.co.uk:8443/news/articles/c1w1nnzgg2no#4", BBC_LINK
    ).endswith("#4")


def test_malformed_external_url_preserves_raw_guid() -> None:
    guid = "https://[invalid/news#4"
    assert canonical_rss_event_id(guid, BBC_LINK) == guid
    assert canonical_rss_event_id(f"{BBC_ARTICLE}#4", "https://[invalid/news") == (
        f"{BBC_ARTICLE}#4"
    )


def test_reconciliation_keeps_deterministic_newest_survivor(db_session: Session) -> None:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    oldest = _rss_row(
        f"{BBC_ARTICLE}#0",
        fetched_at=now - timedelta(hours=2),
        occurred_at=now - timedelta(hours=3),
        title="Old headline",
    )
    newest_fetch = _rss_row(
        f"{BBC_ARTICLE}#1",
        fetched_at=now,
        occurred_at=now - timedelta(hours=2),
        title="Current headline",
    )
    same_fetch_older_publication = _rss_row(
        f"{BBC_ARTICLE}#4",
        fetched_at=now,
        occurred_at=now - timedelta(hours=4),
        title="Stale headline",
    )
    db_session.add_all([oldest, newest_fetch, same_fetch_older_publication])
    db_session.commit()
    survivor_id = newest_fetch.id

    result = reconcile_rss_fragment_duplicates(db_session)
    db_session.commit()

    rows = db_session.execute(select(EventRow)).scalars().all()
    assert result.candidate_rows == 3
    assert result.duplicate_groups == 1
    assert result.deleted_rows == 2
    assert result.canonicalized_rows == 1
    assert len(rows) == 1
    assert rows[0].id == survivor_id
    assert rows[0].source_event_id == BBC_ARTICLE
    assert rows[0].payload["title"] == "Current headline"


def test_reconciliation_joins_late_legacy_row_to_existing_canonical(
    db_session: Session,
) -> None:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    canonical = _rss_row(
        BBC_ARTICLE,
        guid=f"{BBC_ARTICLE}#1",
        fetched_at=now - timedelta(hours=1),
        occurred_at=now - timedelta(hours=2),
        title="Canonical",
    )
    late_legacy = _rss_row(
        f"{BBC_ARTICLE}#4",
        fetched_at=now,
        occurred_at=now,
        title="Late legacy writer",
    )
    db_session.add_all([canonical, late_legacy])
    db_session.commit()
    late_id = late_legacy.id

    first = reconcile_rss_fragment_duplicates(db_session)
    db_session.commit()
    second = reconcile_rss_fragment_duplicates(db_session)
    db_session.commit()

    rows = db_session.execute(select(EventRow)).scalars().all()
    assert first.deleted_rows == 1
    assert len(rows) == 1
    assert rows[0].id == late_id
    assert rows[0].source_event_id == BBC_ARTICLE
    assert second.deleted_rows == 0
    assert second.canonicalized_rows == 0


def test_reconciliation_includes_unsuffixed_canonical_occupant(db_session: Session) -> None:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    existing = _rss_row(
        BBC_ARTICLE,
        guid=BBC_ARTICLE,
        fetched_at=now - timedelta(hours=1),
        occurred_at=now - timedelta(hours=1),
        title="Existing canonical",
    )
    fragment = _rss_row(
        f"{BBC_ARTICLE}#4",
        fetched_at=now,
        occurred_at=now,
        title="New fragment writer",
    )
    db_session.add_all([existing, fragment])
    db_session.commit()
    fragment_id = fragment.id

    result = reconcile_rss_fragment_duplicates(db_session)
    db_session.commit()

    rows = db_session.execute(select(EventRow)).scalars().all()
    assert result.deleted_rows == 1
    assert len(rows) == 1
    assert rows[0].id == fragment_id
    assert rows[0].source_event_id == BBC_ARTICLE


def test_reconciliation_repairs_memberships_and_empty_story(db_session: Session) -> None:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    loser = _rss_row(
        f"{BBC_ARTICLE}#0",
        fetched_at=now - timedelta(minutes=5),
        occurred_at=now - timedelta(minutes=5),
        title="Old",
    )
    survivor = _rss_row(
        f"{BBC_ARTICLE}#4",
        fetched_at=now,
        occurred_at=now,
        title="New",
    )
    kept_story = _story("New")
    duplicate_story = _story("Old")
    db_session.add_all([loser, survivor, kept_story, duplicate_story])
    db_session.flush()
    db_session.add_all(
        [
            StoryMemberRow(event_id=survivor.id, story_id=kept_story.id, similarity=1.0),
            StoryMemberRow(event_id=loser.id, story_id=duplicate_story.id, similarity=1.0),
        ]
    )
    db_session.commit()

    result = reconcile_rss_fragment_duplicates(db_session)
    db_session.commit()

    memberships = db_session.execute(select(StoryMemberRow)).scalars().all()
    assert result.deleted_story_memberships == 1
    assert result.deleted_stories == 1
    assert [(member.event_id, member.story_id) for member in memberships] == [
        (survivor.id, kept_story.id)
    ]
    assert db_session.get(StoryRow, duplicate_story.id) is None
    assert db_session.get(StoryRow, kept_story.id).member_count == 1


def test_reconciliation_transfers_only_loser_membership(db_session: Session) -> None:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    loser = _rss_row(
        f"{BBC_ARTICLE}#0",
        fetched_at=now - timedelta(minutes=5),
        occurred_at=now - timedelta(minutes=5),
        title="Old",
    )
    survivor = _rss_row(
        f"{BBC_ARTICLE}#4",
        fetched_at=now,
        occurred_at=now,
        title="New",
    )
    story = _story("Old")
    db_session.add_all([loser, survivor, story])
    db_session.flush()
    db_session.add(StoryMemberRow(event_id=loser.id, story_id=story.id, similarity=1.0))
    db_session.commit()

    result = reconcile_rss_fragment_duplicates(db_session)
    db_session.commit()

    membership = db_session.execute(select(StoryMemberRow)).scalar_one()
    assert result.deleted_story_memberships == 0
    assert membership.event_id == survivor.id
    assert membership.story_id == story.id
    assert db_session.get(StoryRow, story.id).title == "New"


def test_reconciliation_invalidates_surviving_story_derivations(db_session: Session) -> None:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    loser = _rss_row(
        f"{BBC_ARTICLE}#0",
        fetched_at=now - timedelta(minutes=5),
        occurred_at=now - timedelta(minutes=5),
        title="Old",
    )
    survivor = _rss_row(
        f"{BBC_ARTICLE}#4",
        fetched_at=now,
        occurred_at=now,
        title="New",
    )
    story = _story("Old")
    db_session.add_all([loser, survivor, story])
    db_session.flush()
    db_session.add_all(
        [
            StoryMemberRow(event_id=loser.id, story_id=story.id, similarity=1.0),
            StoryMemberRow(event_id=survivor.id, story_id=story.id, similarity=1.0),
            StoryGistRow(
                story_id=story.id,
                gist="Derived from duplicate inputs",
                category="other",
                escalating="stable",
                model="test",
                method_version="test-v1",
            ),
        ]
    )
    db_session.commit()

    #: The clock has to come from the test. Whether derivations are dropped
    #: or preserved turns on `story.last_seen` against `now - WINDOW_HOURS`,
    #: and `now` defaults to the real clock — so a story pinned to a fixed
    #: date drifts out of the window as real time passes, and this assertion
    #: quietly starts describing the opposite behaviour. It did: both this
    #: test and the historical one below went green for three days and then
    #: failed the moment the wall clock crossed 72 hours past the fixture.
    reconcile_rss_fragment_duplicates(db_session, now=now)
    db_session.commit()

    assert db_session.execute(select(StoryGistRow)).scalars().all() == []
    assert db_session.get(StoryRow, story.id).member_count == 1


def test_reconciliation_preserves_historical_story_derivations(db_session: Session) -> None:
    now = datetime.now(UTC)
    occurred_at = now - timedelta(days=5)
    loser = _rss_row(
        f"{BBC_ARTICLE}#0",
        fetched_at=occurred_at,
        occurred_at=occurred_at,
        title="Old",
    )
    survivor = _rss_row(
        f"{BBC_ARTICLE}#4",
        fetched_at=occurred_at + timedelta(minutes=5),
        occurred_at=occurred_at + timedelta(minutes=5),
        title="New",
    )
    story = _story("Old")
    story.first_seen = occurred_at
    story.last_seen = occurred_at
    db_session.add_all([loser, survivor, story])
    db_session.flush()
    db_session.add_all(
        [
            StoryMemberRow(event_id=loser.id, story_id=story.id, similarity=1.0),
            StoryMemberRow(event_id=survivor.id, story_id=story.id, similarity=1.0),
            StoryGistRow(
                story_id=story.id,
                gist="Historical evidence snapshot",
                category="other",
                escalating="stable",
                model="test",
                method_version="test-v1",
            ),
        ]
    )
    db_session.commit()

    reconcile_rss_fragment_duplicates(db_session, now=now)
    db_session.commit()

    assert db_session.execute(select(StoryGistRow)).scalar_one().gist == (
        "Historical evidence snapshot"
    )
    assert db_session.get(StoryRow, story.id).member_count == 1


def test_reconciliation_preserves_historical_aggregates_with_pruned_members(
    db_session: Session,
) -> None:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    loser = _rss_row(
        f"{BBC_ARTICLE}#0",
        fetched_at=now - timedelta(minutes=5),
        occurred_at=now - timedelta(minutes=5),
        title="Old duplicate",
    )
    survivor = _rss_row(
        f"{BBC_ARTICLE}#4",
        fetched_at=now,
        occurred_at=now,
        title="New duplicate",
    )
    story = _story("Historical title")
    story.first_seen = now - timedelta(days=20)
    story.last_seen = now - timedelta(days=1)
    story.member_count = 3
    story.outlet_count = 3
    story.owner_count = 2
    db_session.add_all([loser, survivor, story])
    db_session.flush()
    db_session.add_all(
        [
            StoryMemberRow(event_id=loser.id, story_id=story.id, similarity=1.0),
            StoryMemberRow(event_id=survivor.id, story_id=story.id, similarity=1.0),
            # Normal retention leaves this membership after deleting its event.
            StoryMemberRow(event_id=999_999, story_id=story.id, similarity=0.8),
            StoryGistRow(
                story_id=story.id,
                gist="Stale retained evidence",
                category="other",
                escalating="stable",
                model="test",
                method_version="test-v1",
            ),
        ]
    )
    db_session.commit()

    #: The test owns the clock, for the reason spelled out in
    #: test_reconciliation_invalidates_surviving_story_derivations.
    reconcile_rss_fragment_duplicates(db_session, now=now)
    db_session.commit()

    refreshed = db_session.get(StoryRow, story.id)
    assert refreshed.member_count == 2
    assert refreshed.outlet_count == 3
    assert refreshed.owner_count == 2
    assert refreshed.first_seen.replace(tzinfo=UTC) == now - timedelta(days=20)
    assert refreshed.last_seen.replace(tzinfo=UTC) == now
    assert refreshed.title == "New duplicate"
    assert db_session.execute(select(StoryGistRow)).scalars().all() == []


def test_reconciliation_preserves_publisher_defined_fragments(db_session: Session) -> None:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    anchored = _rss_row(
        f"{BBC_ARTICLE}#chapter-4",
        link=f"{BBC_ARTICLE}#chapter-4",
        fetched_at=now,
        occurred_at=now,
        title="Anchored section",
    )
    db_session.add(anchored)
    db_session.commit()

    result = reconcile_rss_fragment_duplicates(db_session)
    db_session.commit()

    assert result.candidate_rows == 0
    assert db_session.get(EventRow, anchored.id).source_event_id.endswith("#chapter-4")


def test_canonical_refresh_is_idempotent(db_session: Session) -> None:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    config = RssFeedConfig(
        source="rss-bbc-uk",
        url="https://feeds.bbci.co.uk/news/uk/rss.xml",
        default_country="GB",
        pretty_name="BBC UK",
    )
    first = entry_to_event(
        {
            "title": "Original headline",
            "link": BBC_LINK,
            "id": f"{BBC_ARTICLE}#0",
        },
        config=config,
        fetched_at=now - timedelta(minutes=5),
    )
    refresh = entry_to_event(
        {
            "title": "Updated headline",
            "link": BBC_LINK,
            "id": f"{BBC_ARTICLE}#4",
        },
        config=config,
        fetched_at=now,
    )
    assert first is not None
    assert refresh is not None

    upsert_events([first], db_session)
    upsert_events([refresh], db_session)
    db_session.commit()

    rows = db_session.execute(select(EventRow)).scalars().all()
    assert len(rows) == 1
    assert rows[0].source_event_id == BBC_ARTICLE
    assert rows[0].payload["title"] == "Updated headline"


def test_ingest_batch_keeps_newest_canonical_variant(db_session: Session) -> None:
    fetched_at = datetime.now(UTC)
    config = RssFeedConfig(
        source="rss-bbc-uk",
        url="https://feeds.bbci.co.uk/news/uk/rss.xml",
        default_country="GB",
        pretty_name="BBC UK",
    )
    newer = entry_to_event(
        {
            "title": "New headline",
            "link": BBC_LINK,
            "id": f"{BBC_ARTICLE}#4",
            "published_parsed": (2026, 8, 2, 17, 0, 0, 0, 0, 0),
        },
        config=config,
        fetched_at=fetched_at,
    )
    older = entry_to_event(
        {
            "title": "Old headline",
            "link": BBC_LINK,
            "id": f"{BBC_ARTICLE}#0",
            "published_parsed": (2026, 8, 2, 16, 0, 0, 0, 0, 0),
        },
        config=config,
        fetched_at=fetched_at,
    )
    assert newer is not None
    assert older is not None

    upsert_events([newer, older], db_session, batch_size=1)
    db_session.commit()

    row = db_session.execute(select(EventRow)).scalar_one()
    assert row.payload["title"] == "New headline"
    assert row.occurred_at.replace(tzinfo=UTC) == newer.occurred_at


def test_delayed_canonical_refresh_cannot_replace_newer_story(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    config = RssFeedConfig(
        source="rss-bbc-uk",
        url="https://feeds.bbci.co.uk/news/uk/rss.xml",
        default_country="GB",
        pretty_name="BBC UK",
    )
    newer = entry_to_event(
        {
            "title": "New headline",
            "link": BBC_LINK,
            "id": f"{BBC_ARTICLE}#4",
            "published_parsed": (2026, 8, 2, 17, 0, 0, 0, 0, 0),
        },
        config=config,
        fetched_at=now,
    )
    delayed = entry_to_event(
        {
            "title": "Delayed old headline",
            "link": BBC_LINK,
            "id": f"{BBC_ARTICLE}#0",
            "published_parsed": (2026, 8, 2, 16, 0, 0, 0, 0, 0),
        },
        config=config,
        fetched_at=now - timedelta(minutes=5),
    )
    assert newer is not None
    assert delayed is not None
    upsert_events([newer], db_session)
    event = db_session.execute(select(EventRow)).scalar_one()
    story = _story("New headline")
    db_session.add(story)
    db_session.flush()
    db_session.add_all(
        [
            StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0),
            StoryGistRow(
                story_id=story.id,
                gist="Still current",
                category="other",
                escalating="stable",
                model="test",
                method_version="test-v1",
            ),
        ]
    )
    db_session.commit()

    affected = upsert_events([delayed], db_session)
    db_session.commit()
    db_session.expire_all()

    row = db_session.execute(select(EventRow)).scalar_one()
    assert affected == 0
    assert row.payload["title"] == "New headline"
    assert row.fetched_at.replace(tzinfo=UTC) == newer.fetched_at
    assert db_session.get(StoryRow, story.id).title == "New headline"
    assert db_session.execute(select(StoryGistRow)).scalar_one().gist == "Still current"


def test_canonical_content_refresh_updates_assigned_story(db_session: Session) -> None:
    now = datetime.now(UTC)
    config = RssFeedConfig(
        source="rss-bbc-uk",
        url="https://feeds.bbci.co.uk/news/uk/rss.xml",
        default_country="GB",
        pretty_name="BBC UK",
    )
    first = entry_to_event(
        {"title": "Original headline", "link": BBC_LINK, "id": f"{BBC_ARTICLE}#0"},
        config=config,
        fetched_at=now - timedelta(minutes=5),
    )
    refresh = entry_to_event(
        {"title": "Updated headline", "link": BBC_LINK, "id": f"{BBC_ARTICLE}#4"},
        config=config,
        fetched_at=now,
    )
    assert first is not None
    assert refresh is not None
    upsert_events([first], db_session)
    event = db_session.execute(select(EventRow)).scalar_one()
    story = _story("Original headline")
    story.first_seen = first.occurred_at
    story.last_seen = first.occurred_at
    db_session.add(story)
    db_session.flush()
    db_session.add_all(
        [
            StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0),
            StoryGistRow(
                story_id=story.id,
                gist="Original gist",
                category="other",
                escalating="stable",
                model="test",
                method_version="test-v1",
            ),
        ]
    )
    db_session.commit()

    upsert_events([refresh], db_session)
    db_session.commit()

    updated = db_session.get(StoryRow, story.id)
    assert updated.title == "Updated headline"
    assert updated.last_seen.replace(tzinfo=UTC) == refresh.occurred_at
    assert db_session.execute(select(StoryGistRow)).scalars().all() == []


def test_fragment_only_refresh_preserves_assigned_story_derivations(
    db_session: Session,
) -> None:
    now = datetime.now(UTC)
    config = RssFeedConfig(
        source="rss-bbc-uk",
        url="https://feeds.bbci.co.uk/news/uk/rss.xml",
        default_country="GB",
        pretty_name="BBC UK",
    )
    first = entry_to_event(
        {
            "title": "Unchanged headline",
            "link": BBC_LINK,
            "id": f"{BBC_ARTICLE}#0",
        },
        config=config,
        fetched_at=now - timedelta(minutes=5),
    )
    refresh = entry_to_event(
        {
            "title": "Unchanged headline",
            "link": BBC_LINK,
            "id": f"{BBC_ARTICLE}#4",
        },
        config=config,
        fetched_at=now,
    )
    assert first is not None
    assert refresh is not None
    upsert_events([first], db_session)
    event = db_session.execute(select(EventRow)).scalar_one()
    story = _story("Unchanged headline")
    story.first_seen = first.occurred_at
    story.last_seen = first.occurred_at
    db_session.add(story)
    db_session.flush()
    db_session.add_all(
        [
            StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0),
            StoryGistRow(
                story_id=story.id,
                gist="Still valid",
                category="other",
                escalating="stable",
                model="test",
                method_version="test-v1",
            ),
        ]
    )
    db_session.commit()

    upsert_events([refresh], db_session)
    db_session.commit()

    assert refresh.occurred_at != first.occurred_at
    assert db_session.execute(select(StoryGistRow)).scalar_one().gist == "Still valid"


def test_changed_membership_lookup_is_batched(db_session: Session) -> None:
    now = datetime.now(UTC)
    events = [
        _rss_row(
            f"publisher-id-{index}",
            fetched_at=now,
            occurred_at=now,
            title="Old headline",
        )
        for index in range(1_001)
    ]
    stories = [_story("Old headline") for _index in range(1_001)]
    db_session.add_all([*events, *stories])
    db_session.flush()
    db_session.add_all(
        StoryMemberRow(event_id=event.id, story_id=story.id, similarity=1.0)
        for event, story in zip(events, stories, strict=True)
    )
    db_session.commit()
    incoming = [
        {
            "source": event.source,
            "source_event_id": event.source_event_id,
            "occurred_at": now,
            "payload": {"title": "New headline", "summary": None},
        }
        for event in events
    ]

    changed = changed_assigned_rss_story_ids(db_session, incoming)

    assert changed == {story.id for story in stories}


def test_large_rss_write_uses_one_advisory_lock() -> None:
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "postgresql"
    keys = {("rss-bbc-uk", f"article-{index}") for index in range(10_000)}

    lock_rss_identity_keys(session, keys)

    session.execute.assert_called_once()
    statement = str(session.execute.call_args.args[0])
    assert "pg_advisory_xact_lock(" in statement
    assert "jsonb_array_elements" not in statement


def test_retention_reconciliation_is_idempotent(db_session: Session) -> None:
    now = datetime(2026, 8, 2, 17, 0, tzinfo=UTC)
    db_session.add_all(
        [
            _rss_row(
                f"{BBC_ARTICLE}#0",
                fetched_at=now - timedelta(minutes=2),
                occurred_at=now - timedelta(minutes=2),
                title="Old",
            ),
            _rss_row(
                f"{BBC_ARTICLE}#4",
                fetched_at=now,
                occurred_at=now,
                title="New",
            ),
        ]
    )
    db_session.commit()

    first = prune_events(db_session, now=now)
    db_session.commit()
    second = prune_events(db_session, now=now)
    db_session.commit()

    assert first["rss-fragment-duplicates"] == 1
    assert second["rss-fragment-duplicates"] == 0
    rows = db_session.execute(select(EventRow)).scalars().all()
    assert len(rows) == 1
    assert rows[0].source_event_id == BBC_ARTICLE
