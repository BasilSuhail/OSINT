"""What is scheduled, and where (#934).

Every other thing this console shows has already happened. This is the one that
looks forward: the elections, referendums and summits due in the next ninety
days, so a reader looking at a country can expect something rather than only
review it.

## Why this is presence, when presence means "now"

The tier next door is defined by tense — where something *is*, this minute. A
calendar is future tense and sits here anyway, because what makes presence a
tier is not the tense but the refusal: nothing is written, nothing is retained,
nothing can be cited later. A schedule scraped today is not evidence that an
election happened, and it must not become a row that later looks like one. A
test in ``tests/test_presence_upcoming.py`` holds the boundary.

## What was measured before this existed

A world map layer of scheduled events was the original idea, and probing the
live query service killed it: three items worldwide carry their own coordinate
over a 30-day window, and joining through a venue found 29, a third of them one
band's tour. Scheduled political events have no coordinate at all, because an
election is not at a building — so the country is the resolution, and there is
no map layer here.

Two numbers shaped what is left:

- **The class list is the performance story.** ``convention``, ``meeting`` and
  ``voting`` pulled in wiki-conferences and an ayahuasca forum and cost 8.8 s.
  Elections, referendums and summits alone answer in 1.1 s.
- **Grouping cannot happen upstream.** Filtering to items whose jurisdiction is
  a sovereign state — the clean way to drop forty US Senate races down to one
  election day — timed out at 65 s. It is done here instead, on (country,
  date), for nothing.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

#: Elections, referendums and summits. Deliberately short: every class added
#: here was measured, and the ones left out cost seconds and returned noise.
_CLASSES: tuple[str, ...] = (
    "Q40231",  # public election
    "Q858439",  # presidential election
    "Q1076105",  # general election
    "Q43109",  # referendum
    "Q1072326",  # summit
)

#: Far enough ahead to be worth planning against, near enough that the list
#: stays readable. Election dates are known months out; ninety days is the
#: horizon where a reader can still do something about one.
HORIZON_DAYS: int = 90

#: A schedule changes on the scale of weeks. Six hours is short enough that a
#: newly announced date appears the same day and long enough that the one slow
#: query is paid once.
_TTL_S: float = 6 * 3600

_TIMEOUT_S = 20.0

_ENDPOINT = "https://query.wikidata.org/sparql"

#: Wikidata answers 403 to callers that do not identify themselves.
_USER_AGENT = "OSINT-console/1.0 (https://github.com/BasilSuhail/OSINT)"

#: Country comes through P17 and is optional. A territory with no ISO code is
#: still a scheduled election, and dropping it to keep the grouping tidy would
#: be losing an answer to gain a shape.
_QUERY = """
SELECT ?item ?itemLabel ?begin ?iso ?countryLabel ?typeLabel WHERE {
  VALUES ?type { %(classes)s }
  ?item wdt:P31 ?type .
  { ?item wdt:P580 ?begin } UNION { ?item wdt:P585 ?begin }
  FILTER(?begin >= "%(start)s"^^xsd:dateTime && ?begin <= "%(end)s"^^xsd:dateTime)
  OPTIONAL {
    ?item wdt:P17 ?country .
    ?country wdt:P297 ?iso .
    ?country rdfs:label ?countryLabel . FILTER(lang(?countryLabel) = "en")
  }
  ?item rdfs:label ?itemLabel . FILTER(lang(?itemLabel) = "en")
  ?type rdfs:label ?typeLabel . FILTER(lang(?typeLabel) = "en")
}
ORDER BY ?begin
LIMIT 400
"""

_cache: dict[str, tuple[float, Any]] = {}


def clear_cache() -> None:
    """Forget the calendar. Tests need this; nothing else does."""
    _cache.clear()


def build_query(today: date, *, days: int = HORIZON_DAYS) -> str:
    return _QUERY % {
        "classes": " ".join(f"wd:{qid}" for qid in _CLASSES),
        "start": f"{today.isoformat()}T00:00:00Z",
        "end": f"{(today + timedelta(days=days)).isoformat()}T00:00:00Z",
    }


def _value(row: dict, field: str) -> str | None:
    return (row.get(field) or {}).get("value") or None


def parse(body: dict[str, Any]) -> list[dict]:
    """Rows into entries, dropping any whose date cannot be read.

    A row with an unreadable date cannot be placed on a calendar, and showing it
    undated would put it somewhere it does not belong.
    """
    entries: list[dict] = []
    for row in (body.get("results") or {}).get("bindings") or []:
        raw = _value(row, "begin")
        name = _value(row, "itemLabel")
        if not raw or not name:
            continue
        try:
            starts = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            continue
        entries.append(
            {
                "name": name,
                "starts_on": starts.isoformat(),
                "iso": _value(row, "iso"),
                "country": _value(row, "countryLabel"),
                "kind": _value(row, "typeLabel"),
            }
        )
    return entries


def _headline(members: list[dict]) -> str:
    """What to call a day.

    One thing is called by its name. Several are called by their number, never
    by one member's name: the shortest label in fifty-seven American contests
    was "2026 Iowa elections", which reads as a fact about Iowa.
    """
    if len(members) == 1:
        return members[0]["name"]
    kinds = {member["kind"] for member in members if member["kind"]}
    if len(kinds) == 1:
        return f"{len(members)} {kinds.pop()}s"
    #: Presidential, general and public elections are all elections, so the
    #: shared noun is what to count. Measured live: one US election day carries
    #: 56 public elections, one presidential election and one referendum.
    #: Naming the nouns it actually holds — "58 elections and referendums" —
    #: beats both "58 public elections", which is wrong, and "58 events
    #: scheduled", which is true and tells the reader nothing.
    nouns = sorted({kind.rsplit(" ", 1)[-1] for kind in kinds})
    if not nouns:
        return f"{len(members)} events scheduled"
    plural = [f"{noun}s" for noun in nouns]
    named = plural[0] if len(plural) == 1 else f"{', '.join(plural[:-1])} and {plural[-1]}"
    return f"{len(members)} {named}"


def group(entries: list[dict]) -> list[dict]:
    """One line per country per day.

    A country with no ISO code cannot be grouped by country, so each stands
    alone rather than being lumped with unrelated territories.
    """
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    loners: list[dict] = []
    for entry in entries:
        if entry["iso"]:
            grouped[(entry["iso"], entry["starts_on"])].append(entry)
        else:
            loners.append(entry)

    lines = [
        {
            "starts_on": day,
            "iso": iso,
            "country": members[0]["country"],
            "headline": _headline(members),
            "kind": members[0]["kind"] if len(members) == 1 else None,
            "count": len(members),
        }
        for (iso, day), members in grouped.items()
    ]
    lines.extend(
        {
            "starts_on": entry["starts_on"],
            "iso": None,
            "country": None,
            "headline": entry["name"],
            "kind": entry["kind"],
            "count": 1,
        }
        for entry in loners
    )
    lines.sort(key=lambda line: (line["starts_on"], line["country"] or "", line["headline"]))
    return lines


def _new_client() -> httpx.Client:
    """The module's own outbound client, named so a test can replace it.

    Patching `httpx.Client` itself would also gag the API test client, which is
    built on httpx — the test would then be measuring its own plumbing.
    """
    return httpx.Client(
        timeout=_TIMEOUT_S, headers={"User-Agent": _USER_AGENT}, follow_redirects=True
    )


def _fetch(client: httpx.Client, days: int) -> list[dict]:
    response = client.get(
        _ENDPOINT,
        params={"query": build_query(datetime.now(UTC).date(), days=days), "format": "json"},
        headers={"User-Agent": _USER_AGENT},
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
    return group(parse(response.json()))


def scheduled(
    *,
    client: httpx.Client | None = None,
    days: int = HORIZON_DAYS,
    iso: str | None = None,
) -> dict:
    """The calendar, whole or for one country.

    One upstream query serves every country: asking about France filters an
    answer already in hand rather than asking Wikidata again.

    A failure is an empty calendar marked degraded, and is not cached — a minute
    of somebody else's downtime must not become six hours of blank screen.
    """
    key = f"upcoming:{days}"
    hit = _cache.get(key)
    now = time.monotonic()

    if hit is not None and now - hit[0] < _TTL_S:
        lines, degraded = hit[1]
    else:
        owned = client is None
        http = client or _new_client()
        try:
            lines, degraded = _fetch(http, days), False
            _cache[key] = (now, (lines, degraded))
        except Exception:
            lines, degraded = [], True
        finally:
            if owned:
                http.close()

    if iso:
        wanted = iso.upper()
        lines = [line for line in lines if line["iso"] == wanted]

    return {
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "days": days,
        "count": len(lines),
        "entries": lines,
        "degraded": degraded,
    }
