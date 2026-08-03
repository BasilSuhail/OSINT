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

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep historical migrations independent of the current EventRow mapper:
    # later mapper columns do not exist while a database upgrades through 0024.
    # Housekeeping runs this same idempotent repair after startup.
    op.execute("SELECT 1 /* #751 RSS fragment repair deferred to housekeeping */")


def downgrade() -> None:
    # Deleted duplicate event representations cannot be reconstructed.
    pass
