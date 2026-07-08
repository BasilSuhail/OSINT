"""GDELT 1.0 historical geopolitical signal — daily event files → monthly means.

Pre-registered signal (docs/methodology.md, baseline B3 "GDELT Goldstein"):
for each (country, month), the mean GoldsteinScale across every GDELT event
geolocated to that country (ActionGeo, FIPS 10-4 → ISO2), inverted and
rescaled to a [0, 1] severity where 1 is maximal conflict:

    severity = (10 - goldstein) / 20

No mention-weighting, no volume thresholds — zero tuning knobs. Events are
bucketed by SQLDATE (the event date, not the publication date); GDELT's
anniversary-mention artifact (old events resurfacing in recent files) is
clipped away by restricting SQLDATE to the requested window.

The download is large (~4,000 daily zips for 2014-2024), so aggregation is
checkpointed per month under `$OSINT_DATA_DIR/gdelt/` — a stopped run resumes
where it left off and a completed cache makes re-runs free. Known GDELT
gap-days (HTTP 404) are tolerated and recorded in the checkpoint; transient
errors retry, then fail the month loudly rather than write a partial one.
"""

from __future__ import annotations

import json
import os
import time
import zipfile
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from app.composite.fips import FIPS_TO_ISO2

GDELT_URL_TEMPLATE = "http://data.gdeltproject.org/events/{yyyymmdd}.export.CSV.zip"

#: GDELT 1.0 daily export column positions (58 tab-separated fields).
COL_SQLDATE = 1
COL_GOLDSTEIN = 30
COL_ACTIONGEO_COUNTRY = 51
MIN_COLUMNS = 52  # enough to read every column above

DOWNLOAD_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5.0

#: (url) -> zip bytes, or None for a known gap-day (HTTP 404).
DownloadFn = Callable[[str], bytes | None]


def default_cache_dir() -> Path:
    return Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "gdelt"


def iter_months(start: date, end: date) -> Iterator[date]:
    """First-of-month dates covering [start, end]."""
    if end < start:
        raise ValueError("end must not precede start")
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        yield cursor
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )


def month_days(month_start: date) -> list[date]:
    """Every calendar day of the given month."""
    days = []
    cursor = month_start
    while cursor.month == month_start.month:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def goldstein_to_severity(goldstein: float) -> float:
    """Invert and rescale GoldsteinScale [-10, 10] → severity [0, 1]."""
    severity = (10.0 - goldstein) / 20.0
    return min(1.0, max(0.0, severity))


def parse_export_csv(
    raw: bytes, *, window_start: date, window_end: date
) -> tuple[dict[tuple[str, str], tuple[float, int]], int]:
    """One day's decompressed CSV → {(iso2, "YYYY-MM"): (goldstein_sum, n)}.

    Returns the aggregate plus the count of rows whose ActionGeo country had
    no ISO2 mapping (oceans, disputed rocks — recorded for provenance).
    Malformed rows are skipped: this is telemetry-grade bulk data.
    """
    sums: dict[tuple[str, str], tuple[float, int]] = {}
    unmapped = 0
    for line in raw.decode("utf-8", errors="replace").splitlines():
        cols = line.split("\t")
        if len(cols) < MIN_COLUMNS:
            continue
        fips = cols[COL_ACTIONGEO_COUNTRY]
        if not fips:
            continue
        iso2 = FIPS_TO_ISO2.get(fips)
        if iso2 is None:
            unmapped += 1
            continue
        sqldate = cols[COL_SQLDATE]
        if len(sqldate) != 8 or not sqldate.isdigit():
            continue
        try:
            event_date = date(int(sqldate[:4]), int(sqldate[4:6]), int(sqldate[6:8]))
            goldstein = float(cols[COL_GOLDSTEIN])
        except ValueError:
            continue
        if not (window_start <= event_date <= window_end):
            continue
        key = (iso2, f"{event_date.year:04d}-{event_date.month:02d}")
        current_sum, current_n = sums.get(key, (0.0, 0))
        sums[key] = (current_sum + goldstein, current_n + 1)
    return sums, unmapped


def unzip_export(payload: bytes) -> bytes:
    """A daily zip holds exactly one CSV member; return its bytes."""
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        names = archive.namelist()
        if not names:
            raise ValueError("empty GDELT zip archive")
        return archive.read(names[0])


