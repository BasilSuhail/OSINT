"""Canonical identity and retained-row repair for RSS stories (#751).

Some BBC feeds reuse one article URL while suffixing the GUID with generated
numeric fragments (``#0``, ``#1``, ``#4``).  Treating the raw GUID as identity
creates a new event for every suffix.  The fragment is safe to remove only
when the fragment-less GUID names the same HTTP article as the entry link and
the link itself has no fragment.  Publisher-defined anchors therefore remain
distinct.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from sqlalchemy import delete, or_, select, text
from sqlalchemy.orm import Session

from app.db_models import (
    EventRow,
    StoryClaimRow,
    StoryCorroborationRow,
    StoryDisagreementRow,
    StoryEmbeddingRow,
    StoryGistRow,
    StoryMemberRow,
    StoryReviewRow,
    StoryRow,
    StorySensorCheckRow,
)
from app.sources.rss_registry import content_owner_map
from app.stories.independence import owner_count
from app.stories.task import WINDOW_HOURS

_BBC_HOST_SUFFIXES = (".bbc.co.uk", ".bbc.com")
_BBC_HOSTS = {"bbc.co.uk", "bbc.com"}
_TRACKING_QUERY_KEYS = {
    "at_campaign",
    "at_medium",
    "utm_campaign",
    "utm_content",
    "utm_id",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def canonical_rss_event_id(guid: str, link: str | None) -> str:
    """Return a stable RSS identity without a generated numeric fragment.

    The rule is intentionally narrow and limited to the measured BBC failure.
    A fragment is removed only from an absolute HTTP(S) BBC GUID whose host and
    path match the article link, whose GUID has no query, and whose link has no
    fragment or identity-bearing query. Non-numeric anchors, non-URL GUIDs, and
    publisher links that expose an anchor are preserved.
    """
    if not guid or not link:
        return guid

    try:
        guid_parts = urlsplit(guid)
        link_parts = urlsplit(link)
    except ValueError:
        return guid
    guid_host = guid_parts.hostname.lower() if guid_parts.hostname else ""
    link_query_keys = {key for key, _value in parse_qsl(link_parts.query, keep_blank_values=True)}
    if (
        guid_parts.scheme.lower() not in {"http", "https"}
        or link_parts.scheme.lower() not in {"http", "https"}
        or not (guid_host in _BBC_HOSTS or guid_host.endswith(_BBC_HOST_SUFFIXES))
        or not guid_parts.fragment.isdecimal()
        or guid_parts.query
        or link_parts.fragment
        or not link_query_keys.issubset(_TRACKING_QUERY_KEYS)
        or guid_parts.scheme.lower() != link_parts.scheme.lower()
        or guid_parts.netloc.lower() != link_parts.netloc.lower()
        or guid_parts.path != link_parts.path
    ):
        return guid

    return urlunsplit(
        (
            guid_parts.scheme,
            guid_parts.netloc,
            guid_parts.path,
            guid_parts.query,
            "",
        )
    )


@dataclass(frozen=True)
class RssReconciliationResult:
    """Counts returned by one retained-row reconciliation pass."""

    candidate_rows: int = 0
    canonicalized_rows: int = 0
    duplicate_groups: int = 0
    deleted_rows: int = 0
    deleted_story_memberships: int = 0
    deleted_stories: int = 0


def _survivor_key(row: EventRow) -> tuple[object, object, int]:
    """Newest known representation wins, with a stable final tie-break."""
    return (row.fetched_at, row.occurred_at, row.id)


_STORY_DERIVED_MODELS = (
    StorySensorCheckRow,
    StoryCorroborationRow,
    StoryDisagreementRow,
    StoryClaimRow,
    StoryReviewRow,
    StoryEmbeddingRow,
    StoryGistRow,
)


def _as_utc(value: datetime) -> datetime:
    """Normalise SQLite's naive datetime round-trip to production UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _refresh_story(
    session: Session,
    story_id: int,
    owners: dict[str, str],
    *,
    now: datetime,
) -> bool:
    """Refresh one story after duplicate memberships are removed.

    Returns ``True`` when the story became empty and was deleted.  Derived rows
    are removed with an empty story because the schema intentionally has no
    foreign-key cascades.
    """
    # Different RSS identities can belong to one story. Lock the aggregate row
    # before reading members so a waiter recomputes from the first writer's
    # committed event state instead of persisting a stale snapshot afterwards.
    story = session.execute(
        select(StoryRow)
        .where(StoryRow.id == story_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    memberships = list(
        session.execute(select(StoryMemberRow).where(StoryMemberRow.story_id == story_id)).scalars()
    )
    if not memberships:
        for model in _STORY_DERIVED_MODELS:
            session.execute(delete(model).where(model.story_id == story_id))
        if story is not None:
            session.delete(story)
        return story is not None
    if story is None:
        return False

    event_rows = session.execute(
        select(EventRow)
        .join(StoryMemberRow, StoryMemberRow.event_id == EventRow.id)
        .where(StoryMemberRow.story_id == story_id)
        .execution_options(populate_existing=True)
    ).scalars()
    events = list(event_rows)
    story.member_count = len(memberships)
    if not events:
        return False

    # Retention deliberately leaves historical memberships after their event
    # rows expire. A partial join cannot reconstruct lifetime outlet/owner
    # counts or the real first/last timestamps, so preserve only those
    # aggregates. The newest retained headline and recent derivations remain
    # recoverable and must still refresh.
    if len(events) == len(memberships):
        sources = [event.source for event in events]
        story.outlet_count = len(set(sources))
        story.owner_count = owner_count(sources, owners)
        story.first_seen = min(event.occurred_at for event in events)
        story.last_seen = max(event.occurred_at for event in events)
    else:
        latest_retained = max(events, key=lambda event: _as_utc(event.occurred_at))
        if _as_utc(latest_retained.occurred_at) > _as_utc(story.last_seen):
            story.last_seen = latest_retained.occurred_at
    newest = max(events, key=lambda event: (event.occurred_at, event.id))
    newest_title = (newest.payload or {}).get("title")
    if newest_title:
        story.title = newest_title

    # Every downstream row was derived from the old membership set. Most of
    # these workers are insert-if-absent, so recent rows must be invalidated for
    # their normal scheduled rebuild. Historical stories sit outside every
    # producer's rolling window; deleting those derivations would be permanent,
    # so keep their existing evidence snapshot instead.
    if _as_utc(story.last_seen) >= _as_utc(now) - timedelta(hours=WINDOW_HOURS):
        for model in _STORY_DERIVED_MODELS:
            session.execute(delete(model).where(model.story_id == story_id))
    return False


def _reconcile_story_memberships(
    session: Session,
    group: list[EventRow],
    survivor: EventRow,
    owners: dict[str, str],
    *,
    now: datetime,
) -> tuple[int, int]:
    """Keep one assignment for the survivor and repair affected stories."""
    event_by_id = {row.id: row for row in group}
    memberships = list(
        session.execute(
            select(StoryMemberRow).where(StoryMemberRow.event_id.in_(event_by_id))
        ).scalars()
    )
    if not memberships:
        return (0, 0)

    survivor_membership = next(
        (membership for membership in memberships if membership.event_id == survivor.id),
        None,
    )
    kept = survivor_membership or max(
        memberships,
        key=lambda membership: (
            _survivor_key(event_by_id[membership.event_id]),
            membership.similarity,
            -membership.story_id,
        ),
    )
    affected_story_ids = {membership.story_id for membership in memberships}
    removed = 0
    for membership in memberships:
        if membership is kept:
            continue
        session.delete(membership)
        removed += 1
    session.flush()
    if kept.event_id != survivor.id:
        kept.event_id = survivor.id
        session.flush()

    deleted_stories = sum(
        _refresh_story(session, story_id, owners, now=now)
        for story_id in sorted(affected_story_ids)
    )
    session.flush()
    return (removed, deleted_stories)


def changed_assigned_rss_story_ids(
    session: Session,
    rows: list[dict[str, Any]],
) -> set[int]:
    """Find assigned RSS stories whose canonical event content will change.

    Fetch timestamps and raw GUID fragments are transport metadata. Only a
    changed publication time, headline, or summary changes the story model and
    its derived evidence.
    """
    incoming = {
        (row["source"], row["source_event_id"]): row
        for row in rows
        if str(row.get("source") or "").startswith("rss-")
        and row.get("source_event_id") is not None
    }
    if not incoming:
        return set()

    existing: list[EventRow] = []
    ids_by_source: dict[str, list[str]] = defaultdict(list)
    for source, event_id in incoming:
        ids_by_source[source].append(event_id)
    # Stay below SQLite's expression-depth and legacy parameter limits, and
    # preserve the batching guarantee that protects PostgreSQL imports.
    lookup_batch_size = 400
    for source, event_ids in ids_by_source.items():
        for start in range(0, len(event_ids), lookup_batch_size):
            existing.extend(
                session.execute(
                    select(EventRow).where(
                        EventRow.source == source,
                        EventRow.source_event_id.in_(event_ids[start : start + lookup_batch_size]),
                    )
                ).scalars()
            )
    changed_event_ids: list[int] = []
    for event in existing:
        candidate = incoming[(event.source, event.source_event_id)]
        if (
            _as_utc(candidate.get("fetched_at", event.fetched_at)),
            _as_utc(candidate["occurred_at"]),
        ) < (_as_utc(event.fetched_at), _as_utc(event.occurred_at)):
            # The conflict UPDATE rejects this delayed representation too, so
            # it must not invalidate or refresh the assigned story.
            continue
        old_payload = event.payload or {}
        new_payload = candidate.get("payload") or {}
        publisher_time_changed = new_payload.get("published_from_feed") is True and (
            _as_utc(event.occurred_at) != _as_utc(candidate["occurred_at"])
        )
        if publisher_time_changed or any(
            old_payload.get(key) != new_payload.get(key) for key in ("title", "summary")
        ):
            changed_event_ids.append(event.id)
    if not changed_event_ids:
        return set()
    story_ids: set[int] = set()
    for start in range(0, len(changed_event_ids), lookup_batch_size):
        story_ids.update(
            session.execute(
                select(StoryMemberRow.story_id).where(
                    StoryMemberRow.event_id.in_(
                        changed_event_ids[start : start + lookup_batch_size]
                    )
                )
            ).scalars()
        )
    return story_ids


def lock_rss_identity_keys(
    session: Session,
    keys: set[tuple[str, str]],
) -> None:
    """Serialize RSS upserts and retained-row reconciliation.

    One coarse transaction lock covers absent keys without growing with import
    size. RSS feeds are staggered and small in normal operation; serializing
    their short write transactions is the safe tradeoff. SQLite tests are
    single-process and need no equivalent.
    """
    if not keys or session.get_bind().dialect.name != "postgresql":
        return
    _lock_rss_reconciliation(session)


def _lock_rss_reconciliation(session: Session) -> None:
    """Exclude canonical RSS writers before retained candidates are read."""
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended('osint:rss-identity-reconciliation', 0))"
        )
    )


