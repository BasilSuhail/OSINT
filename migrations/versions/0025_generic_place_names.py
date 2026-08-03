"""Withdraw generic place-name resolutions (#755).

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import context, op
from sqlalchemy.orm import Session

from app.enrichment.place import repair_generic_place_names

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if context.is_offline_mode():
        # The scheduled place worker runs the same idempotent repair before its
        # bounded scan, because an offline SQL stream cannot inspect live rows.
        op.execute("SELECT 1 /* #755 generic place repair deferred to place worker */")
        return

    with Session(
        bind=op.get_bind(),
        future=True,
        join_transaction_mode="create_savepoint",
    ) as session:
        repair_generic_place_names(session)
        session.commit()


def downgrade() -> None:
    # Removed false resolutions cannot be truthfully reconstructed.
    pass
