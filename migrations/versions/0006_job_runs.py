"""Job runs — heartbeat rows behind the top-bar activity monitor (#341).

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-08

One row per execution of a long-running job (backfills, exports, analytical
beat bodies). status stays 'running' with a stale heartbeat when a job
crashes — readers surface that as 'stalled'.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("job", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", sa.Text, nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
    )
    op.create_index("job_runs_started_idx", "job_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("job_runs_started_idx", table_name="job_runs")
    op.drop_table("job_runs")