def refresh_assigned_rss_stories(
    session: Session,
    story_ids: set[int],
    *,
    now: datetime | None = None,
) -> int:
    """Refresh assigned stories after canonical RSS content changes."""
    if not story_ids:
        return 0
    now = now or datetime.now(UTC)
    owners = content_owner_map()
    for story_id in sorted(story_ids):
        _refresh_story(session, story_id, owners, now=now)
    session.flush()
    return len(story_ids)


def reconcile_rss_fragment_duplicates(
    session: Session,
    *,
    now: datetime | None = None,
) -> RssReconciliationResult:
    """Canonicalize retained generated-fragment rows and delete duplicates.

    Rows already canonicalized by an earlier pass remain candidates through
    their raw ``payload.guid``.  This lets a later legacy row join the existing
    canonical row instead of colliding with it.  A row whose stored identity is
    neither the raw nor canonical GUID is left untouched.

    The caller owns the transaction.  Re-running the function is idempotent.
    """
    now = now or datetime.now(UTC)
    _lock_rss_reconciliation(session)
    raw_guid = EventRow.payload["guid"].as_string()
    fragment_rows = list(
        session.execute(
            select(EventRow).where(
                EventRow.source.like("rss-%"),
                or_(EventRow.source_event_id.like("%#%"), raw_guid.like("%#%")),
            )
        ).scalars()
    )

    groups: dict[tuple[str, str], list[EventRow]] = defaultdict(list)
    for row in fragment_rows:
        payload = row.payload or {}
        guid = payload.get("guid")
        link = payload.get("source_url")
        if not isinstance(guid, str) or not isinstance(link, str):
            continue
        canonical_id = canonical_rss_event_id(guid, link)
        if canonical_id == guid:
            continue
        if row.source_event_id not in {guid, canonical_id}:
            continue
        groups[(row.source, canonical_id)].append(row)

    # An older/newer worker may already have written the unsuffixed canonical
    # key with an unsuffixed payload GUID. Include that occupant before ranking
    # or renaming a fragment row would violate events_source_id_idx.
    for source, canonical_id in sorted(groups):
        group = groups[(source, canonical_id)]
        if any(row.source_event_id == canonical_id for row in group):
            continue
        canonical_row = session.execute(
            select(EventRow).where(
                EventRow.source == source,
                EventRow.source_event_id == canonical_id,
            )
        ).scalar_one_or_none()
        if canonical_row is not None:
            group.append(canonical_row)

    candidate_rows = sum(len(group) for group in groups.values())
    canonicalized_rows = 0
    duplicate_groups = 0
    deleted_rows = 0
    deleted_story_memberships = 0
    deleted_stories = 0
    owners = content_owner_map()

    for (_source, canonical_id), group in sorted(groups.items()):
        survivor = max(group, key=_survivor_key)
        losers = [row for row in group if row.id != survivor.id]
        if losers:
            duplicate_groups += 1
            removed_memberships, removed_stories = _reconcile_story_memberships(
                session, group, survivor, owners, now=now
            )
            deleted_story_memberships += removed_memberships
            deleted_stories += removed_stories
            loser_ids = [row.id for row in losers]
            result = session.execute(delete(EventRow).where(EventRow.id.in_(loser_ids)))
            deleted_rows += int(getattr(result, "rowcount", 0) or 0)
            session.flush()
        if survivor.source_event_id != canonical_id:
            survivor.source_event_id = canonical_id
            canonicalized_rows += 1

    session.flush()
    return RssReconciliationResult(
        candidate_rows=candidate_rows,
        canonicalized_rows=canonicalized_rows,
        duplicate_groups=duplicate_groups,
        deleted_rows=deleted_rows,
        deleted_story_memberships=deleted_story_memberships,
        deleted_stories=deleted_stories,
    )
