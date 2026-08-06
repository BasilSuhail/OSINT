"""When a place name in a sentence is not a place (#800).

A city's name is also a person's title, an award, a football club and a
street. Searching "edinburgh" returned forty rows of which twenty were the
Duke and Duchess of Edinburgh — a dukedom, not the capital of Scotland.

This is the same defect as #771's honorific place-matches and #794's
"Salinas", reached through full-text search rather than through the
resolver. One implementation, used by both the search that must drop these
rows and the probe that counts them, because two copies of a rule this
fiddly will drift and the number will stop describing the product.

## What that shared use costs, stated rather than discovered later

Once search filters on this predicate, `app.audit.city_probe` will report
zero collisions — it is measuring the output of the filter that uses the
same rule. The probe keeps its value for regression (a change that breaks
the filter shows up immediately) and for the metrics it does not share:
duplicates, publisher count, how many rows are positioned in the city at
all. It cannot discover a *new* collision class the filter misses. Nothing
automatic can; that stays a human reading results.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Final

#: Titles that take "of <Place>" and name a person. "Duke of Edinburgh",
#: "Earl of Wessex", "Bishop of Durham", "Prince of Wales".
HONORIFICS: Final[tuple[str, ...]] = (
    "duke",
    "duchess",
    "dukes",
    "earl",
    "countess",
    "count",
    "lord",
    "lady",
    "baron",
    "baroness",
    "marquess",
    "marchioness",
    "viscount",
    "viscountess",
    "prince",
    "princess",
    "bishop",
    "archbishop",
    "sheriff",
    "mayor",
)

#: Named things that borrow a place's name outright and then happen
#: somewhere else. "Tributes to teenager who died during Duke of Edinburgh
#: expedition" — that expedition was in Snowdonia.
BORROWED: Final[tuple[str, ...]] = (
    "award",
    "awards",
    "scheme",
    "expedition",
    "medal",
    "trophy",
    "prize",
)


@lru_cache(maxsize=512)
def _patterns(term: str) -> tuple[re.Pattern[str], re.Pattern[str], re.Pattern[str]]:
    """Compiled once per query term — search calls this per row.

    Cached on the term rather than the text: a search runs one term over
    forty rows, so the terms repeat and the texts never do.
    """
    needle = re.escape(term)
    titles = "|".join(HONORIFICS)
    borrowed = "|".join(BORROWED)
    return (
        re.compile(rf"\b{needle}\b"),
        #: "duke of edinburgh", "duke and duchess of edinburgh"
        re.compile(rf"\b(?:{titles})\b(?:\s+and\s+\b(?:{titles})\b)?\s+of\s+{needle}\b"),
        #: "edinburgh award", "edinburgh's award"
        re.compile(rf"\b{needle}(?:'s)?\s+(?:{borrowed})\b"),
    )


def is_collision(text: str, term: str) -> bool:
    """True when *every* mention of ``term`` in ``text`` is a title or a
    borrowed name, and so none of them is the place.

    "Every" is load-bearing. A story that says both "the Duke of Edinburgh
    opened it" and "in Edinburgh" is about the place, and dropping it would
    trade one wrong answer for another — the precision failure that started
    #717, in the opposite direction.
    """
    if not text or not term:
        return False
    lowered = text.lower()
    needle = term.lower()
    if needle not in lowered:
        return False
    mention, as_title, as_borrowed = _patterns(needle)
    hits = len(mention.findall(lowered))
    if hits == 0:
        return False
    covered = len(as_title.findall(lowered)) + len(as_borrowed.findall(lowered))
    return covered >= hits
