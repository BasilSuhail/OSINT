"""SQLAlchemy ORM models matching `docs/architecture/04-schema.md`.

Postgres-native column types are used (JSONB, ARRAY, INTERVAL). Tests target a
real Postgres database via the dev docker-compose stack.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Interval,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Cross-dialect JSON: JSONB on Postgres, JSON elsewhere (used in tests).
JsonColumn = JSONB().with_variant(JSON(), "sqlite")
StringArray = ARRAY(String).with_variant(JSON(), "sqlite")

# SQLite only auto-increments columns typed exactly INTEGER PRIMARY KEY; a BIGINT
# primary key on SQLite stays NULL on insert which fails the NOT NULL constraint.
# Use BigInteger on Postgres (production) and Integer on SQLite (tests).
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    keywords: Mapped[list[str]] = mapped_column(StringArray, nullable=False, default=list)
    country: Mapped[str | None] = mapped_column(String(2))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "source_event_id", name="events_source_id_idx"),
        CheckConstraint(
            "severity IS NULL OR (severity BETWEEN 0 AND 1)", name="events_severity_range"
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence BETWEEN 0 AND 1)", name="events_confidence_range"
        ),
        Index("events_occurred_at_idx", "occurred_at"),
        Index("events_country_occurred_idx", "country", "occurred_at"),
        Index("events_category_idx", "category", "occurred_at"),
        Index("events_source_occurred_idx", "source", "occurred_at"),
    )


class ScoreRow(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_length: Mapped[timedelta] = mapped_column(Interval, nullable=False)
    score_name: Mapped[str] = mapped_column(Text, nullable=False)
    score_value: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "country",
            "bucket_start",
            "bucket_length",
            "score_name",
            "method_version",
            name="scores_unique_idx",
        ),
        CheckConstraint("score_value BETWEEN 0 AND 1", name="scores_value_range"),
    )


class LabelRow(Base):
    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_length: Mapped[timedelta] = mapped_column(Interval, nullable=False)
    label_code: Mapped[str] = mapped_column(Text, nullable=False)
    label_source: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(Text)
    magnitude: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("labels_country_bucket_idx", "country", "bucket_start"),
        UniqueConstraint(
            "country",
            "bucket_start",
            "label_code",
            "label_source",
            name="labels_country_bucket_code_source_key",
        ),
    )


class IngestHealthRow(Base):
    __tablename__ = "ingest_health"

    source: Mapped[str] = mapped_column(Text, primary_key=True)
    day: Mapped[Date] = mapped_column(Date, primary_key=True)
    success_n: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_n: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestFailureRow(Base):
    __tablename__ = "ingest_failures"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    error_class: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    request_url: Mapped[str | None] = mapped_column(Text)
    response_body: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn)


class DeadLetterRow(Base):
    __tablename__ = "dead_letter_queue"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(Text, nullable=False)
    fetcher_name: Mapped[str] = mapped_column(Text, nullable=False)
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    replay_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class HousekeepingRunRow(Base):
    __tablename__ = "housekeeping_runs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    archived_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class NotificationRow(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    score_value: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class PredictionRow(Base):
    """Forward prediction journal (WS-E). Rows are immutable once issued —
    only `outcome` and `graded_at` are ever updated, exactly once."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_months: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    outcome: Mapped[int | None] = mapped_column(Integer)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source",
            "method_version",
            "country",
            "bucket_start",
            "horizon_months",
            name="predictions_forecast_key",
        ),
        CheckConstraint("score BETWEEN 0 AND 1", name="predictions_score_range"),
        Index("predictions_ungraded_idx", "outcome", "bucket_start"),
    )


class StoryRow(Base):
    """WS-A story cluster — one row per real-world story (issue #296)."""

    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    outlet_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Distinct content owners (#355) — the WS-C independence input; ≤ outlet_count.
    owner_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (Index("stories_last_seen_idx", "last_seen"),)


class JobRunRow(Base):
    """One execution of a long-running job — the activity monitor's raw feed (#341).

    A crashed job leaves status='running' with a stale heartbeat; readers
    treat that as 'stalled' rather than trusting the status blindly.
    """

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    job: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("job_runs_started_idx", "started_at"),)


class StoryMemberRow(Base):
    """Membership link between a news event and its story. Append-only."""

    __tablename__ = "story_members"

    event_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True)
    story_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("story_members_story_idx", "story_id"),)