def download_day(url: str, *, client: httpx.Client) -> bytes | None:
    """Fetch one daily zip. 404 → None (known GDELT gap); retries then raises."""
    last_error: Exception | None = None
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            response = client.get(url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as error:
            last_error = error
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise RuntimeError(f"GDELT download failed after {DOWNLOAD_RETRIES} attempts: {url}") from (
        last_error
    )


def _checkpoint_path(cache_dir: Path, month_start: date) -> Path:
    return cache_dir / f"gdelt-{month_start.year:04d}-{month_start.month:02d}.json"


def build_month_checkpoint(
    month_start: date,
    *,
    window_start: date,
    window_end: date,
    download: DownloadFn,
) -> dict[str, Any]:
    """Download and aggregate one month of daily files into checkpoint shape.

    Checkpoint JSON: {"days_ok", "days_missing": [...], "unmapped_rows",
    "countries": {"ISO2:YYYY-MM": [goldstein_sum, n]}}. Keys carry the event
    month (SQLDATE), which is usually — not always — the file's own month.
    """
    totals: dict[tuple[str, str], tuple[float, int]] = {}
    days_ok = 0
    days_missing: list[str] = []
    unmapped_rows = 0
    for day in month_days(month_start):
        url = GDELT_URL_TEMPLATE.format(yyyymmdd=f"{day.year:04d}{day.month:02d}{day.day:02d}")
        payload = download(url)
        if payload is None:
            days_missing.append(day.isoformat())
            continue
        day_sums, unmapped = parse_export_csv(
            unzip_export(payload), window_start=window_start, window_end=window_end
        )
        unmapped_rows += unmapped
        days_ok += 1
        for key, (goldstein_sum, n) in day_sums.items():
            current_sum, current_n = totals.get(key, (0.0, 0))
            totals[key] = (current_sum + goldstein_sum, current_n + n)
    return {
        "days_ok": days_ok,
        "days_missing": days_missing,
        "unmapped_rows": unmapped_rows,
        "countries": {f"{iso2}:{month}": [s, n] for (iso2, month), (s, n) in totals.items()},
    }


def load_or_build_month(
    month_start: date,
    *,
    cache_dir: Path,
    window_start: date,
    window_end: date,
    download: DownloadFn,
) -> dict[str, Any]:
    """Return the month's checkpoint, building and persisting it if absent."""
    path = _checkpoint_path(cache_dir, month_start)
    if path.exists():
        return json.loads(path.read_text())
    checkpoint = build_month_checkpoint(
        month_start, window_start=window_start, window_end=window_end, download=download
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(checkpoint))
    tmp.replace(path)
    return checkpoint


def fetch_gdelt_history(
    start: date,
    end: date,
    *,
    cache_dir: Path | None = None,
    download: DownloadFn | None = None,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Monthly mean Goldstein per country → synthetic geopolitical event dicts.

    One event per (country, month): the aggregation layer's mean-severity of a
    single event is exactly the monthly mean, so the live pipeline reproduces
    the pre-registered signal without special-casing.
    """
    cache_dir = cache_dir if cache_dir is not None else default_cache_dir()

    owned_client: httpx.Client | None = None
    if download is None:
        owned_client = httpx.Client(timeout=120.0, follow_redirects=True)
        client = owned_client
        download = lambda url: download_day(url, client=client)  # noqa: E731

    totals: dict[tuple[str, str], tuple[float, int]] = {}
    months = list(iter_months(start, end))
    try:
        for index, month_start in enumerate(months, start=1):
            checkpoint = load_or_build_month(
                month_start,
                cache_dir=cache_dir,
                window_start=start,
                window_end=end,
                download=download,
            )
            for key, (goldstein_sum, n) in checkpoint["countries"].items():
                iso2, month = key.split(":")
                current_sum, current_n = totals.get((iso2, month), (0.0, 0))
                totals[(iso2, month)] = (current_sum + goldstein_sum, current_n + n)
            # index/total + percentage feed the activity monitor's chip (#343).
            log(
                f"  gdelt {month_start.year:04d}-{month_start.month:02d} "
                f"({index}/{len(months)}, {100 * index // len(months)}%): "
                f"{checkpoint['days_ok']} days"
                + (
                    f", {len(checkpoint['days_missing'])} missing"
                    if checkpoint["days_missing"]
                    else ""
                )
            )
    finally:
        if owned_client is not None:
            owned_client.close()

    events: list[dict[str, Any]] = []
    for (iso2, month), (goldstein_sum, n) in totals.items():
        if n == 0:
            continue
        year_s, month_s = month.split("-")
        events.append(
            {
                "country": iso2,
                "category": "geopolitical",
                "severity": goldstein_to_severity(goldstein_sum / n),
                "occurred_at": datetime(int(year_s), int(month_s), 1, tzinfo=UTC),
            }
        )
    return events
