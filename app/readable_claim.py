"""What a reader can be shown (#810).

A marker asserts that something happened at a place. A reader who clicks it is
owed what that something was. GDELT rows arrive before their headline does,
and most of them never get one:

```
precision   rows     positioned   untitled      (seven days, live table)
city       15,770       15,770      5,302
country     4,355        4,354      4,354
admin       4,103        4,103      4,103
```

`app.enrichment.gdelt_titles.pending_ids` only considers `geo_precision ==
'city'`, on the stated grounds that country-precision rows are never pinned.
They are: 4,354 of 4,355 carry coordinates. So the 8,457 country and admin
rows are drawn and can never be explained, on points that were never places —
320 of them sat on 39.828, -98.580, the geographic centre of the United
States. The frontend falls back to `title ?? ev.source`, so the reader is
handed a list row that says "gdelt".

This module decides which rows carry a readable claim. It does not delete
anything, and it does not judge quality: a bad headline is still a headline,
and the question of whether a country centroid should be drawn at all belongs
to #773.

**Only GDELT is judged on a headline.** A quake, an aircraft track and a fire
detection have no title and are not meant to — the reading is the claim. An
RSS row cannot exist without a title because the fetcher drops the entry, so
including RSS here would be a rule with no subject.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.db_models import EventRow

#: The one source that ships rows before it knows what they say.
JUDGED_SOURCE = "gdelt"


def has_readable_claim() -> sa.ColumnElement[bool]:
    """True for rows a reader can be shown.

    An empty string is treated as no headline: it renders as blank, which is
    the same defect wearing a different storage shape.
    """
    title = EventRow.payload["title"].as_string()
    return sa.or_(
        EventRow.source != JUDGED_SOURCE,
        sa.and_(title.is_not(None), title != ""),
    )


#: The same rule as SQL text, for the search path, which is raw PostgreSQL
#: because it ranks on `ts_rank_cd`. Kept next to the expression version so the
#: two cannot drift apart unnoticed.
READABLE_CLAIM_SQL = """
        (source <> 'gdelt' OR coalesce(payload->>'title', '') <> '')
"""


def readable_only(stmt: Any) -> Any:
    """Apply the filter to a `select(EventRow)`."""
    return stmt.where(has_readable_claim())