class StorySensorCheckRow(Base):
    """WS-C sensor cross-check verdict per (story, claim type) — issue #361.

    Overwrite-in-place per method version, except a 'confirmed' verdict is
    never downgraded: hazard retention deletes the sensor row within days,
    so the verdict keeps its evidence snapshot after the evidence is gone.
    """

    __tablename__ = "story_sensor_checks"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    claim_type: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    matched_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn, nullable=True)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "story_id", "claim_type", "method_version", name="story_sensor_checks_unique"
        ),
        Index("story_sensor_checks_story_idx", "story_id"),
    )


class StoryCorroborationRow(Base):
    """WS-C corroboration score per story — issue #363.

    One row per (story, method version), overwritten in place while the story
    is inside the clustering window. `components` is the evidence trail —
    the score is never shown without its inputs.
    """

    __tablename__ = "story_corroboration"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("story_id", "method_version", name="story_corroboration_unique"),
        Index("story_corroboration_story_idx", "story_id"),
        CheckConstraint("score >= 0 AND score < 1", name="story_corroboration_score_range"),
    )


class StoryDisagreementRow(Base):
    """WS-B per-story telling divergence — issue #370.

    One row per (story, method version), overwritten in place while the story
    is inside the clustering window. Stories with fewer than two known-origin
    country groups get no row. `components` carries the group sizes — the
    number is never shown without who is diverging.
    """

    __tablename__ = "story_disagreement"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    divergence: Mapped[float] = mapped_column(Float, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("story_id", "method_version", name="story_disagreement_unique"),
        Index("story_disagreement_story_idx", "story_id"),
        CheckConstraint("divergence >= 0 AND divergence <= 1", name="story_disagreement_range"),
    )


class DisagreementPairRow(Base):
    """WS-B (country-pair, month) divergence roll-up — issue #372.

    Rebuilt idempotently from persisted story_disagreement rows on every
    disagreement beat; months accumulate because story rows outlive the
    clustering window. country_a < country_b lexicographically.
    """

    __tablename__ = "disagreement_pairs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    country_a: Mapped[str] = mapped_column(String(2), nullable=False)
    country_b: Mapped[str] = mapped_column(String(2), nullable=False)
    month: Mapped[Date] = mapped_column(Date, nullable=False)
    n_stories: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_divergence: Mapped[float] = mapped_column(Float, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "country_a", "country_b", "month", "method_version", name="disagreement_pairs_unique"
        ),
        Index("disagreement_pairs_month_idx", "month"),
        CheckConstraint(
            "mean_divergence >= 0 AND mean_divergence <= 1", name="disagreement_pairs_range"
        ),
    )


class StoryClaimRow(Base):
    """WS-G model-extracted claims per story — issue #378.

    The model is another noisy annotator: rows carry model + prompt_version
    so every claim is attributable, and NOTHING downstream consumes them
    until agreement with a human-checked sample is measured and published.
    """

    __tablename__ = "story_claims"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    claims: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("story_id", "method_version", name="story_claims_unique"),
        Index("story_claims_story_idx", "story_id"),
    )


class StoryReviewRow(Base):
    """WS-G nightly story review — contradiction + cluster QA (issue #386).

    Same guardrails as story_claims: attributable (model + prompt version),
    consumed by nothing until its own agreement rate is published.
    """

    __tablename__ = "story_reviews"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    review: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("story_id", "method_version", name="story_reviews_unique"),
        Index("story_reviews_story_idx", "story_id"),
    )


class BrainNarrativeRow(Base):
    """One situation narrative produced by the brain (#409).

    Append-only, 30-day retention (housekeeping prunes it). `input_digest`
    lets a reader tell a genuinely new narrative from a mere re-render.
    """

    __tablename__ = "brain_narrative"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JsonColumn, nullable=False)
    input_digest: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("brain_narrative_created_idx", "created_at"),)


class StoryGistRow(Base):
    """A light per-story gist + tags from the 1.5b brain (#413).

    One row per (story, method version), idempotent like story_claims; 30-day
    retention. Timely first-look that complements the nightly 4b claim layer.
    """

    __tablename__ = "story_gist"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gist: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    escalating: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    method_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("story_id", "method_version", name="story_gist_unique"),
        Index("story_gist_created_idx", "created_at"),
    )
