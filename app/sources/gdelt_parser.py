"""GDELT v2 export CSV → canonical `Event` transformation.

Pure functions only. The HTTP layer lives in `gdelt_fetcher` and calls these
functions over the downloaded CSV body.

GDELT v2 export schema reference:
https://www.gdeltproject.org/data.html#documentation
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from app.enrichment.country import country_for
from app.models import Category, Event
from app.sources.gdelt_cameo import fips_to_iso, is_conflict_event

#: Tab-separated column indices for the GDELT v2 export schema. Only the
#: fields the fetcher actually reads are named here.
COL_GLOBAL_EVENT_ID: Final[int] = 0
COL_DAY: Final[int] = 1
COL_EVENT_ROOT_CODE: Final[int] = 28
COL_GOLDSTEIN: Final[int] = 30
COL_NUM_MENTIONS: Final[int] = 31
COL_AVG_TONE: Final[int] = 34
#: ActionGeo_Type — GDELT's own statement of how precisely it placed the
#: event. 1 country, 2 US state, 3 US city, 4 world city, 5 world state.
#: Without it a "somewhere in Russia" coordinate is indistinguishable from
#: a street in Kharkiv, and both get drawn as pins (#727).
COL_ACTION_GEO_TYPE: Final[int] = 51
#: ActionGeo_FullName — free text, "Tehran, Tehran, Iran" or bare "Iran".
#: Named COL_ACTION_COUNTRY historically and read as a FIPS code, which it
#: has never been; see the note in ``row_to_event``.
COL_ACTION_COUNTRY: Final[int] = 52
COL_ACTION_LAT: Final[int] = 56
COL_ACTION_LON: Final[int] = 57
COL_SOURCE_URL: Final[int] = 59

#: Min field count a valid GDELT row exposes. The schema has 61 columns;
#: GDELT occasionally publishes rows with trailing-tab oddities — we require
#: at least up to the source-URL column so the parser is robust.
MIN_FIELD_COUNT: Final[int] = COL_SOURCE_URL + 1


def _parse_optional_float(raw: str) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_optional_int(raw: str) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


#: ActionGeo_Type values that mean GDELT placed the event in a settlement.
_CITY_GEO_TYPES: Final[frozenset[int]] = frozenset({3, 4})  # US city, world city
#: …in a first-order administrative area.
_ADMIN_GEO_TYPES: Final[frozenset[int]] = frozenset({2, 5})  # US state, world state


def geo_precision(geo_type: int | None, geo_name: str | None) -> str:
    """How precisely GDELT placed this event: city, admin, country, unknown.

    A country-level row's coordinate means "somewhere in Russia" — a real
    number that is not a real place. Drawn as a pin it stacks with every
    other unplaceable event from that country: measured over three days,
    admin-level rows piled 21 deep on a single point and country-level rows
    10 deep, while city-level rows spread 4,165 events over 1,085 distinct
    places. Keeping the distinction is what lets the map draw only the
    third kind (#727).

    Falls back to counting the parts of ``ActionGeo_FullName`` when the type
    column is absent, so rows stored before the type was read ("Tehran,
    Tehran, Iran" → city, bare "Iran" → country) still classify.
    """
    if geo_type in _CITY_GEO_TYPES:
        return "city"
    if geo_type in _ADMIN_GEO_TYPES:
        return "admin"
    if geo_type == 1:
        return "country"
    if not geo_name:
        return "unknown"
    parts = [p for p in geo_name.split(",") if p.strip()]
    if len(parts) >= 3:
        return "city"
    if len(parts) == 2:
        return "admin"
    return "country"


def _goldstein_to_severity(goldstein: float) -> float:
    """Map the Goldstein scale (-10..+10) to a severity in [0, 1].

    Goldstein is negative for escalatory events and positive for cooperative
    ones; the composite stress index treats escalation as high severity.
    """
    severity = (10.0 - goldstein) / 20.0
    return max(0.0, min(1.0, severity))


def row_to_event(fields: list[str], *, fetched_at: datetime) -> Event | None:
    """Convert a single GDELT export row (already split into fields) to an Event.

    Returns None when the row should be skipped:
    - too few columns (malformed)
    - EventRootCode not in the conflict-relevant CAMEO set
    - Day cannot be parsed into a date
    - GoldsteinScale is missing or non-numeric (required for severity)
    """
    if len(fields) < MIN_FIELD_COUNT:
        return None

    event_root_code = fields[COL_EVENT_ROOT_CODE].strip()
    if not is_conflict_event(event_root_code):
        return None

    global_event_id = fields[COL_GLOBAL_EVENT_ID].strip()
    if not global_event_id:
        return None

    day_str = fields[COL_DAY].strip()
    try:
        occurred_at = datetime.strptime(day_str, "%Y%m%d").replace(tzinfo=UTC)
    except ValueError:
        return None

    goldstein_raw = _parse_optional_float(fields[COL_GOLDSTEIN])
    if goldstein_raw is None:
        return None
    severity = _goldstein_to_severity(goldstein_raw)

    country = fips_to_iso(fields[COL_ACTION_COUNTRY].strip() or None)

    lat = _parse_optional_float(fields[COL_ACTION_LAT])
    lon = _parse_optional_float(fields[COL_ACTION_LON])

    # Column 52 is ActionGeo_FullName, not a FIPS code — "Tehran, Tehran,
    # Iran" or a bare "Iran". `fips_to_iso` therefore returns None for
    # essentially every row and the polygon lookup below is what actually
    # assigns the country. The real ActionGeo_CountryCode is column 53;
    # correcting that moves country attribution for every GDELT row, so it
    # is deliberately left alone here and measured separately (#727).
    if country is None and lat is not None and lon is not None:
        country = country_for(lat, lon)
    geo_name = fields[COL_ACTION_COUNTRY].strip() or None
    geo_type = _parse_optional_int(fields[COL_ACTION_GEO_TYPE])

    num_mentions = _parse_optional_float(fields[COL_NUM_MENTIONS])
    avg_tone = _parse_optional_float(fields[COL_AVG_TONE])
    source_url = fields[COL_SOURCE_URL].strip() or None

    payload = {
        "global_event_id": global_event_id,
        "day": day_str,
        "event_root_code": event_root_code,
        "goldstein": goldstein_raw,
        "num_mentions": num_mentions,
        "avg_tone": avg_tone,
        "geo_name": geo_name,
        "geo_type": geo_type,
        "geo_precision": geo_precision(geo_type, geo_name),
        # Kept under its old (wrong) name so existing readers and stored rows
        # stay consistent until they migrate to geo_name.
        "country_fips": geo_name,
        "source_url": source_url,
    }

    keywords = ["gdelt", f"cameo:{event_root_code}"]

    return Event(
        source="gdelt",
        source_event_id=global_event_id,
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.GEOPOLITICAL,
        severity=severity,
        confidence=None,
        keywords=keywords,
        country=country,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_csv_body(body: str, *, fetched_at: datetime) -> list[Event]:
    """Parse the tab-separated export body returned by a GDELT zip.

    Skips malformed and filtered-out rows; never raises on bad data.
    """
    events: list[Event] = []
    for line in body.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        event = row_to_event(fields, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events
