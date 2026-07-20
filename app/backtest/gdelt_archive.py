"""Daily per-country volume from GDELT's raw 15-minute exports (#555).

The gate's narrative side reads the DOC API, which only reaches back about
three months and is rate limited. GDELT's raw export grid is free, complete and
unthrottled, so anchors older than that window become scorable — the unlock
described in #550 §1.1.

What this deliberately does not do is store the rows. `scripts/backfill.py`
persists raw GDELT events, and `app/housekeeping.py` prunes that source at ~30
days: a multi-year raw backfill would be deleted on the next housekeeping pass,
having first eaten the 30 GB cap. Counts are the durable shape — a year is
roughly 200 countries x 365 days.

Two counts per country-day are kept. `events` is one per coded event row;
`mentions` sums GDELT's NumMentions. The DOC API measures *article* volume, so
mentions are the closer analogue, but which series actually tracks it is a
question for the comparison on the overlapping window, not one to guess here.

Every CAMEO code counts, unlike the live fetcher's conflict-only filter:
narrative volume means coverage volume.

Rows are bucketed by the *file's* timestamp, not by their own Day column. A
single 15-minute export carries events dated up to a year earlier — Day is when
something happened, and the file stamp is when GDELT saw it reported. The gate
measures when coverage spikes relative to a sensor, so bucketing by event date
would smear the very signal it is trying to detect.
"""

from __future__ import annotations

import concurrent.futures
import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import GdeltArchiveDayRow, GdeltDailyVolumeRow
from app.enrichment.country import country_for
from app.sources.gdelt_cameo import fips_to_iso
from app.sources.gdelt_parser import (
    COL_ACTION_COUNTRY,
    COL_ACTION_LAT,
    COL_ACTION_LON,
    COL_NUM_MENTIONS,
    MIN_FIELD_COUNT,
)

METHOD_VERSION: str = "gdelt-archive-v1.0"

#: The same grid `scripts/backfill.py` walks — one zipped CSV every 15 minutes.
EXPORT_URL: str = "http://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"

#: GDELT publishes 96 export files a day. A handful routinely 404 — a day is
#: still usable, but a day missing a large share of its files is a dip the
#: sensor side never caused, so it does not count as ingested.
FILES_PER_DAY: int = 96
MIN_FILES_FOR_A_DAY: int = 90


class ArchiveWindowMissingError(RuntimeError):
    """The window asked for has not been walked, so it has no volume to report."""


@dataclass(frozen=True)
class DayCount:
    """Volume for one country on one day."""

    events: int
    mentions: int


#: Polygon lookups dominate the cost when the country column is unusable, and
#: export rows cluster hard on the same cities. Rounding to ~1 km before the
#: lookup makes the cache hit for the whole cluster.
@lru_cache(maxsize=100_000)
def _country_at(lat_key: float, lon_key: float) -> str | None:
    return country_for(lat_key, lon_key)


def _float_or_none(raw: str) -> float | None:
    try:
        return float(raw)
    except ValueError:
        return None


def _country_of(fields: list[str]) -> str | None:
    raw = fields[COL_ACTION_COUNTRY].strip() or None
    country = fips_to_iso(raw)
    if country is not None:
        return country
    lat = _float_or_none(fields[COL_ACTION_LAT])
    lon = _float_or_none(fields[COL_ACTION_LON])
    if lat is None or lon is None:
        return None
    return _country_at(round(lat, 2), round(lon, 2))


def count_rows(body: str, *, day: date) -> dict[tuple[str, date], DayCount]:
    """Count one export file's rows by country, filed under `day`.

    `day` is the date of the file itself, not of the rows: an export carries
    events dated long before it, and what the gate needs is when coverage
    appeared.

    Rows are read field by field rather than through `parse_csv_body`: building
    an `Event` per row only to discard it is what #546 removed from the ACLED
    path, and this walks tens of thousands of files.
    """
    events: defaultdict[tuple[str, date], int] = defaultdict(int)
    mentions: defaultdict[tuple[str, date], int] = defaultdict(int)

    for line in body.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < MIN_FIELD_COUNT:
            continue
        country = _country_of(fields)
        if country is None:
            continue
        key = (country, day)
        events[key] += 1
        mentions[key] += int(_float_or_none(fields[COL_NUM_MENTIONS]) or 0)

    return {key: DayCount(events=events[key], mentions=mentions[key]) for key in events}


def merge_counts(
    running: dict[tuple[str, date], DayCount], batch: dict[tuple[str, date], DayCount]
) -> None:
    """Fold one file's counts into a running total, in place."""
    for key, count in batch.items():
        current = running.get(key)
        if current is None:
            running[key] = count
        else:
            running[key] = DayCount(
                events=current.events + count.events,
                mentions=current.mentions + count.mentions,
            )


