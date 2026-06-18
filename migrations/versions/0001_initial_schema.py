"""Initial schema — events, scores, labels, supporting tables.

Revision ID: 0001
Revises:
Create Date: 2026-06-18

Matches `docs/architecture/04-schema.md`.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("source_event_id", sa.Text, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("severity", sa.Float),
        sa.Column("confidence", sa.Float),
        sa.Column(
            "keywords",
            postgresql.ARRAY(sa.String),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("country", sa.String(2)),
        sa.Column("lat", sa.Float),
        sa.Column("lon", sa.Float),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.CheckConstraint(
            "severity IS NULL OR (severity BETWEEN 0 AND 1)", name="events_severity_range"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence BETWEEN 0 AND 1)",
            name="events_confidence_range",
        ),
    )
    op.create_index(
        "events_source_id_idx", "events", ["source", "source_event_id"], unique=True
    )
    op.create_index("events_occurred_at_idx", "events", ["occurred_at"])
    op.create_index("events_country_occurred_idx", "events", ["country", "occurred_at"])
    op.create_index("events_category_idx", "events", ["category", "occurred_at"])
    op.create_index("events_source_occurred_idx", "events", ["source", "occurred_at"])

    op.create_table(
        "scores",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_length", sa.Interval, nullable=False),
        sa.Column("score_name", sa.Text, nullable=False),
        sa.Column("score_value", sa.Float, nullable=False),
        sa.Column("components", postgresql.JSONB, nullable=False),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("score_value BETWEEN 0 AND 1", name="scores_value_range"),
        sa.UniqueConstraint(
            "country",
            "bucket_start",
            "bucket_length",
            "score_name",
            "method_version",
            name="scores_unique_idx",
        ),
    )

    op.create_table(
        "labels",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_length", sa.Interval, nullable=False),
        sa.Column("label_code", sa.Text, nullable=False),
        sa.Column("label_source", sa.Text, nullable=False),
        sa.Column("source_record_id", sa.Text),
        sa.Column("magnitude", sa.Float),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "locked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("labels_country_bucket_idx", "labels", ["country", "bucket_start"])

    op.create_table(
        "ingest_health",
        sa.Column("source", sa.Text, primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("success_n", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failure_n", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_success", sa.DateTime(timezone=True)),
        sa.Column("last_failure", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "ingest_failures",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("error_class", sa.Text, nullable=False),
        sa.Column("error_message", sa.Text),
        sa.Column("request_url", sa.Text),
        sa.Column("response_body", sa.Text),
        sa.Column("payload", postgresql.JSONB),
    )

    op.create_table(
        "dead_letter_queue",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("task_name", sa.Text, nullable=False),
        sa.Column("fetcher_name", sa.Text, nullable=False),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("replay_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
    )

    op.create_table(
        "housekeeping_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "ran_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("job_name", sa.Text, nullable=False),
        sa.Column("archived_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("deleted_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("notes", sa.Text),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("country", sa.String(2)),
        sa.Column("score_value", sa.Float),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("dedup_key", sa.Text, nullable=False, unique=True),
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("housekeeping_runs")
    op.drop_table("dead_letter_queue")
    op.drop_table("ingest_failures")
    op.drop_table("ingest_health")
    op.drop_index("labels_country_bucket_idx", table_name="labels")
    op.drop_table("labels")
    op.drop_table("scores")
    op.drop_index("events_source_occurred_idx", table_name="events")
    op.drop_index("events_category_idx", table_name="events")
    op.drop_index("events_country_occurred_idx", table_name="events")
    op.drop_index("events_occurred_at_idx", table_name="events")
    op.drop_index("events_source_id_idx", table_name="events")
    op.drop_table("events")
