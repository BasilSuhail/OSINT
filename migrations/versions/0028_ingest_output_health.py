"""Persist source output states and row movement (#848).

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COUNT_COLUMNS: tuple[str, ...] = (
    "new_data_n",
    "unchanged_n",
    "empty_n",
    "misconfigured_n",
    "fetched_rows",
    "accepted_rows",
    "inserted_rows",
    "rejected_rows",
    "last_fetched",
    "last_accepted",
    "last_inserted",
    "last_rejected",
)


def upgrade() -> None:
    for name in _COUNT_COLUMNS:
        op.add_column(
            "ingest_health",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )
    op.add_column("ingest_health", sa.Column("last_state", sa.Text(), nullable=True))
    op.add_column(
        "ingest_health", sa.Column("last_checked", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "ingest_health", sa.Column("last_output", sa.DateTime(timezone=True), nullable=True)
    )
    # Existing healthy rows predate output accounting. Seed their clocks from
    # the strongest evidence available so deployment does not page every source
    # before its next scheduled run. Rows can contain both timestamps; the
    # newer one is the current state, not merely the first non-null value.
    op.execute(
        "UPDATE ingest_health SET last_checked = CASE "
        "WHEN last_success IS NULL THEN last_failure "
        "WHEN last_failure IS NULL THEN last_success "
        "ELSE GREATEST(last_success, last_failure) END, "
        "last_output = last_success, "
        "last_state = CASE "
        "WHEN last_failure IS NOT NULL "
        "AND (last_success IS NULL OR last_failure > last_success) THEN 'failed' "
        "WHEN last_success IS NOT NULL THEN 'unchanged' ELSE NULL END"
    )
    op.create_check_constraint(
        "ingest_health_state_allowed",
        "ingest_health",
        "last_state IS NULL OR last_state IN "
        "('new_data', 'unchanged', 'empty', 'misconfigured', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint("ingest_health_state_allowed", "ingest_health", type_="check")
    for name in ("last_output", "last_checked", "last_state"):
        op.drop_column("ingest_health", name)
    for name in reversed(_COUNT_COLUMNS):
        op.drop_column("ingest_health", name)
