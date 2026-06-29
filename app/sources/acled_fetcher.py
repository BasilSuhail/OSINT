"""ACLED conflict/event ingest.

Primary path is manual CSV import from myACLED / ACLED data downloads. API
access is opt-in because many valid myACLED accounts authenticate but receive
``403 Access denied`` for the data API.
"""

from __future__ import annotations

import csv
import glob
import hashlib
import math
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx
import pandas as pd

from app.enrichment.country import country_for
from app.enrichment.country_codes import country_centroid, country_name_to_iso2, iso3_to_iso2
from app.models import Category, Event
from app.settings import settings
from app.sources.base import Fetcher

ACLED_API_URL: Final[str] = "https://acleddata.com/api/acled/read"
ACLED_TOKEN_URL: Final[str] = "https://acleddata.com/oauth/token"
ACLED_USER_AGENT: Final[str] = "OSINT-thesis-project/0.0.1 (academic)"
_LOCAL_EXTENSIONS: Final[tuple[str, ...]] = (".csv", ".xlsx")

_EVENT_TYPE_SEVERITY: Final[dict[str, float]] = {
    "battles": 0.9,
    "explosions/remote violence": 0.85,
    "violence against civilians": 0.8,
    "riots": 0.65,
    "protests": 0.45,
    "strategic developments": 0.35,
}

_AGGREGATE_VALUE_FIELDS: Final[tuple[str, ...]] = (
    "events",
    "event_count",
    "number_of_events",
    "number_of_political_violence_events",
    "political_violence_events",
    "demonstration_events",
    "events_targeting_civilians",
    "fatalities",
    "reported_fatalities",
    "civilian_fatalities",
    "count",
    "value",
    "total",
)


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def _field_map(record: dict[str, Any]) -> dict[str, Any]:
    return {_normalize_key(str(key)): value for key, value in record.items()}


def _first(record: dict[str, Any], *names: str) -> Any:
    fields = _field_map(record)
    for name in names:
        value = fields.get(_normalize_key(name))
        if value not in (None, ""):
            return value
    return None


