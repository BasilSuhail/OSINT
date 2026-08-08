"""One article, one row (#772).

GDELT extracts an event per actor pairing it finds in an article, so a single
news story arrives as several `GLOBALEVENTID`s sharing a `source_url`, a
headline, a coordinate and an event code. Storage keeps all of them — the
relations differ in actors and mention counts and analytics reads them — but a
reader looking at a list of what happened near a place should see the story
once.

Measured on the live table before this module existed: 8,670 GDELT rows over
three days carried 3,958 distinct (`source_url`, `event_root_code`) pairs, and
one article contributed forty rows to the same coordinate.

Two decisions worth stating.

**The key is the article and the point, not the article alone.** Of the 1,860
articles producing more than one row in that window, 1,049 place their rows at
different coordinates — an article about strikes in two cities is two things
that happened, and collapsing on the URL alone would erase one of them from the
map. The event code is deliberately *not* part of the key: 180 articles emitted
several root codes at a single coordinate, which is one sentence classified
twice, and a reader seeing the same headline pinned twice to the same street
does not care that GDELT called it both `Coerce` and `Fight`. Same article,
same point, one row; same article, another point, another row.

**The collapse happens in SQL, before `LIMIT`.** Thinning a page in Python
after the database applied the limit returns a short page, and
`fetchAllEventPages` treats a short page as the end of the data, so the map
would stop loading early. That is the truncation #770 was about, and it is the
reason this is a window function rather than four lines of Python.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy import Select
from sqlalchemy.orm import aliased

from app.db_models import EventRow

#: Only this source multiplies one article into several rows. RSS duplicates
#: are a different defect with their own fix (#751), and a sensor reporting the
#: same aircraft twice is two readings, not one row said twice.
COLLAPSED_SOURCE = "gdelt"


def _article_key() -> sa.ColumnElement[str]:
    """What counts as "the same thing said twice".

    Rows that cannot be duplicates of anything — every non-GDELT row, and any
    GDELT row with no article URL — are keyed by their own primary key, so they
    are alone in their partition and always survive. Absence of a URL is
    absence of evidence that two rows came from one report; keying those
    together would merge unrelated events that happen to share an event code.
    """
    url = EventRow.payload["source_url"].as_string()
    lat = sa.func.coalesce(sa.cast(EventRow.lat, sa.Text), "")
    lon = sa.func.coalesce(sa.cast(EventRow.lon, sa.Text), "")
    own_id = sa.cast(EventRow.id, sa.Text)
    return sa.case(
        (
            sa.and_(EventRow.source == COLLAPSED_SOURCE, url.is_not(None)),
            url.concat("|").concat(lat).concat("|").concat(lon),
        ),
        else_=own_id,
    )


def _survivor_order() -> list[sa.ColumnElement[Any]]:
    """Most-cited relation wins, oldest id breaks the tie.

    `num_mentions` is GDELT's count of how often the article was referenced,
    so the highest is the relation carrying the most evidence that anyone read
    it. `coalesce` rather than `NULLS LAST` keeps the ordering identical on
    SQLite, which the tests run on.
    """
    mentions = sa.cast(EventRow.payload["num_mentions"].as_string(), sa.Float)
    return [sa.func.coalesce(mentions, -1.0).desc(), EventRow.id.asc()]


def collapse_article_relations(
    stmt: Select[Any],
) -> tuple[Any, sa.ColumnElement[int], sa.ColumnElement[bool]]:
    """Wrap a `select(EventRow)` so each article contributes one row.

    Returns the entity to select from, the relation-count column, and the
    predicate that keeps the survivor — all bound to the wrapped subquery. The
    caller applies its own ordering and limit to them, which is the point: the
    limit then counts rows a reader sees rather than relations a parser
    produced.
    """
    key = _article_key()
    windowed = stmt.add_columns(
        sa.func.row_number().over(partition_by=key, order_by=_survivor_order()).label("rank"),
        sa.func.count().over(partition_by=key).label("relation_count"),
    ).subquery()
    entity = aliased(EventRow, windowed)
    return entity, windowed.c.relation_count, windowed.c.rank == 1


#: The same rule as SQL text, for the search path, which is raw PostgreSQL
#: because it ranks on `ts_rank_cd`. Kept beside the expression version so the
#: two definitions of "same article" cannot drift apart unnoticed.
ARTICLE_KEY_SQL = """
        CASE
            WHEN source = 'gdelt' AND payload->>'source_url' IS NOT NULL
            THEN (payload->>'source_url') || '|' ||
                 coalesce(lat::text, '') || '|' || coalesce(lon::text, '')
            ELSE id::text
        END
"""

SURVIVOR_ORDER_SQL = """
        coalesce((payload->>'num_mentions')::float, -1) DESC, id ASC
"""
