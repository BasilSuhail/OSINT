"""Persist the source-data audit's findings over time (#669).

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-29

#580 built the only check that asks whether the data means what it claims —
eight rules over 47 declared source expectations. It ran once, found 50
findings, and nothing since knows whether that is still the number.

One run row plus one row per finding, nightly. No retention: raw events expire
at 30 days, derived analytical tables do not, and pruning this would recreate
#586 — the retention window eating the history the trend needs. ~50 findings a
day is ~18k rows a year.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sources_measured", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings_total", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("audit_runs_started_idx", "audit_runs", ["started_at"])

    op.create_table(
        "audit_findings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("check_name", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["audit_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("audit_findings_run_idx", "audit_findings", ["run_id", "source"])


def downgrade() -> None:
    op.drop_index("audit_findings_run_idx", table_name="audit_findings")
    op.drop_table("audit_findings")
    op.drop_index("audit_runs_started_idx", table_name="audit_runs")
    op.drop_table("audit_runs")
