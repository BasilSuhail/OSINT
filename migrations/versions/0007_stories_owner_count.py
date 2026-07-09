"""Stories owner_count — distinct content owners per story (WS-C step 2, #355).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-09

`outlet_count` counts feeds; the corroboration input is *independent tellers*.
Adds `stories.owner_count` and recomputes it for every existing story from its
members, using a frozen snapshot of the owner registry as of this migration
(rss_feeds.json is the living copy). Sources absent from the snapshot count as
their own owner, so the backfill can never inflate independence.

Stories whose member events were already pruned by the 30-day retention have
no evidence left to recount; they keep `owner_count = outlet_count` — exactly
the independence claim the system made before #355 — rather than a
false-precise 1.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen source → content-owner snapshot (syndication already resolved:
# the Yahoo-hosted feed carries Reuters wire, RT + TASS share one controller).
OWNER_SNAPSHOT: dict[str, str] = {
    "rss-bbc-world": "bbc",
    "rss-bbc-uk": "bbc",
    "rss-reuters-world": "reuters",
    "rss-dawn": "dawn-media",
    "rss-guardian-world": "guardian-media",
    "rss-geo-english": "jang-group",
    "rss-aljazeera": "aljazeera",
    "rss-cnn-world": "cnn",
    "rss-nyt-world": "nyt",
    "rss-france24-en": "france-medias-monde",
    "rss-dw-world": "dw",
    "rss-nhk-world": "nhk",
    "rss-rt-news": "russian-state",
    "rss-tass-en": "russian-state",
    "rss-times-of-india": "times-group",
    "rss-the-hindu": "kasturi-sons",
    "rss-tribune-pk": "lakson-group",
    "rss-cbc-world": "cbc",
    "rss-abc-au-world": "abc-au",
    "rss-rnz-world": "rnz",
    "rss-straits-times-world": "sph-media",
    "rss-jpost-world": "jpost",
    "rss-haaretz-en": "haaretz-group",
    "rss-arab-news": "srmg",
    "rss-kyiv-independent": "kyiv-independent",
}


def upgrade() -> None:
    op.add_column(
        "stories",
        sa.Column("owner_count", sa.Integer, nullable=False, server_default="1"),
    )

    lookup = sa.values(
        sa.column("source", sa.Text), sa.column("owner", sa.Text), name="owner_lookup"
    ).data(sorted(OWNER_SNAPSHOT.items()))

    members = sa.table(
        "story_members",
        sa.column("story_id", sa.BigInteger),
        sa.column("event_id", sa.BigInteger),
    )
    events = sa.table("events", sa.column("id", sa.BigInteger), sa.column("source", sa.Text))
    stories = sa.table(
        "stories",
        sa.column("id", sa.BigInteger),
        sa.column("owner_count", sa.Integer),
        sa.column("outlet_count", sa.Integer),
    )

    counts = (
        sa.select(
            members.c.story_id.label("story_id"),
            sa.func.count(
                sa.distinct(sa.func.coalesce(lookup.c.owner, events.c.source))
            ).label("owners"),
        )
        .select_from(
            members.join(events, events.c.id == members.c.event_id).outerjoin(
                lookup, lookup.c.source == events.c.source
            )
        )
        .group_by(members.c.story_id)
        .subquery()
    )
    op.execute(
        sa.update(stories)
        .where(stories.c.id == counts.c.story_id)
        .values(owner_count=counts.c.owners)
    )

    # Retention already deleted every member event of some stories — nothing to
    # recount there. Carry over outlet_count (the pre-#355 claim) instead of
    # leaving the misleading server default of 1.
    surviving = (
        sa.select(members.c.story_id)
        .select_from(members.join(events, events.c.id == members.c.event_id))
        .where(members.c.story_id == stories.c.id)
    )
    op.execute(
        sa.update(stories)
        .where(~sa.exists(surviving))
        .values(owner_count=stories.c.outlet_count)
    )


def downgrade() -> None:
    op.drop_column("stories", "owner_count")
