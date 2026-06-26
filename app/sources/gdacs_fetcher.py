"""Module C — Hazards: GDACS multi-hazard RSS feed.

GDACS publishes a rolling 4-day feed of active hazards (earthquakes, tropical
cyclones, floods, droughts, volcanoes, wildfires). Each item carries an
alert level (green / orange / red) which directly maps to severity.

A bounded ISO 3166-1 alpha-3 → alpha-2 table covers the panel countries plus
common conflict / hazard-prone countries. Items whose ISO3 is not in the table
keep country=None and the raw iso3 in payload, so the rejection can be
debugged from the database alone.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Final
from xml.etree import ElementTree as ET

import httpx

from app.models import Category, Event
from app.sources.base import Fetcher

GDACS_FEED_URL: Final[str] = "https://www.gdacs.org/xml/rss.xml"
GDACS_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"

#: GDACS event-list search API. Unlike the 4-day ``rss.xml`` alert feed (which
#: carries no volcanoes and only the 1-2 most recent cyclones), this returns the
#: full active set per event type. It caps at 100 results per call, so we query
#: each type separately — otherwise the frequent earthquakes / wildfires crowd
#: out the sparse volcanoes and cyclones the map needs.
GDACS_API_SEARCH_URL: Final[str] = (
    "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
    "?eventlist={eventlist}&alertlevel=Green;Orange;Red"
)
GDACS_API_EVENT_TYPES: Final[tuple[str, ...]] = ("EQ", "TC", "FL", "VO", "DR", "WF")

_NAMESPACES: Final[dict[str, str]] = {
    "gdacs": "http://www.gdacs.org",
    "georss": "http://www.georss.org/georss",
    "dc": "http://purl.org/dc/elements/1.1/",
}

_ALERT_LEVEL_SEVERITY: Final[dict[str, float]] = {
    "green": 0.2,
    "orange": 0.6,
    "red": 1.0,
}

#: ISO 3166-1 alpha-3 → alpha-2 lookup covering the 10-country market panel
#: plus the conflict / hazard hotspots most likely to surface in GDACS.
ISO3_TO_ISO2: Final[dict[str, str]] = {
    "AFG": "AF",
    "ARG": "AR",
    "AUS": "AU",
    "AUT": "AT",
    "BEL": "BE",
    "BGD": "BD",
    "BGR": "BG",
    "BLR": "BY",
    "BOL": "BO",
    "BRA": "BR",
    "CAN": "CA",
    "CHE": "CH",
    "CHL": "CL",
    "CHN": "CN",
    "COD": "CD",
    "COL": "CO",
    "CUB": "CU",
    "CZE": "CZ",
    "DEU": "DE",
    "DNK": "DK",
    "DOM": "DO",
    "DZA": "DZ",
    "ECU": "EC",
    "EGY": "EG",
    "ERI": "ER",
    "ESP": "ES",
    "EST": "EE",
    "ETH": "ET",
    "FIN": "FI",
    "FRA": "FR",
    "GBR": "GB",
    "GEO": "GE",
    "GRC": "GR",
    "HKG": "HK",
    "HND": "HN",
    "HRV": "HR",
    "HUN": "HU",
    "IDN": "ID",
    "IND": "IN",
    "IRL": "IE",
    "IRN": "IR",
    "IRQ": "IQ",
    "ISL": "IS",
    "ISR": "IL",
    "ITA": "IT",
    "JOR": "JO",
    "JPN": "JP",
    "KAZ": "KZ",
    "KEN": "KE",
    "KHM": "KH",
    "KOR": "KR",
    "KWT": "KW",
    "LBN": "LB",
    "LBY": "LY",
    "LTU": "LT",
    "LUX": "LU",
    "MAR": "MA",
    "MDG": "MG",
    "MEX": "MX",
    "MYS": "MY",
    "NGA": "NG",
    "NIC": "NI",
    "NLD": "NL",
    "NOR": "NO",
    "NPL": "NP",
    "NZL": "NZ",
    "PAK": "PK",
    "PAN": "PA",
    "PER": "PE",
    "PHL": "PH",
    "POL": "PL",
    "PRT": "PT",
    "ROU": "RO",
    "RUS": "RU",
    "SAU": "SA",
    "SDN": "SD",
    "SGP": "SG",
    "SLV": "SV",
    "SWE": "SE",
    "SYR": "SY",
    "TCD": "TD",
    "THA": "TH",
    "TUN": "TN",
    "TUR": "TR",
    "TWN": "TW",
    "UKR": "UA",
    "USA": "US",
    "VEN": "VE",
    "VNM": "VN",
    "YEM": "YE",
    "ZAF": "ZA",
    "ZWE": "ZW",
}


def iso3_to_iso2(iso3: str | None) -> str | None:
    if not iso3:
        return None
    return ISO3_TO_ISO2.get(iso3.upper())


def _alert_to_severity(alert: str | None) -> float | None:
    if alert is None:
        return None
    return _ALERT_LEVEL_SEVERITY.get(alert.lower())


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    text = element.text.strip()
    return text or None


#: GDACS quake severity text reads "Magnitude 6.9M, Depth:50.9km".
_DEPTH_RE: Final[re.Pattern[str]] = re.compile(r"Depth:\s*([\d.]+)\s*km", re.IGNORECASE)


def _parse_eq_magnitude_depth(
    severity_el: ET.Element | None, event_type: str
) -> tuple[float | None, float | None]:
    """Pull (magnitude, depth_km) from a GDACS earthquake severity element.

    Only earthquakes (``event_type == "EQ"``) carry a magnitude — for other
    hazards the severity ``value`` is wind speed, water level, etc., so we
    return ``(None, None)``. Magnitude comes from the ``value`` attribute
    (e.g. ``value="6.9"``); depth is parsed from the element text.
    """
    if severity_el is None or event_type != "EQ":
        return (None, None)
    magnitude: float | None = None
    value = severity_el.get("value")
    if value:
        try:
            parsed = float(value)
            magnitude = parsed if parsed > 0 else None
        except ValueError:
            magnitude = None
    depth_km: float | None = None
    if severity_el.text:
        match = _DEPTH_RE.search(severity_el.text)
        if match:
            try:
                depth_km = float(match.group(1))
            except ValueError:
                depth_km = None
    return (magnitude, depth_km)


def _parse_point(point_text: str | None) -> tuple[float | None, float | None]:
    if not point_text:
        return (None, None)
    parts = point_text.split()
    if len(parts) < 2:
        return (None, None)
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return (None, None)


def item_to_event(item: ET.Element, *, fetched_at: datetime) -> Event | None:
    """Convert a single RSS item to a canonical Event."""
    event_id = _text(item.find("gdacs:eventid", _NAMESPACES))
    event_type = _text(item.find("gdacs:eventtype", _NAMESPACES))
    alert_level = _text(item.find("gdacs:alertlevel", _NAMESPACES))
    severity = _alert_to_severity(alert_level)

    if not event_id or not event_type or severity is None:
        return None

    pub_date_raw = _text(item.find("pubDate"))
    occurred_at: datetime | None = None
    if pub_date_raw:
        # RSS uses RFC-822-style dates. Try a couple of common variants.
        for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                parsed = datetime.strptime(pub_date_raw, fmt)
                occurred_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                break
            except ValueError:
                continue
    if occurred_at is None:
        occurred_at = fetched_at

    iso3 = _text(item.find("gdacs:iso3", _NAMESPACES))
    country = iso3_to_iso2(iso3)
    lat, lon = _parse_point(_text(item.find("georss:point", _NAMESPACES)))

    severity_el = item.find("gdacs:severity", _NAMESPACES)
    magnitude, depth_km = _parse_eq_magnitude_depth(severity_el, event_type)

    payload = {
        "gdacs_event_id": event_id,
        "event_type": event_type,
        "alert_level": alert_level,
        "country_name": _text(item.find("gdacs:country", _NAMESPACES)),
        "iso3": iso3,
        "severity_raw": _text(severity_el),
        "magnitude": magnitude,
        "depth_km": depth_km,
        "from_date": _text(item.find("gdacs:fromdate", _NAMESPACES)),
        "to_date": _text(item.find("gdacs:todate", _NAMESPACES)),
        "link": _text(item.find("link")),
    }

    return Event(
        source="gdacs",
        source_event_id=f"{event_type}:{event_id}",
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.HAZARD,
        severity=severity,
        confidence=None,
        keywords=["gdacs", event_type.lower()],
        country=country,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_rss_body(body: str, *, fetched_at: datetime) -> list[Event]:
    """Parse a GDACS RSS feed body into Events. Never raises on bad XML."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    items = root.findall(".//item")
    events: list[Event] = []
    for item in items:
        event = item_to_event(item, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def feature_to_event_api(feature: dict[str, Any], *, fetched_at: datetime) -> Event | None:
    """Convert a GDACS geteventlist GeoJSON feature into a canonical Event.

    Keeps the same ``{eventtype}:{eventid}`` source id as the RSS path so the two
    feeds dedup against one another, but enriches the payload with the direct
    footprint ``geometry_url`` (correct episode baked in) used by the footprint
    enrichment, plus the GDACS report link and event name.
    """
    if not isinstance(feature, dict):
        return None
    props = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}

    event_type = props.get("eventtype")
    event_id = props.get("eventid")
    alert_level = props.get("alertlevel")
    severity = _alert_to_severity(alert_level)
    if not event_type or event_id is None or severity is None:
        return None

    coordinates = geometry.get("coordinates") or []
    lon: float | None = None
    lat: float | None = None
    if isinstance(coordinates, list) and len(coordinates) >= 2:
        try:
            lon = float(coordinates[0])
            lat = float(coordinates[1])
        except (TypeError, ValueError):
            lon = lat = None

    occurred_at = _parse_iso_datetime(props.get("fromdate")) or fetched_at
    iso3 = props.get("iso3")
    country = iso3_to_iso2(iso3)

    sev = props.get("severitydata") or {}
    severity_text = sev.get("severitytext") if isinstance(sev, dict) else None
    magnitude: float | None = None
    depth_km: float | None = None
    if event_type == "EQ" and isinstance(sev, dict):
        raw_mag = sev.get("severity")
        try:
            magnitude = float(raw_mag) if raw_mag is not None else None
        except (TypeError, ValueError):
            magnitude = None
        if severity_text:
            match = _DEPTH_RE.search(severity_text)
            if match:
                try:
                    depth_km = float(match.group(1))
                except ValueError:
                    depth_km = None

    url = props.get("url") if isinstance(props.get("url"), dict) else {}
    payload = {
        "gdacs_event_id": str(event_id),
        "event_type": event_type,
        "alert_level": alert_level,
        "country_name": props.get("country"),
        "iso3": iso3,
        "severity_raw": severity_text or None,
        "magnitude": magnitude,
        "depth_km": depth_km,
        "from_date": props.get("fromdate"),
        "to_date": props.get("todate"),
        "link": url.get("report"),
        "episodeid": props.get("episodeid"),
        "geometry_url": url.get("geometry"),
        "eventname": props.get("eventname"),
    }

    return Event(
        source="gdacs",
        source_event_id=f"{event_type}:{event_id}",
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.HAZARD,
        severity=severity,
        confidence=None,
        keywords=["gdacs", str(event_type).lower()],
        country=country,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_eventlist_json(body: str, *, fetched_at: datetime) -> list[Event]:
    """Parse a GDACS geteventlist JSON body into Events. Never raises on bad data."""
    try:
        document = json.loads(body)
    except json.JSONDecodeError:
        return []
    features = document.get("features") if isinstance(document, dict) else None
    if not isinstance(features, list):
        return []
    events: list[Event] = []
    for feature in features:
        event = feature_to_event_api(feature, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events


class GdacsFetcher(Fetcher):
    """GDACS multi-hazard fetcher (geteventlist API, per event type)."""

    name = "gdacs"
    queue = "slow"

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        merged: dict[str, Event] = {}
        with httpx.Client(
            timeout=self.timeout_seconds, headers={"User-Agent": GDACS_USER_AGENT}
        ) as client:
            for event_type in GDACS_API_EVENT_TYPES:
                try:
                    response = client.get(
                        GDACS_API_SEARCH_URL.format(eventlist=event_type)
                    )
                    response.raise_for_status()
                except httpx.HTTPError:
                    # One type failing must not lose the others.
                    continue
                for event in parse_eventlist_json(response.text, fetched_at=fetched_at):
                    merged[event.source_event_id] = event
        return list(merged.values())

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return f"/mnt/data/parquet/gdacs/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
