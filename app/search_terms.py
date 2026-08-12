"""The words a reader types for a kind of event (#938).

Search matched a full-text vector built from `payload->>'title'` and
`payload->>'summary'`. Measured against the live table over a thirty-day
window, that reached 3.6% of the corpus:

```
category        rows   searchable
hazard     1,950,393          227
geopolitical 152,666       32,370
tracking      82,908            0
news          48,304       48,304
cyber         16,817            0
market            350            0
```

Fire detections, aircraft tracks and malware URLs have no headline and are not
meant to — the reading is the claim. So the box could not find any of them,
and typing "disasters" into a console whose map is 86% fire detections
returned nothing at all.

Every row does carry `keywords`, and that vocabulary is small — 160 distinct
tokens over thirty days — and already says what the row is: a fire detection
is tagged `fire`, a quake `earthquake`, an aircraft sample `aircraft`. What is
missing is only the gap between the token and the word a person types:
`wildfire` for `wf`, `quake` for `earthquake`, `disasters` for a category.

This module is that gap and nothing else. It does not guess: a word not listed
here produces no topic, and the query goes to full-text as before.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    """A kind of event, and how to find it in the columns.

    ``keywords`` matches the `keywords` array; ``category`` matches the column
    of the same name. A topic may set either or both — "disasters" is a whole
    category, "floods" is a keyword within one.
    """

    #: Tokens as they appear in `events.keywords`, not as anyone types them.
    keywords: frozenset[str] = frozenset()
    category: str | None = None


#: Reader's word → what to look for. The right-hand side is checked against the
#: live vocabulary in `tests/test_search_terms.py`; a token that no row carries
#: is a promise the box cannot keep.
#:
#: Plurals and the obvious synonyms are spelled out rather than stemmed. The
#: set is small enough to read, and stemming "ice" or "fl" produces nonsense.
_TOPICS: dict[str, Topic] = {}


def _register(topic: Topic, *words: str) -> None:
    for word in words:
        _TOPICS[word] = topic


#: Whole categories. What a reader means by "disasters" is the hazard
#: category entire — quakes, fires, floods, storms — not one source in it.
_register(Topic(category="hazard"), "disaster", "disasters", "hazard", "hazards")
_register(Topic(category="cyber"), "cyber", "cybersecurity", "malware", "botnet", "threats")
_register(
    Topic(category="tracking"),
    "tracking",
    "flight",
    "flights",
    "aircraft",
    "planes",
    "aviation",
)
_register(Topic(category="news"), "news", "headlines", "press")
_register(Topic(category="market"), "market", "markets", "prediction", "predictions")
_register(Topic(category="geopolitical"), "geopolitical", "geopolitics", "diplomacy")

#: Disaster types. `wf`/`eq`/`fl`/`tc`/`vo`/`dr` are GDACS' codes and are what
#: the rows carry; nobody types them.
_register(
    Topic(keywords=frozenset({"earthquake", "eq", "usgs"})),
    "earthquake",
    "earthquakes",
    "quake",
    "quakes",
    "seismic",
    "tremor",
)
_register(
    Topic(keywords=frozenset({"fire", "wf", "wildfires", "firms"})),
    "fire",
    "fires",
    "wildfire",
    "wildfires",
    "blaze",
)
_register(Topic(keywords=frozenset({"fl"})), "flood", "floods", "flooding")
_register(
    Topic(keywords=frozenset({"tc", "severeStorms"})),
    "cyclone",
    "cyclones",
    "hurricane",
    "hurricanes",
    "typhoon",
    "typhoons",
    "storm",
    "storms",
)
_register(Topic(keywords=frozenset({"vo"})), "volcano", "volcanoes", "volcanic", "eruption")
_register(Topic(keywords=frozenset({"dr"})), "drought", "droughts")
_register(Topic(keywords=frozenset({"seaLakeIce"})), "ice", "snow", "glacier", "glaciers")


def topic_for(query: str) -> Topic | None:
    """The kind of event ``query`` names, or None if it names none.

    Only a query that is *entirely* a topic word counts. "fire" is a request
    for fire detections; "fire at the docks" is a sentence, and answering it
    with 1.9 million satellite readings would bury the thing actually asked
    for. A phrase that is not a topic falls through to full-text, which is
    where sentences belong.
    """
    return _TOPICS.get(" ".join(query.strip().lower().split()))


def topic_words() -> frozenset[str]:
    """Every word this module answers to. For tests and for nothing else."""
    return frozenset(_TOPICS)
