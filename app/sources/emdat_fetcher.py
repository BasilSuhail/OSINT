"""EM-DAT disaster CSV importer.

EM-DAT is best treated as disaster ground truth/backfill rather than a live
alert stream. This fetcher reads a local CSV export path from ``EMDAT_CSV_PATH``
and emits canonical hazard events. Without a path it is a no-op.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.enrichment.country_codes import iso3_to_iso2
from app.models import Category, Event
from app.settings import settings
from app.sources.base import Fetcher

_SEVERITY_BY_TYPE: Final[dict[str, float]] = {
    "earthquake": 0.8,
    "flood": 0.65,
    "storm": 0.65,
    "drought": 0.55,
    "wildfire": 0.6,
    "volcanic activity": 0.7,
    "extreme temperature": 0.55,
}


def _first(row: dict[str, str], *names: str) -> str | None:
    lowered = {k.strip().lower(): v for k, v in row.items()}
    for name in names:
        value = lowered.get(name.strip().lower())
        if value is not None and value.strip():
            return value.strip()
    return None


def _parse_int(raw: str | None) -> int | None:
    if not raw:
        return None
    cleaned = raw.replace(",", "").strip()
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _parse_float(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        return None


def _date_from_parts(year: str | None, month: str | None, day: str | None) -> datetime | None:
    y = _parse_int(year)
    if y is None:
        return None
    m = _parse_int(month) or 1
    d = _parse_int(day) or 1
    try:
        return datetime(y, max(1, min(12, m)), max(1, min(28, d)), tzinfo=UTC)
    except ValueError:
        return None


def _severity(row: dict[str, str]) -> float:
    disaster_type = (_first(row, "Disaster Type", "Disaster Subtype") or "").lower()
    base = _SEVERITY_BY_TYPE.get(disaster_type, 0.5)
    deaths = _parse_int(_first(row, "Total Deaths", "No. Injured")) or 0
    affected = _parse_int(_first(row, "Total Affected", "No. Affected")) or 0
    death_bump = min(0.25, deaths / 10_000)
    affected_bump = min(0.2, affected / 1_000_000)
    return max(0.0, min(1.0, base + death_bump + affected_bump))


def row_to_event(row: dict[str, str], *, fetched_at: datetime) -> Event | None:
    dis_no = _first(row, "DisNo.", "Dis No", "Disaster No.", "Disaster No")
    if not dis_no:
        return None
    occurred_at = _date_from_parts(
        _first(row, "Start Year", "Year"),
        _first(row, "Start Month", "Month"),
        _first(row, "Start Day", "Day"),
    )
    if occurred_at is None:
        return None

    iso3 = _first(row, "ISO", "ISO3", "Country ISO")
    country = iso3_to_iso2(iso3)
    lat = _parse_float(_first(row, "Latitude", "Lat"))
    lon = _parse_float(_first(row, "Longitude", "Lon", "Lng"))

    disaster_type = _first(row, "Disaster Type")
    subtype = _first(row, "Disaster Subtype")
    country_name = _first(row, "Country")
    deaths = _parse_int(_first(row, "Total Deaths"))
    affected = _parse_int(_first(row, "Total Affected", "No. Affected"))
    damages = _parse_int(
        _first(row, "Total Damages ('000 US$)", "Total Damages, Adjusted ('000 US$)")
    )

    payload: dict[str, Any] = {
        "dis_no": dis_no,
        "country_name": country_name,
        "iso3": iso3,
        "disaster_type": disaster_type,
        "disaster_subtype": subtype,
        "event_name": _first(row, "Event Name"),
        "total_deaths": deaths,
        "total_affected": affected,
        "total_damages_000_usd": damages,
        "start_year": _first(row, "Start Year", "Year"),
        "start_month": _first(row, "Start Month", "Month"),
        "start_day": _first(row, "Start Day", "Day"),
    }

    keywords = ["emdat", "disaster"]
    if disaster_type:
        keywords.append(disaster_type.lower())
    if subtype:
        keywords.append(subtype.lower())

    return Event(
        source="emdat",
        source_event_id=dis_no,
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.HAZARD,
        severity=_severity(row),
        confidence=None,
        keywords=keywords,
        country=country,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_emdat_csv(body: str, *, fetched_at: datetime) -> list[Event]:
    reader = csv.DictReader(body.splitlines())
    events: list[Event] = []
    for row in reader:
        event = row_to_event(row, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events


class EmdatFetcher(Fetcher):
    name = "emdat"
    queue = "slow"

    def fetch(self) -> list[Event]:
        if not settings.emdat_csv_path:
            return []
        path = Path(settings.emdat_csv_path).expanduser()
        if not path.exists():
            return []
        return parse_emdat_csv(path.read_text(encoding="utf-8-sig"), fetched_at=datetime.now(UTC))

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return f"/mnt/data/parquet/emdat/year={now.year}/month={now.month:02d}/"
