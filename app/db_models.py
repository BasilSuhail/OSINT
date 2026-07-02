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

    __table_args__ = (Index("stories_last_seen_idx", "last_seen"),)


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
