"""Story sensor checks — claim-vs-sensor verdicts per story (WS-C step 3, #361).

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-09

One row per (story, claim type, method version). Overwrite-in-place on
re-check, except 'confirmed' never downgrades — hazard retention deletes the
sensor evidence within days, the verdict and its evidence snapshot persist.
No backfill: sensor rows for stories older than the retention window are gone,
so historical stories simply have no checks (absence = not checked, honest).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_sensor_checks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("story_id", sa.BigInteger, nullable=False),
        sa.Column("claim_type", sa.Text, nullable=False),
        sa.Column("verdict", sa.Text, nullable=False),
        sa.Column("matched_event_id", sa.BigInteger, nullable=True),
        sa.Column("evidence", JSONB, nullable=True),
        sa.Column("method_version", sa.Text, nullable=False),
        sa.Column(
            "checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "story_id", "claim_type", "method_version", name="story_sensor_checks_unique"
        ),
    )
    op.create_index("story_sensor_checks_story_idx", "story_sensor_checks", ["story_id"])


def downgrade() -> None:
    op.drop_index("story_sensor_checks_story_idx", table_name="story_sensor_checks")
    op.drop_table("story_sensor_checks")
