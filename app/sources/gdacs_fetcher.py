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

from datetime import UTC, datetime
from typing import Final
from xml.etree import ElementTree as ET

import httpx

from app.models import Category, Event
from app.sources.base import Fetcher

GDACS_FEED_URL: Final[str] = "https://www.gdacs.org/xml/rss.xml"
GDACS_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"

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

    payload = {
        "gdacs_event_id": event_id,
        "event_type": event_type,
        "alert_level": alert_level,
        "country_name": _text(item.find("gdacs:country", _NAMESPACES)),
        "iso3": iso3,
        "severity_raw": _text(item.find("gdacs:severity", _NAMESPACES)),
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


class GdacsFetcher(Fetcher):
    """GDACS multi-hazard RSS fetcher."""

    name = "gdacs"
    queue = "slow"

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        with httpx.Client(
            timeout=self.timeout_seconds, headers={"User-Agent": GDACS_USER_AGENT}
        ) as client:
            response = client.get(GDACS_FEED_URL)
            response.raise_for_status()
            return parse_rss_body(response.text, fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return f"/mnt/data/parquet/gdacs/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
