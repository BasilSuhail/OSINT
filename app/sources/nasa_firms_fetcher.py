"""Module C — Hazards: NASA FIRMS active-fire CSV via the area API.

Pulls VIIRS_SNPP_NRT global daily active-fire hotspots via the FIRMS area API.
The API requires a free MAP_KEY (`FIRMS_MAP_KEY`); when unset, fetch() is a
no-op so local dev does not surface upstream-credential errors.

VIIRS_SNPP_NRT confidence is a text value (low / nominal / high). MODIS feeds
publish numeric 0..100 confidence; both shapes are accepted here so the fetcher
can switch upstream products without code changes.

Severity comes from `frp` (fire radiative power, MW), not from confidence
(#579). Confidence answers "is this pixel fire at all"; severity is read
downstream as "how bad is this". The two ran non-monotonic on live data —
`l` pixels average roughly twice the FRP of `n` pixels — so a high-confidence
small fire outranked a low-confidence large one.

A row with no readable `frp` gets no severity, deliberately: falling back to
confidence would silently restore the wrong quantity, and the whole cost of
#574 was a wrong-but-plausible number that nothing surfaced. If a future FIRMS
product drops the column the resweep's `unreadable_rows` count says so out
loud.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx

from app.enrichment.country import country_for
from app.models import Category, Event
from app.settings import settings
from app.severity import scale
from app.sources.base import Fetcher, SourceMisconfiguredError

FIRMS_URL_TEMPLATE: Final[str] = (
    "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{map_key}/VIIRS_SNPP_NRT/world/1/{date}"
)
FIRMS_USER_AGENT: Final[str] = "OSINT-project/0.0.1 (academic)"

#: VIIRS reports confidence as a single letter, MODIS as 0-100, and the words
#: appear in some exports. Only the words were mapped, so `float("n")` raised
#: and every VIIRS row was stored with severity NULL — 536,097 of them, which
#: the composite then skipped entirely (#574). The value was read and kept in
#: `payload.confidence_raw` the whole time, which is why the gap was invisible
#: at every layer except the one that used it.
_TEXT_CONFIDENCE_QUALITY: Final[dict[str, float]] = {
    "low": 0.2,
    "l": 0.2,
    "nominal": 0.5,
    "n": 0.5,
    "high": 0.9,
    "h": 0.9,
}

#: FRP, in MW, that maps to the top of the severity range. 1488.19 is the
#: largest value across the 536,097 stored rows; 1500 rounds it off so the
#: reference is a stated constant rather than a high-water mark that shifts
#: every time a bigger fire is observed.
#:
#: Global, not per-country, and that is not a convenience. Composite
#: normalisation already applies a rolling per-country z-score
#: (`app.composite.normalization.normalize_domain_signals`), so scaling within
#: country here would apply the country frame twice and destroy the
#: cross-country comparability the composite is built on.
FRP_REFERENCE_MW: Final[float] = 1500.0

#: The highest severity a bare fire detection may claim. `scale.LETHAL_FLOOR`
#: means "confirmed deaths"; FIRMS sees a hot pixel and knows nothing about
#: casualties, so it must stay below that floor no matter how large the fire.
#:
#: This also fixes an aggregation bug. Hazard signals are combined with `max`
#: over the country-month (#574), so the old 0.90 mapping put an ordinary fire
#: pixel above every USGS and GDACS row it shared a bucket with — 55% of
#: country-months pinned at exactly 0.90 (#580). Capped here, a confirmed
#: fatality event always outranks a detection.
#:
#: Rounded because binary floats make `0.60 - 0.05` land at 0.5499999999999999,
#: and a ceiling that a value can exceed by 1e-16 is not a ceiling.
FRP_SEVERITY_CEILING: Final[float] = round(scale.LETHAL_FLOOR - 0.05, 6)


def confidence_quality(raw: str | None) -> float | None:
    """Read a raw FIRMS confidence as 0..1 detection quality, None if unreadable.

    Not a severity (#579). This is the instrument's certainty that the pixel is
    fire at all, and it is used as a readability gate: an unrecognised encoding
    returns None so a future FIRMS change fails loudly at the boundary instead
    of quietly becoming "no fire happened", which is precisely how #574 hid
    536,097 null severities for the life of the source.

    It deliberately does *not* filter `l` pixels out. On the stored data `l`
    detections average 18.27 MW against 8.91 MW for `n` — dropping them would
    throw away larger fires than it kept.
    """
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned:
        return None
    if cleaned in _TEXT_CONFIDENCE_QUALITY:
        return _TEXT_CONFIDENCE_QUALITY[cleaned]
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return max(0.0, min(value / 100.0, 1.0))


def frp_to_severity(raw_frp: str | float | None, *, confidence_raw: str | None) -> float | None:
    """Map fire radiative power (MW) to severity, or None if it cannot be read.

    Log-scaled. FRP spans 2.4 decades on the stored rows (p50 5.37, p99 105.69,
    max 1488.19), so a linear map pins essentially everything at zero and
    resolves nothing where almost all of the data lives. On the log curve the
    median pixel reads 0.139, p99 reads 0.351 and the largest fire observed
    reads 0.549.

    A fixed reference rather than a percentile rank of the current corpus:
    percentile makes the value depend on which other rows happen to be loaded,
    so the same fire would score differently between a fetch and a resweep.

    Returns None when confidence is unreadable — that signals the upstream
    encoding changed, and nothing derived from that row should be trusted.
    """
    if confidence_quality(confidence_raw) is None:
        return None
    if raw_frp is None:
        return None
    try:
        frp = float(raw_frp)
    except (TypeError, ValueError):
        return None
    if frp != frp or frp == float("inf") or frp < 0.0:  # NaN, inf, negative
        return None
    scaled = math.log10(1.0 + frp) / math.log10(1.0 + FRP_REFERENCE_MW)
    return round(max(0.0, min(scaled, 1.0)) * FRP_SEVERITY_CEILING, 6)


def hash_event_id(lat: str, lon: str, acq_date: str, acq_time: str, satellite: str) -> str:
    payload = f"{lat}|{lon}|{acq_date}|{acq_time}|{satellite}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_acq_time(acq_date: str, acq_time: str) -> datetime | None:
    """Combine FIRMS acq_date (YYYY-MM-DD) and acq_time (HHMM) into UTC datetime."""
    try:
        time_str = acq_time.zfill(4)
        hour = int(time_str[:2])
        minute = int(time_str[2:])
        date = datetime.strptime(acq_date, "%Y-%m-%d")
        return date.replace(hour=hour, minute=minute, tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def row_to_event(row: dict[str, str], *, fetched_at: datetime) -> Event | None:
    """Convert a FIRMS CSV row (already parsed into a dict) to an Event."""
    lat_raw = row.get("latitude", "")
    lon_raw = row.get("longitude", "")
    acq_date = row.get("acq_date", "")
    acq_time = row.get("acq_time", "")
    satellite = row.get("satellite", "")
    confidence_raw = row.get("confidence")

    if not lat_raw or not lon_raw or not acq_date or not acq_time:
        return None

    try:
        lat = float(lat_raw)
        lon = float(lon_raw)
    except ValueError:
        return None

    occurred_at = _parse_acq_time(acq_date, acq_time)
    if occurred_at is None:
        return None

    frp_raw = row.get("frp")
    severity = frp_to_severity(frp_raw, confidence_raw=confidence_raw)
    # Deterministic reason (#591), and it now names the quantity actually
    # measured: radiative power in MW, capped below the lethal floor because a
    # detection knows nothing about casualties (#579).
    verdict = (
        scale.Verdict(
            value=severity,
            rationale=(
                f"fire radiative power {frp_raw} MW, log-scaled against "
                f"{FRP_REFERENCE_MW:.0f} MW and capped at {FRP_SEVERITY_CEILING} — "
                f"a detection cannot claim confirmed deaths (confidence {confidence_raw!r} "
                f"read as quality only)"
            ),
            method="firms-frp-v1",
        )
        if severity is not None
        else None
    )

    source_event_id = hash_event_id(lat_raw, lon_raw, acq_date, acq_time, satellite)

    payload: dict[str, Any] = {
        "acq_date": acq_date,
        "acq_time": acq_time,
        "satellite": satellite,
        "instrument": row.get("instrument"),
        "confidence_raw": confidence_raw,
        **(verdict.as_payload() if verdict is not None else {}),
        "brightness": row.get("brightness"),
        "bright_t31": row.get("bright_t31"),
        "frp": row.get("frp"),
        "daynight": row.get("daynight"),
    }

    country = country_for(lat, lon) if lat is not None and lon is not None else None

    return Event(
        source="nasa-firms",
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        fetched_at=fetched_at,
        category=Category.HAZARD,
        severity=severity,
        confidence=None,
        keywords=["firms", "fire"],
        country=country,
        lat=lat,
        lon=lon,
        payload=payload,
    )


def parse_csv_body(body: str, *, fetched_at: datetime) -> list[Event]:
    """Parse the FIRMS CSV body into Events. Never raises on malformed rows."""
    if not body.strip():
        return []
    reader = csv.DictReader(io.StringIO(body))
    events: list[Event] = []
    for row in reader:
        event = row_to_event(row, fetched_at=fetched_at)
        if event is not None:
            events.append(event)
    return events


class NasaFirmsFetcher(Fetcher):
    """NASA FIRMS active-fire fetcher."""

    name = "nasa-firms"
    queue = "slow"

    def __init__(self, *, timeout_seconds: float = 60.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds

    def _target_date(self) -> str:
        # FIRMS publishes near-real-time data. Use the prior UTC day so the
        # CSV is reliably populated when we poll.
        return (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    def fetch(self) -> list[Event]:
        if not settings.firms_map_key:
            raise SourceMisconfiguredError("FIRMS_MAP_KEY is not configured")
        fetched_at = datetime.now(UTC)
        url = FIRMS_URL_TEMPLATE.format(map_key=settings.firms_map_key, date=self._target_date())
        with httpx.Client(
            timeout=self.timeout_seconds, headers={"User-Agent": FIRMS_USER_AGENT}
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            return parse_csv_body(response.text, fetched_at=fetched_at)

    def archive_path(self) -> str:
        now = datetime.now(UTC)
        return (
            f"/mnt/data/parquet/nasa-firms/year={now.year}/month={now.month:02d}/day={now.day:02d}/"
        )