def _first_text(record: dict[str, Any], *names: str) -> str | None:
    value = _first(record, *names)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_float(raw: Any) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _parse_int(raw: Any) -> int | None:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _parse_date(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    if hasattr(raw, "to_pydatetime"):
        value = raw.to_pydatetime()
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except ValueError:
        parsed = None
    if parsed is not None:
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _json_safe_value(value.item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(key): _json_safe_value(raw) for key, raw in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    return value


def _parse_aggregate_date(record: dict[str, Any]) -> datetime | None:
    raw_date = _first(record, "event_date", "date", "week", "month_year", "period")
    parsed = _parse_date(raw_date)
    if parsed is not None:
        return parsed

    year = _parse_int(_first(record, "year"))
    if year is None or year < 1900:
        return None
    month = _parse_int(_first(record, "month"))
    if month is None:
        month = 1
    if month < 1 or month > 12:
        return None
    return datetime(year, month, 1, tzinfo=UTC)


def _severity(record: dict[str, Any]) -> float:
    fatalities = _parse_int(_first(record, "fatalities")) or 0
    event_type = str(_first(record, "event_type") or "").strip().lower()
    base = _EVENT_TYPE_SEVERITY.get(event_type, 0.5)
    fatality_bump = min(0.2, fatalities / 50.0)
    return max(0.0, min(1.0, base + fatality_bump))


def record_to_event(record: dict[str, Any], *, fetched_at: datetime) -> Event | None:
    """Convert one ACLED API record to a canonical Event."""
    event_id = str(
        _first(record, "event_id_cnty", "event_id_no_cnty", "event_id", "data_id") or ""
    ).strip()
    if not event_id:
        return None
    occurred_at = _parse_date(_first(record, "event_date", "date"))
    if occurred_at is None:
        return None

    lat = _parse_float(_first(record, "latitude", "lat"))
    lon = _parse_float(_first(record, "longitude", "lon", "lng"))
    country = iso3_to_iso2(str(_first(record, "iso3", "iso") or "").strip() or None)
    if country is None:
        country = country_name_to_iso2(_first_text(record, "country", "admin0"))
    if country is None and lat is not None and lon is not None:
        country = country_for(lat, lon)

    event_type = _first_text(record, "event_type")
    sub_event_type = _first_text(record, "sub_event_type")
    actor1 = _first_text(record, "actor1")
    actor2 = _first_text(record, "actor2")
    fatalities = _parse_int(_first(record, "fatalities"))
    location = _first_text(record, "location")

    payload = {
        "event_id_cnty": _first(record, "event_id_cnty"),
        "event_id_no_cnty": _first(record, "event_id_no_cnty"),
        "event_date": _first(record, "event_date", "date"),
        "year": _first(record, "year"),
        "event_type": event_type,
        "sub_event_type": sub_event_type,
        "actor1": actor1,
        "actor2": actor2,
        "fatalities": fatalities,
        "location": location,
        "admin1": _first(record, "admin1"),
        "admin2": _first(record, "admin2"),
        "admin3": _first(record, "admin3"),
        "source": _first(record, "source"),
        "source_scale": _first(record, "source_scale"),
        "notes": _first(record, "notes"),
        "iso3": _first(record, "iso3"),
    }

    keywords = ["acled", "conflict"]
    if event_type:
        keywords.append(event_type.lower())
    if sub_event_type:
        keywords.append(sub_event_type.lower())

    return Event(
        source="acled",
        source_event_id=event_id,
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.GEOPOLITICAL,
        severity=_severity(record),
        confidence=None,
        keywords=keywords,
        country=country,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def _aggregate_metric(record: dict[str, Any]) -> tuple[str, float] | None:
    fields = _field_map(record)
    for field in _AGGREGATE_VALUE_FIELDS:
        value = _parse_float(fields.get(field))
        if value is not None:
            return field, value

    ignored = {"year", "month", "iso", "iso2", "iso3", "country", "region"}
    for field, raw_value in fields.items():
        if field in ignored or field.endswith("_year"):
            continue
        value = _parse_float(raw_value)
        if value is not None:
            return field, value
    return None


def _aggregate_severity(metric_name: str, metric_value: float) -> float:
    scale = 100.0 if "fatal" in metric_name else 1000.0
    return max(0.05, min(1.0, math.log1p(max(metric_value, 0.0)) / math.log1p(scale)))


def aggregate_record_to_event(
    record: dict[str, Any], *, fetched_at: datetime, source_name: str = "acled-aggregate"
) -> Event | None:
    """Convert ACLED country aggregate rows to country-level map events."""
    occurred_at = _parse_aggregate_date(record)
    if occurred_at is None:
        return None

    country = iso3_to_iso2(_first_text(record, "iso3", "iso"))
    if country is None:
        iso2 = _first_text(record, "iso2", "country_code")
        if iso2 and len(iso2) == 2:
            country = iso2.upper()
    country_name = _first_text(record, "country", "admin0", "location")
    if country is None:
        country = country_name_to_iso2(country_name)
    if country is None:
        return None

    metric = _aggregate_metric(record)
    if metric is None:
        return None
    metric_name, metric_value = metric

    centroid = country_centroid(country)
    lat = lon = None
    if centroid is not None:
        lat, lon = centroid
    explicit_lat = _parse_float(_first(record, "centroid_latitude", "latitude", "lat"))
    explicit_lon = _parse_float(_first(record, "centroid_longitude", "longitude", "lon", "lng"))
    if explicit_lat is not None and explicit_lon is not None:
        lat = explicit_lat
        lon = explicit_lon

    stable = "|".join(
        [source_name, country, occurred_at.date().isoformat(), metric_name, str(metric_value)]
    )
    source_event_id = "aggregate-" + hashlib.sha1(stable.encode("utf-8")).hexdigest()[:24]
    keywords = ["acled", "conflict", "aggregate", metric_name]

    return Event(
        source="acled",
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.GEOPOLITICAL,
        severity=_aggregate_severity(metric_name, metric_value),
        confidence=None,
        keywords=keywords,
        country=country,
        lat=lat,
        lon=lon,
        payload={
            "aggregate": True,
            "source_name": source_name,
            "country": country_name,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "year": _first(record, "year"),
            "month": _first(record, "month"),
            "raw": _json_safe_value(dict(record)),
        },
    )


def parse_acled_response(body: dict[str, Any], *, fetched_at: datetime) -> list[Event]:
    records = body.get("data") or []
    if not isinstance(records, list):
        return []
    events: list[Event] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        event = record_to_event(record, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events


def parse_acled_csv(
    body: str, *, fetched_at: datetime, source_name: str = "acled-csv"
) -> list[Event]:
    return _records_to_events(
        csv.DictReader(body.splitlines()),
        fetched_at=fetched_at,
        source_name=source_name,
    )


def parse_acled_excel(
    path: Path, *, fetched_at: datetime, source_name: str = "acled-excel"
) -> list[Event]:
    sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    events: list[Event] = []
    for sheet_name, frame in sheets.items():
        frame = frame.dropna(how="all")
        if frame.empty:
            continue
        frame = frame.where(pd.notna(frame), None)
        records = frame.to_dict(orient="records")
        events.extend(
            _records_to_events(
                records,
                fetched_at=fetched_at,
                source_name=f"{source_name}:{sheet_name}",
            )
        )
    return events


def parse_acled_file(path: Path, *, fetched_at: datetime) -> list[Event]:
    if path.suffix.lower() == ".csv":
        return parse_acled_csv(
            path.read_text(encoding="utf-8-sig"),
            fetched_at=fetched_at,
            source_name=path.name,
        )
    if path.suffix.lower() == ".xlsx":
        return parse_acled_excel(path, fetched_at=fetched_at, source_name=path.name)
    return []


def _local_paths() -> list[Path]:
    paths: list[Path] = []
    if settings.acled_csv_path:
        paths.append(Path(settings.acled_csv_path).expanduser())
    if settings.acled_csv_dir:
        root = Path(settings.acled_csv_dir).expanduser()
        for extension in _LOCAL_EXTENSIONS:
            pattern = str(root / f"*{extension}")
            paths.extend(Path(p) for p in glob.glob(pattern))
    return sorted(set(paths))


def _records_to_events(
    records: Iterable[dict[str, Any]], *, fetched_at: datetime, source_name: str
) -> list[Event]:
    events: list[Event] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        event = record_to_event(record, fetched_at=fetched_at)
        if event is None:
            event = aggregate_record_to_event(
                record,
                fetched_at=fetched_at,
                source_name=source_name,
            )
        if event is not None:
            events.append(event)
    return events


def parse_acled_csv(
    body: str, *, fetched_at: datetime, source_name: str = "acled-csv"
) -> list[Event]:
    return _records_to_events(
        csv.DictReader(body.splitlines()),
        fetched_at=fetched_at,
        source_name=source_name,
    )


def parse_acled_excel(
    path: Path, *, fetched_at: datetime, source_name: str = "acled-excel"
) -> list[Event]:
    sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    events: list[Event] = []
    for sheet_name, frame in sheets.items():
        frame = frame.dropna(how="all")
        if frame.empty:
            continue
        frame = frame.where(pd.notna(frame), None)
        records = frame.to_dict(orient="records")
        events.extend(
            _records_to_events(
                records,
                fetched_at=fetched_at,
                source_name=f"{source_name}:{sheet_name}",
            )
        )
    return events


def parse_acled_file(path: Path, *, fetched_at: datetime) -> list[Event]:
    if path.suffix.lower() == ".csv":
        return parse_acled_csv(
            path.read_text(encoding="utf-8-sig"),
            fetched_at=fetched_at,
            source_name=path.name,
        )
    if path.suffix.lower() == ".xlsx":
        return parse_acled_excel(path, fetched_at=fetched_at, source_name=path.name)
    return []


def _local_paths() -> list[Path]:
    paths: list[Path] = []
    if settings.acled_csv_path:
        paths.append(Path(settings.acled_csv_path).expanduser())
    if settings.acled_csv_dir:
        root = Path(settings.acled_csv_dir).expanduser()
        for extension in _LOCAL_EXTENSIONS:
            pattern = str(root / f"*{extension}")
            paths.extend(Path(p) for p in glob.glob(pattern))
    return sorted(set(paths))


def _recent(events: Iterable[Event], *, since: datetime, limit: int) -> list[Event]:
    filtered = [event for event in events if event.occurred_at >= since]
    filtered.sort(key=lambda event: event.occurred_at, reverse=True)
    return filtered[:limit]


class AcledFetcher(Fetcher):
    name = "acled"
    queue = "slow"

    def __init__(self, *, lookback_days: int = 30, limit: int = 500, timeout_seconds: float = 30.0):
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        if limit <= 0:
            raise ValueError("limit must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.lookback_days = lookback_days
        self.limit = limit
        self.timeout_seconds = timeout_seconds

    def fetch(self) -> list[Event]:
        fetched_at = datetime.now(UTC)
        csv_events = self._fetch_csv(fetched_at=fetched_at)
        if csv_events:
            return csv_events
        if not settings.acled_api_enabled:
            return []
        if not settings.acled_username or not settings.acled_password:
            return []
        return self._fetch_api(fetched_at=fetched_at)

    def _fetch_csv(self, *, fetched_at: datetime) -> list[Event]:
        paths = [path for path in _local_paths() if path.exists()]
        if not paths:
            return []
        all_events: list[Event] = []
        for path in paths:
            all_events.extend(parse_acled_file(path, fetched_at=fetched_at))
        since = fetched_at - timedelta(days=self.lookback_days)
        return _recent(all_events, since=since, limit=self.limit)

    def _fetch_api(self, *, fetched_at: datetime) -> list[Event]:
        event_date = (fetched_at - timedelta(days=self.lookback_days)).date().isoformat()
        params = {
            "event_date": event_date,
            "event_date_where": ">=",
            "limit": str(self.limit),
            "format": "json",
        }
        with httpx.Client(
            timeout=self.timeout_seconds,
            headers={"User-Agent": ACLED_USER_AGENT, "Accept": "application/json"},
        ) as client:
            token = self._access_token(client)
            response = client.get(
                ACLED_API_URL,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            return parse_acled_response(response.json(), fetched_at=fetched_at)

    def _access_token(self, client: httpx.Client) -> str:
        response = client.post(
            ACLED_TOKEN_URL,
            data={
                "username": settings.acled_username,
                "password": settings.acled_password,
                "grant_type": "password",
                "client_id": "acled",
                "scope": "authenticated",
            },
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError("ACLED OAuth response did not include access_token")
        return token

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return f"/mnt/data/parquet/acled/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
