"""Does searching a city return that city's news? (#798)

Every accuracy number this project has published so far was measured against
the metric the issue itself chose — news rows carrying a country went 73% →
28% → 14%. That is real, and it flatters the work, because it grades the
resolver on rows already in the database rather than grading the console on
the question a reader actually asks: *type a city, get that city's news*.

Run against Edinburgh by hand, the answer was 40 results of which 20 matched
"Duke of Edinburgh" — a title, not a place. Half. Four merged pull requests
went past that without anyone noticing, which is what an unmeasured surface
looks like.

## What this measures, and what it does not

It does **not** judge relevance. Nothing here knows whether a story is
"about" Edinburgh, and a check that claimed to would be the same kind of
comfortable fiction it exists to prevent.

It counts three named, objective defects:

- **collisions** — every occurrence of the query sits inside an honorific
  ("Duke of Edinburgh"), so the term is a person's title, not a place
- **duplicates** — the same headline returned more than once
- **unpositioned** — no coordinates, so the row cannot be placed on the map

and two facts worth watching beside them: how many publishers the results
came from, and how many rows there were at all. A city served by one feed is
a coverage problem no ranking change can fix.

The headline number is `clean_share`: results left after removing collisions
and duplicates. It is a ceiling on relevance, never a claim of it — a story
can be free of all three defects and still not be about the place.

The collision rule itself lives in `app.enrichment.name_collision`, shared
with the search that drops these rows (#800). That sharing has a cost worth
stating: once search filters on it, this probe reports zero collisions,
because it is measuring the output of a filter using the same rule. It
keeps its value as a regression alarm and for the metrics it does not share
— duplicates, publishers, rows positioned in the city — but it cannot
discover a collision class the filter misses. Nothing automatic can.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt
from typing import Any, Final

from sqlalchemy.orm import Session

from app.enrichment.name_collision import is_collision
from app.search import search

#: How close a row must sit to count as positioned in the city. Generous on
#: purpose — this asks "is it in the right place at all", not "is the pin
#: exact", which is #773's question.
DEFAULT_RADIUS_KM: Final[float] = 40.0

#: The probe set. Cities picked to span the coverage story rather than to
#: look good: a capital with one feed, one with several, and two outside the
#: English-language core where the gap is widest.
PROBE_CITIES: Final[tuple[tuple[str, float, float], ...]] = (
    ("edinburgh", 55.9533, -3.1883),
    ("glasgow", 55.8642, -4.2518),
    ("lahore", 31.5204, 74.3587),
    ("nairobi", -1.2864, 36.8172),
)


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance. Plain haversine — no dependency for one formula."""
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


def _row_text(row: dict[str, Any]) -> str:
    payload = row.get("payload") or {}
    parts = [payload.get("title"), payload.get("summary"), payload.get("action_label")]
    return " ".join(str(p) for p in parts if p)


@dataclass
class CityProbe:
    """One city's answer, as counts rather than a verdict."""

    city: str
    results: int = 0
    collisions: int = 0
    duplicates: int = 0
    positioned_in_city: int = 0
    unpositioned: int = 0
    publishers: int = 0
    examples: list[str] = field(default_factory=list)

    @property
    def clean(self) -> int:
        """Results left after the two defects that are unambiguously wrong."""
        return max(0, self.results - self.collisions - self.duplicates)

    @property
    def clean_share(self) -> float:
        return self.clean / self.results if self.results else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "city": self.city,
            "results": self.results,
            "collisions": self.collisions,
            "duplicates": self.duplicates,
            "positioned_in_city": self.positioned_in_city,
            "unpositioned": self.unpositioned,
            "publishers": self.publishers,
            "clean": self.clean,
            "clean_share": round(self.clean_share, 3),
        }


def probe_city(
    session: Session,
    city: str,
    lat: float,
    lon: float,
    *,
    limit: int = 40,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> CityProbe:
    """Run one city's search and count what came back."""
    rows = search(session, city, limit=limit).events
    out = CityProbe(city=city, results=len(rows))
    seen: set[str] = set()
    publishers: set[str] = set()
    for row in rows:
        text = _row_text(row)
        publishers.add(str(row.get("source") or ""))
        key = text[:120].strip().lower()
        if key and key in seen:
            out.duplicates += 1
        elif key:
            seen.add(key)
        if is_collision(text, city):
            out.collisions += 1
            if len(out.examples) < 3:
                out.examples.append(text[:90])
        row_lat, row_lon = row.get("lat"), row.get("lon")
        if row_lat is None or row_lon is None:
            out.unpositioned += 1
        elif _km(lat, lon, float(row_lat), float(row_lon)) <= radius_km:
            out.positioned_in_city += 1
    out.publishers = len(publishers)
    return out


def probe_all(session: Session, *, limit: int = 40) -> list[CityProbe]:
    return [probe_city(session, name, lat, lon, limit=limit) for name, lat, lon in PROBE_CITIES]


def format_report(probes: list[CityProbe]) -> str:
    """A table, and no verdict. The numbers are the finding."""
    head = (
        f"{'city':<12}{'results':>8}{'collide':>8}{'dupes':>7}"
        f"{'in-city':>8}{'pubs':>6}{'clean':>7}{'clean%':>8}"
    )
    lines = [head, "-" * len(head)]
    for p in probes:
        lines.append(
            f"{p.city:<12}{p.results:>8}{p.collisions:>8}{p.duplicates:>7}"
            f"{p.positioned_in_city:>8}{p.publishers:>6}{p.clean:>7}"
            f"{p.clean_share:>7.0%}"
        )
    return "\n".join(lines)


def main() -> int:
    """`python -m app.audit.city_probe` — run the probe and print the table.

    On demand rather than on a schedule, deliberately: this is the number a
    change to search or to the resolver should be checked against *before*
    it ships, which is the failure it exists to prevent. Wiring it into the
    nightly audit with stored history is worth doing once it has a few runs
    behind it to compare against.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.settings import settings

    engine = create_engine(settings.postgres_url)
    with sessionmaker(bind=engine)() as session:
        probes = probe_all(session)
    print(format_report(probes))
    for probe in probes:
        for example in probe.examples:
            print(f"  {probe.city}: {example}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
