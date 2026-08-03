"""Collapse generated RSS GUID fragment duplicates (#751).

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-02

The repair is deliberately narrower than removing every URL fragment.  It
uses the same identity rule as live ingestion and keeps the newest fetched
representation, then the newest publication, then the highest row ID.
Story memberships and aggregates follow the surviving event.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import context, op
from sqlalchemy.orm import Session

from app.sources.rss_identity import reconcile_rss_fragment_duplicates

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode():
        # This revision changes data, not schema. Offline Alembic has no live
        # rows to reconcile, so emit an executable marker and let the first
        # housekeeping pass run the same idempotent repair after startup.
        op.execute(
            "SELECT 1 /* #751 RSS fragment repair deferred to housekeeping */"
        )
        return

    # A savepoint lets the tested runtime reconciler share Alembic's outer
    # transaction without committing the migration independently.
    with Session(
        bind=op.get_bind(),
        future=True,
        join_transaction_mode="create_savepoint",
    ) as session:
        reconcile_rss_fragment_duplicates(session)
        session.commit()


def downgrade() -> None:
    # Deleted duplicate event representations cannot be reconstructed.
    pass
