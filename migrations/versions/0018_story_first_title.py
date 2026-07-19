"""Keep a story's opening headline when its title starts tracking (#516).

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-19

`stories.title` was written once, from whichever article opened the cluster, and
never revised — so a developing story kept its earliest, least-informed account
as its name. It now follows the newest member headline.

`first_title` preserves the opening headline so that change stays auditable, and
because the drift between a story's first framing and its current one is itself
a signal worth measuring: casualty counts climbing, a description hardening.

Existing rows are backfilled from `title`, which is by definition still the
opening headline at the moment this runs — nothing has ever overwritten it.

Titles are then corrected in place from each story's newest member. Without
this, only stories that happen to gain another member would ever heal, and every
story that has stopped updating would keep its earliest account forever — which
is the whole defect. `first_title` is captured first, so the original survives.

Embeddings for corrected stories are deleted so the enrich beat rebuilds them.
`story_embed_text` is "title · gist · keywords" and `embed_missing_stories`
skips any story that already has a vector, so a corrected title would otherwise
keep being retrieved through text it no longer says.

Postgres-only SQL (DISTINCT ON). Nothing runs migrations against SQLite.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stories", sa.Column("first_title", sa.Text, nullable=True))
    # Capture the opening headline BEFORE correcting titles below.
    op.execute("UPDATE stories SET first_title = title WHERE first_title IS NULL")
    op.execute(
        """
        UPDATE stories AS s
        SET title = newest.title
        FROM (
            SELECT DISTINCT ON (m.story_id)
                   m.story_id,
                   e.payload ->> 'title' AS title
            FROM story_members m
            JOIN events e ON e.id = m.event_id
            WHERE e.payload ->> 'title' IS NOT NULL
              AND e.payload ->> 'title' <> ''
            ORDER BY m.story_id, e.occurred_at DESC
        ) AS newest
        WHERE newest.story_id = s.id
          AND newest.title <> s.title
        """
    )
    op.execute(
        """
        DELETE FROM story_embeddings
        WHERE story_id IN (
            SELECT id FROM stories
            WHERE first_title IS NOT NULL AND title <> first_title
        )
        """
    )


def downgrade() -> None:
    # Restore the opening headlines before losing the column that holds them.
    op.execute("UPDATE stories SET title = first_title WHERE first_title IS NOT NULL")
    op.drop_column("stories", "first_title")
