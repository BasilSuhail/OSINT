"""How much a coordinate is actually claiming (#773).

A row's latitude and longitude mean wildly different things depending on how
they were arrived at, and until now the map drew all of them as the same dot.
Measured over seven days of positioned news and GDELT rows:

```
basis    precision   rows
(gdelt)  city       17,903
(gdelt)  country     4,789
(gdelt)  admin       4,502
city     city        1,936
term     city        1,278
region   region        772
place    building      159
place    site           14
place    street          8
```

**181 rows out of 31,361 are standing on a place somebody verified.** The rest
are the centroid of a city, an administrative area or a country, and a reader
zooming into an empty field in Kansas found 320 events there.

This module answers one question — *how big is the claim?* — and answers it
with a radius in metres, because that is the honest shape of the answer. A
city-centroid row is not wrong; it is a claim about a city, and a claim about
a city is roughly a city wide.

The radii are deliberately round numbers. They are the order of magnitude of
the thing named, not a measurement of it: no gazetteer here records the actual
extent of Lagos or Rutland, and pretending otherwise would be the same
overclaim one layer up.
"""

from __future__ import annotations

from typing import Any, Final, Literal

Precision = Literal["exact", "city", "area", "country", "unknown"]

#: Roughly how far from the given point the event might actually be. A
#: verified venue is where it says; a country centroid is anywhere in the
#: country. Metres, and round on purpose.
RADIUS_M: Final[dict[Precision, int]] = {
    "exact": 100,
    "city": 8_000,
    "area": 60_000,
    "country": 400_000,
    "unknown": 0,
}

#: What the resolver's own vocabulary means in these terms. `place` is the only
#: basis backed by a verified location (#756), so it is the only one that earns
#: `exact`.
_BY_BASIS: Final[dict[str, Precision]] = {
    "place": "exact",
    "city": "city",
    "region": "area",
    "term": "country",
    "desk": "country",
    "domestic": "country",
}

#: GDELT carries no `geo_basis`; it records the precision of its own geocoder.
_BY_GDELT_PRECISION: Final[dict[str, Precision]] = {
    "building": "exact",
    "street": "exact",
    "site": "exact",
    "city": "city",
    "admin": "area",
    "country": "country",
}


def precision_of(source: str, payload: dict[str, Any] | None, *, positioned: bool) -> Precision:
    """How precise this row's coordinate is, in one shared vocabulary.

    A row with no coordinate gets `unknown` rather than a precision, because
    an absent point makes no claim at all and giving it one would invent a
    kind of certainty out of nothing.
    """
    if not positioned:
        return "unknown"
    data = payload or {}
    basis = str(data.get("geo_basis") or "")
    if basis in _BY_BASIS:
        # A `term` or `city` basis still borrows its point from the gazetteer,
        # so the gazetteer's own precision is the tighter of the two claims.
        by_basis = _BY_BASIS[basis]
        by_precision = _BY_GDELT_PRECISION.get(str(data.get("geo_precision") or ""))
        if by_precision is not None and RADIUS_M[by_precision] > RADIUS_M[by_basis]:
            return by_precision
        return by_basis
    coded = _BY_GDELT_PRECISION.get(str(data.get("geo_precision") or ""))
    if coded is not None:
        return coded
    #: A sensor reading is an instrument's own position: a fire pixel, an
    #: epicentre, an aircraft. Those are measurements, not geocodes.
    if source in {"usgs-quake", "nasa-firms", "opensky-adsb", "gdacs", "eonet", "abuse-ch-feodo"}:
        return "exact"
    return "unknown"


def radius_m(precision: Precision) -> int:
    """How far from the point the event might be. Zero when nothing is claimed."""
    return RADIUS_M.get(precision, 0)