def _upsert(session: Session, model, values: dict, index_elements: list[str], update: list[str]):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        base = pg_insert(model).values(values)
    elif dialect == "sqlite":
        base = sqlite_insert(model).values(values)
    else:
        raise NotImplementedError(f"gdelt_archive: unsupported dialect {dialect!r}")
    return base.on_conflict_do_update(
        index_elements=index_elements,
        set_={column: base.excluded[column] for column in update},
    )


def store_counts(session: Session, counts: dict[tuple[str, date], DayCount]) -> int:
    """Upsert country-day counts. Returns how many rows were written.

    Overwrites rather than accumulates: a run interrupted part-way through a
    day leaves a partial count, and resuming must replace it.
    """
    written = 0
    for (country, day), count in counts.items():
        session.execute(
            _upsert(
                session,
                GdeltDailyVolumeRow,
                {
                    "country": country,
                    "day": day,
                    "events": count.events,
                    "mentions": count.mentions,
                    "method_version": METHOD_VERSION,
                },
                ["country", "day", "method_version"],
                ["events", "mentions"],
            )
        )
        written += 1
    session.commit()
    return written


def mark_day_ingested(session: Session, day: date, *, files_ok: int, files_missing: int) -> None:
    """Record that `day`'s export grid has been walked."""
    session.execute(
        _upsert(
            session,
            GdeltArchiveDayRow,
            {
                "day": day,
                "files_ok": files_ok,
                "files_missing": files_missing,
                "method_version": METHOD_VERSION,
            },
            ["day", "method_version"],
            ["files_ok", "files_missing"],
        )
    )
    session.commit()


def ingested_days(session: Session, start: date, end: date) -> set[date]:
    """Days in `[start, end]` walked completely enough to be trusted."""
    rows = session.execute(
        select(GdeltArchiveDayRow.day, GdeltArchiveDayRow.files_ok).where(
            GdeltArchiveDayRow.method_version == METHOD_VERSION,
            GdeltArchiveDayRow.day >= start,
            GdeltArchiveDayRow.day <= end,
        )
    ).all()
    return {day for day, files_ok in rows if files_ok >= MIN_FILES_FOR_A_DAY}


def daily_volume(
    session: Session, country: str, start: date, end: date, *, measure: str = "mentions"
) -> dict[date, int]:
    """Narrative volume per day for `country` over `[start, end]`, inclusive.

    Shaped to match `narrative.fetch_daily_volume` so it can be injected as the
    gate's `volume_fetcher`. A day that was walked but carries no rows for this
    country is a real zero. A day that was never walked raises: an un-ingested
    window must never read as a quiet one.
    """
    wanted = {start + timedelta(days=offset) for offset in range((end - start).days + 1)}
    missing = sorted(wanted - ingested_days(session, start, end))
    if missing:
        raise ArchiveWindowMissingError(
            f"{country}: {len(missing)} day(s) of the archive were never ingested, "
            f"first {missing[0].isoformat()}. Run scripts/gdelt_archive.py for this range."
        )

    column = GdeltDailyVolumeRow.events if measure == "events" else GdeltDailyVolumeRow.mentions
    rows = session.execute(
        select(GdeltDailyVolumeRow.day, column).where(
            GdeltDailyVolumeRow.method_version == METHOD_VERSION,
            GdeltDailyVolumeRow.country == country,
            GdeltDailyVolumeRow.day >= start,
            GdeltDailyVolumeRow.day <= end,
        )
    ).all()
    series = dict.fromkeys(wanted, 0)
    for day, value in rows:
        series[day] = value
    return series


def day_stamps(day: date) -> list[str]:
    """The 96 export stamps GDELT publishes for `day`."""
    start = datetime(day.year, day.month, day.day)
    return [
        (start + timedelta(minutes=15 * slot)).strftime("%Y%m%d%H%M%S")
        for slot in range(FILES_PER_DAY)
    ]


def read_export(client: httpx.Client, stamp: str) -> str | None:
    """One export file's CSV body, or None if it is unavailable or unreadable."""
    try:
        response = client.get(EXPORT_URL.format(stamp=stamp))
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            if not names:
                return None
            with archive.open(names[0]) as handle:
                return handle.read().decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError):
        return None


def ingest_day(
    session: Session, day: date, *, client: httpx.Client, concurrency: int = 8
) -> dict[str, int]:
    """Walk one day's export grid, store its counts, and record the day.

    The day is marked *after* its counts are stored, so an interrupted run
    leaves the day unmarked and the next pass redoes it rather than trusting a
    partial count.
    """
    counts: dict[tuple[str, date], DayCount] = {}
    files_ok = 0
    files_missing = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        for body in pool.map(lambda stamp: read_export(client, stamp), day_stamps(day)):
            if body is None:
                files_missing += 1
                continue
            files_ok += 1
            merge_counts(counts, count_rows(body, day=day))

    store_counts(session, counts)
    mark_day_ingested(session, day, files_ok=files_ok, files_missing=files_missing)
    return {
        "files_ok": files_ok,
        "files_missing": files_missing,
        "country_days": len(counts),
    }
