"""Database persistence for canonical events.

Single entry point: `upsert_events()`. Idempotent on the
`(source, source_event_id)` UNIQUE index so retrying a fetch never produces
duplicate rows. See `docs/architecture/03-ingestion.md` for the contract.

Batching: Postgres limits a single statement to 65 535 bound parameters
(libpq protocol). The Event row has 12 columns, so the safe ceiling per
INSERT is ⌊65535 / 12⌋ = 5 461 rows. We batch at 1 000 to keep memory and
parse cost low and to leave headroom if the row shape grows.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import and_, case, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import EventRow
from app.events_bus import publish_new_events
from app.models import Event

#: Rows per upsert statement. 12 cols x 1000 = 12 000 bound params — well under
#: Postgres' 65 535 cap, generous headroom if columns are added later.
DEFAULT_BATCH_SIZE = 1000


@dataclass(frozen=True)
class UpsertReport:
    """Portable row movement for one persistence call.

    ``affected`` preserves the historical return contract: inserts plus
    refreshes. ``inserted`` is deliberately narrower and is what ingest health
    uses to distinguish new data from an unchanged snapshot.
    """

    accepted: int = 0
    affected: int = 0
    inserted: int = 0


def _event_to_row(event: Event) -> dict[str, Any]:
    """Convert a Pydantic `Event` to a row dict suitable for bulk insert."""
    return {
        "source": event.source,
        "source_event_id": event.source_event_id,
        "occurred_at": event.occurred_at,
        "fetched_at": event.fetched_at,
        "category": event.category.value,
        "severity": event.severity,
        "confidence": event.confidence,
        "keywords": list(event.keywords),
        "country": event.country,
        "lat": event.lat,
        "lon": event.lon,
        "payload": event.payload,
    }


#: Columns refreshed when an event is re-reported. Snapshot feeds (GDACS
#: geteventlist, EONET open events) re-publish the SAME `(source, source_event_id)`
#: every fetch while a hazard is active; without refreshing these, an ongoing
#: wildfire / flood / cyclone would freeze at its first-seen state and eventually
#: fall out of the dashboard's live window. Identity columns (source,
#: source_event_id, category) are never updated. `payload` is handled separately
#: — see `_payload_refresh()`.
_REFRESH_COLS: Final = (
    "occurred_at",
    "fetched_at",
    "severity",
    "confidence",
    "keywords",
)

#: Geography columns have source-specific ownership. RSS rows replace them
#: because the news resolver has already produced an authoritative verdict.
#: Other feeds may acquire geography after ingestion, so their nulls preserve
#: that enrichment (#618). A supplied position always wins.
_GEO_COLS: Final = ("country", "lat", "lon")


def _geo_refresh(excluded: Any, col: str) -> Any:
    """Refresh one geography column under the source's ownership rule.

    RSS rows run the news resolver before persistence, so a null is an
    authoritative withdrawal: the latest text no longer supports the old
    country or point. Other sources can acquire geography after ingestion;
    for them an upstream null still means "not supplied" and must preserve the
    enriched value (#618).
    """
    return case(
        (excluded.source.like("rss-%"), excluded[col]),
        else_=func.coalesce(excluded[col], getattr(EventRow, col)),
    )


#: Payload keys written AFTER ingestion — by the enrichment tasks and the
#: backfill scripts, not by the fetcher that produced the event. A refresh must
#: never destroy them: the fetcher does not know they exist and will not send
#: them again, so anything lost here is lost until the enrichment happens to run
#: on that row a second time. That is exactly how #604 hid for weeks — GDACS
#: re-published every active hazard on a 15-minute cadence and each refresh
#: deleted the real footprint geometry the map needed.
#:
#: Add the key here when you add an enricher. `test_persistence.py` walks this
#: list, so a refresh that starts clobbering enrichment fails the suite instead
#: of quietly emptying the map.
ENRICHMENT_PAYLOAD_KEYS: Final = (
    "footprint_geojson",  # real hazard geometry (app/enrichment/footprint.py, #205)
    "footprint_checked_at",  # cooldown stamp for footprints with no upstream geometry (#604)
    "footprint_source_key",  # upstream document the stored geometry came from (#880)
    "city",  # scripts/backfill_news_cities.py
    "news_scope",  # scripts/backfill_news_scope.py
    "sentiment",  # scripts/backfill_news_sentiment.py
    "sentiment_label",
    "entities",  # scripts/backfill_news_ner.py
    "enrichment_meta",  # which enricher/model wrote the above
    "geo_precision",  # exactness of the coordinate, including named places (#745)
    "geo_source",  # authority that supplied the coordinate (#745)
    "place_name",  # verified physical location label (#745)
    "place_wikidata_id",  # auditable external identity (#745)
    "place_description",
    "place_checked_at",
    "place_model",
    "place_resolution",
    "place_locations",  # every independently verified point for one story (#748)
    "place_candidate_count",
    "place_verified_count",
    "place_rejections",  # deterministic refusal evidence for generic names (#755)
    "place_rejected_count",
)


def _payload_refresh(excluded: Any, dialect: str) -> Any:
    """Merge the incoming payload over the stored one instead of replacing it.

    Everything we add ourselves after ingestion lives in `payload`: footprint
    geometry, sentiment, NER, geo enrichment. Replacing the column on refresh
    wiped all of it every time a snapshot feed re-published an active event —
    GDACS does that every 15 minutes, which is why long-running hazards
    (droughts above all) never kept their real polygon and fell back to the
    synthesized circle on the map (#604). A shallow merge keeps the enrichment
    and still lets upstream win on any key it actually sends.
    """
    if dialect == "postgresql":
        return EventRow.payload.op("||")(excluded.payload)
    return func.json_patch(EventRow.payload, excluded.payload)


def _rss_grade_is_current(excluded: Any) -> Any:
    """Whether a stored post-ingest RSS grade still describes this headline."""
    stored_method = EventRow.payload["severity_method"].as_string()
    stored_title = func.coalesce(EventRow.payload["title"].as_string(), "")
    incoming_title = func.coalesce(excluded.payload["title"].as_string(), "")
    return and_(
        excluded.source.like("rss-%"),
        stored_method.like("news-llm-%"),
        stored_title == incoming_title,
    )


def _rss_grade_payload(excluded: Any, dialect: str) -> Any:
    """Refresh upstream fields while keeping a current post-ingest RSS grade."""
    merged = _payload_refresh(excluded, dialect)
    grade_values = {
        key: EventRow.payload[key].as_string()
        for key in ("severity_method", "severity_band", "severity_rationale")
    }
    if dialect == "postgresql":
        grade_patch = func.jsonb_build_object(
            *[item for pair in grade_values.items() for item in pair]
        )
        preserved = merged.op("||")(grade_patch)
    else:
        grade_patch = func.json_object(*[item for pair in grade_values.items() for item in pair])
        preserved = func.json_patch(merged, grade_patch)
    return case((_rss_grade_is_current(excluded), preserved), else_=merged)


def _dedup_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse duplicate `(source, source_event_id)` within one batch, keeping
    the last occurrence — ON CONFLICT DO UPDATE cannot touch the same key twice
    in a single statement. Rows with a null id never conflict, so they pass
    through untouched.
    """
    keyed: dict[tuple[str, str], dict[str, Any]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in rows:
        sid = row["source_event_id"]
        if sid is None:
            passthrough.append(row)
        else:
            key = (row["source"], sid)
            existing = keyed.get(key)
            if (
                existing is None
                or not str(row["source"]).startswith("rss-")
                or (row["fetched_at"], row["occurred_at"])
                >= (existing["fetched_at"], existing["occurred_at"])
            ):
                keyed[key] = row
    return passthrough + list(keyed.values())


def _sqlite_existing_keys(rows: list[dict[str, Any]], session: Session) -> set[tuple[str, str]]:
    """Identity keys present before a SQLite batch.

    Production Postgres reports insert-vs-update directly from ``RETURNING``.
    SQLite has no equivalent, so the hermetic test dialect takes a bounded
    pre-image. Queries are split to stay below conservative bind limits.
    """
    grouped: dict[str, list[str]] = {}
    for row in rows:
        source = str(row["source"])
        source_id = row["source_event_id"]
        if source_id is not None:
            grouped.setdefault(source, []).append(str(source_id))

    existing: set[tuple[str, str]] = set()
    for source, source_ids in grouped.items():
        for start in range(0, len(source_ids), 400):
            chunk = source_ids[start : start + 400]
            existing.update(
                (str(found_source), str(found_id))
                for found_source, found_id in session.execute(
                    select(EventRow.source, EventRow.source_event_id).where(
                        EventRow.source == source,
                        EventRow.source_event_id.in_(chunk),
                    )
                ).all()
            )
    return existing


def _upsert_batch(rows: list[dict[str, Any]], session: Session, dialect: str) -> UpsertReport:
    """Run a batch and report inserts separately from refreshed rows."""
    rows = _dedup_rows(rows)
    existing = _sqlite_existing_keys(rows, session) if dialect == "sqlite" else set()
    if dialect == "postgresql":
        base = pg_insert(EventRow).values(rows)
    elif dialect == "sqlite":
        base = sqlite_insert(EventRow).values(rows)
    else:
        raise NotImplementedError(
            f"upsert_events does not support dialect {dialect!r}; add a branch above"
        )

    refreshed: dict[str, Any] = {col: base.excluded[col] for col in _REFRESH_COLS}
    has_rss = any(str(row["source"]).startswith("rss-") for row in rows)
    if has_rss:
        refreshed["severity"] = case(
            (_rss_grade_is_current(base.excluded), EventRow.severity),
            else_=base.excluded.severity,
        )
    # PostgreSQL now() is fixed at transaction start. clock_timestamp() marks
    # the actual upsert statement, preventing a long transaction from publishing
    # a revision older than work that committed while it was running.
    refreshed["updated_at"] = func.clock_timestamp() if dialect == "postgresql" else func.now()
    refreshed.update({col: _geo_refresh(base.excluded, col) for col in _GEO_COLS})
    refreshed["payload"] = (
        _rss_grade_payload(base.excluded, dialect)
        if has_rss
        else _payload_refresh(base.excluded, dialect)
    )
    stmt = base.on_conflict_do_update(
        index_elements=["source", "source_event_id"],
        set_=refreshed,
        # Canonical RSS fragments can arrive in separate, out-of-order fetch
        # transactions.  A delayed response must not replace a representation
        # already fetched later.  Snapshot sources keep their existing refresh
        # semantics; equal RSS timestamps still allow deterministic replays.
        where=or_(
            base.excluded.source.not_like("rss-%"),
            base.excluded.fetched_at > EventRow.fetched_at,
            and_(
                base.excluded.fetched_at == EventRow.fetched_at,
                base.excluded.occurred_at >= EventRow.occurred_at,
            ),
        ),
    )

    # RETURNING yields every affected row (inserted + updated). Both Postgres and
    # SQLite ≥ 3.35 support it, avoiding the `rowcount = -1` quirk some drivers
    # exhibit on multi-row ON CONFLICT statements.
    if dialect == "postgresql":
        # xmax is zero for a tuple inserted by this statement and nonzero for a
        # tuple produced by ON CONFLICT DO UPDATE. It is read, never stored.
        returned = session.execute(
            stmt.returning(EventRow.id, literal_column("xmax = 0").label("inserted"))
        ).all()
        inserted = sum(1 for row in returned if bool(row.inserted))
    else:
        returned = session.execute(stmt.returning(EventRow.id)).all()
        inserted = sum(
            1
            for row in rows
            if row["source_event_id"] is not None
            and (str(row["source"]), str(row["source_event_id"])) not in existing
        )
    return UpsertReport(accepted=len(rows), affected=len(returned), inserted=inserted)


def upsert_events_report(
    events: list[Event],
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> UpsertReport:
    """Upsert events keyed on `(source, source_event_id)`.

    New rows are inserted; a row whose key already exists is REFRESHED (its
    occurred_at / fetched_at / severity / geo / payload updated from the latest
    fetch) so snapshot feeds like GDACS and EONET keep their ongoing hazards
    current instead of freezing at first-seen. Splits the input into chunks of
    ``batch_size`` and returns accepted, affected and genuinely inserted counts.
    """
    if not events:
        return UpsertReport()
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    # New network lookups only happen in the bounded enrichment worker. This
    # cache-only pass makes an unchanged RSS refresh reproduce the exact point;
    # changed text has a different key and withdraws the stale point (#741).
    from app.enrichment.place import apply_cached_places

    events = apply_cached_places(events, session)
    # Deduplicate before splitting into SQL batches. Canonical RSS variants may
    # otherwise land on opposite sides of a batch boundary and let the later
    # statement overwrite the newest representation selected above.
    rows = _dedup_rows([_event_to_row(e) for e in events])
    dialect = session.get_bind().dialect.name

    # Canonical RSS identities mean a publisher's later fragment variant now
    # refreshes one existing event. Capture assigned stories before the upsert,
    # then refresh their aggregates and rebuildable derivations afterwards.
    from app.sources.rss_identity import (
        changed_assigned_rss_story_ids,
        lock_rss_identity_keys,
        refresh_assigned_rss_stories,
    )

    lock_rss_identity_keys(
        session,
        {
            (str(row["source"]), str(row["source_event_id"]))
            for row in rows
            if str(row["source"]).startswith("rss-") and row["source_event_id"] is not None
        },
    )
    changed_story_ids = changed_assigned_rss_story_ids(session, rows)

    report = UpsertReport()
    for start in range(0, len(rows), batch_size):
        batch = _upsert_batch(rows[start : start + batch_size], session, dialect)
        report = UpsertReport(
            accepted=report.accepted + batch.accepted,
            affected=report.affected + batch.affected,
            inserted=report.inserted + batch.inserted,
        )
    refresh_assigned_rss_stories(session, changed_story_ids)
    # A dead Redis must never fail an ingest; the SSE clients fall back to
    # their 30s SWR poll. Swallow and continue.
    with contextlib.suppress(Exception):
        publish_new_events(report.affected)
    return report


def upsert_events(
    events: list[Event],
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Compatibility entry point returning inserts plus refreshes.

    Callers which need to distinguish new rows use ``upsert_events_report``;
    backfills retain the original integer contract.
    """
    return upsert_events_report(events, session, batch_size=batch_size).affected
