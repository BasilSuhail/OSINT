"""Withdraw generic place-name resolutions (#755).

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the migration independent of the current EventRow mapper. Later
    # mapper columns do not exist yet when a database upgrades through 0025.
    # The scheduled place worker runs the same idempotent repair before every
    # bounded scan, so both online and offline upgrades safely defer it there.
    op.execute("SELECT 1 /* #755 generic place repair deferred to place worker */")


def downgrade() -> None:
    # Removed false resolutions cannot be truthfully reconstructed.
    pass
