"""Labels — unique key backing the idempotent labeler upsert.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-02

`app.labels.persistence.upsert_labels` runs ON CONFLICT DO UPDATE keyed on
(country, bucket_start, label_code, label_source) so reruns refresh rows
instead of duplicating them. That conflict target needs a unique constraint.
The table is empty in every deployment (nothing wrote to it before the
labeler existed), so no duplicate cleanup is required first.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "labels_country_bucket_code_source_key"


def upgrade() -> None:
    op.create_unique_constraint(
        _NAME, "labels", ["country", "bucket_start", "label_code", "label_source"]
    )


def downgrade() -> None:
    op.drop_constraint(_NAME, "labels", type_="unique")
