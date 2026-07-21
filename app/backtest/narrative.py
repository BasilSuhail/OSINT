"""Daily narrative volume per country, for the phase-1 lead-time gate (#518).

The gate compares when physical sensors spike against when the narrative spikes.
The narrative side used to come from `GdeltBackfill`, which asked the DOC API for
an article list with `format=tsv`. GDELT rejects that with a prose body at HTTP
200 — `raise_for_status()` passes, the CSV parser finds no rows, and the gate
scores a confident FAIL against a narrative series that was never fetched.

Two changes follow from that.

First, volume comes from `mode=timelinevolraw`, which returns one daily count per
day for the whole window in a single request. Paging article lists needed dozens
of calls per event against an API that permits one call every five seconds.

Second, nothing here returns an empty series. An empty result is indistinguishable
from a broken query, and treating the two alike is what produced a FAIL verdict
on the project's central claim. Failures raise.

Responses are cached on disk because the gate is meant to be re-run — against new
registries, new thresholds, new method versions — and re-running must not depend
on a rate-limited public API being reachable.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import date, timedelta
from pathlib import Path

import httpx

from app.backtest import pacing
from app.enrichment.country import country_name

_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMEOUT_S = 90.0

#: GDELT publishes "one request every 5 seconds". A burst earns a rolling 429
#: penalty that outlasts the burst by minutes, so the gate paces itself rather
#: than discovering the limit the hard way mid-run.
#:
#: Overridable so a sweep of many countries can be paced more conservatively
#: than a single fetch without editing this module (#559).
MIN_INTERVAL_S = float(os.environ.get("BACKTEST_GDELT_MIN_INTERVAL_S", 5.0))
_RETRIES = 3

#: The series carrying this country's article count. The response also holds
#: "Total Monitored Articles" — the whole GDELT corpus for the day, identical
#: for every country, which would make every country look equally loud.
_COUNT_SERIES = "article count"

DEFAULT_CACHE_DIR = Path("data/backtest_cache")

#: Pacing state lives beside the response cache: both describe the same
#: conversation with GDELT, and both must outlive the process.
PACING_STATE_PATH = DEFAULT_CACHE_DIR / "gdelt-pacing.json"

#: Words outlets actually use for a topic. Scoping the query to the event is the
#: difference between asking "did this country's news spike?" and "did coverage
#: of this event spike?" — Japan runs ~1,300 articles a day and a M6 earthquake
#: adds perhaps thirty, so the country-wide question can only ever answer no
#: (#528).
TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    "earthquake": ("earthquake", "quake", "tremor", "seismic", "aftershock"),
    "flood": ("flood", "flooding", "inundation"),
    "cyclone": ("cyclone", "hurricane", "typhoon", "storm"),
    "wildfire": ("wildfire", "bushfire", "blaze"),
    "volcano": ("volcano", "volcanic", "eruption"),
    "drought": ("drought",),
}


def build_query(country_name: str, topic: str | None) -> str:
    """GDELT query for a country, optionally narrowed to a topic."""
    scope = f"sourcecountry:{country_name.lower()}"
    if not topic:
        return scope
    terms = TOPIC_TERMS.get(topic.lower(), (topic.lower(),))
    if len(terms) == 1:
        return f"{scope} {terms[0]}"
    return f"{scope} ({' OR '.join(terms)})"


class NarrativeUnavailableError(RuntimeError):
    """The narrative series could not be fetched, so the window is unscorable."""


def parse_timeline(body: str) -> dict[date, int]:
    """GDELT timeline CSV → {day: article count}."""
    counts: dict[date, int] = {}
    reader = csv.DictReader(io.StringIO(body.lstrip("﻿")))
    for row in reader:
        series = (row.get("Series") or "").strip().lower()
        if series != _COUNT_SERIES:
            continue
        raw_day = (row.get("Date") or "").strip()
        raw_value = (row.get("Value") or "").strip()
        if not raw_day or not raw_value:
            continue
        try:
            day = date.fromisoformat(raw_day[:10])
            counts[day] = int(float(raw_value))
        except ValueError:
            continue
    return counts


def daily_series(counts: dict[date, int], start: date, end: date) -> tuple[list[date], list[float]]:
    """Contiguous day list and values, zero-filling days GDELT did not report.

    A quiet day is a real zero. Leaving it out would shorten the series and
    silently misalign it against the physical side it is compared with.
    """
    days: list[date] = []
    values: list[float] = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        values.append(float(counts.get(cursor, 0)))
        cursor += timedelta(days=1)
    return days, values


def _cache_path(cache_dir: Path, country: str, start: date, end: date, query: str) -> Path:
    """Cache key includes the query.

    Keying on country and window alone meant a corrected query kept being served
    the data its broken predecessor fetched — a fixed bug still returning its
    own wrong answers (#520).
    """
    token = hashlib.sha256(query.encode("utf-8")).hexdigest()[:8]
    return cache_dir / f"{country.upper()}_{start:%Y%m%d}_{end:%Y%m%d}_{token}.json"


def _looks_like_error(body: str) -> str | None:
    """GDELT reports failure as prose at HTTP 200. Return the reason, or None."""
    head = body.strip()[:200].lower()
    for marker in ("invalid format", "please limit requests", "error", "not recognized"):
        if marker in head:
            return body.strip()[:200]
    return None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """`Retry-After` in seconds, when the host sends a usable one."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:  # HTTP-date form; the default cooldown covers it
        return None


def _pacer() -> pacing.Pacer:
    return pacing.Pacer(state_path=PACING_STATE_PATH, min_interval_s=MIN_INTERVAL_S)


def _get_with_pacing(params: dict, country: str, start: date, end: date) -> str:
    """One paced request, retrying a rate-limit refusal with backoff.

    Pacing state is persisted (#559): a refusal widens the wait for every later
    call, including calls made by a later process. The old in-process global
    meant each resumed run opened with an immediate call and re-provoked the
    limiter it was resuming because of.
    """
    pacer = _pacer()
    last_reason = "unknown"
    for attempt in range(_RETRIES):
        pacer.wait_turn()
        try:
            response = httpx.get(_ENDPOINT, params=params, timeout=_TIMEOUT_S)
        except httpx.HTTPError as exc:  # network down, DNS, timeout
            raise NarrativeUnavailableError(f"{country} {start}..{end}: {exc}") from exc
        finally:
            pacer.record_call()

        if response.status_code == 429:
            last_reason = "HTTP 429"
            pacer.record_refusal(retry_after_s=_retry_after_seconds(response))
        elif response.status_code != 200:
            raise NarrativeUnavailableError(
                f"{country} {start}..{end}: HTTP {response.status_code}"
            )
        else:
            reason = _looks_like_error(response.text)
            if reason is None:
                pacer.record_success()
                return response.text
            # Prose-at-200 is how GDELT says "slow down" as often as not.
            last_reason = f"GDELT said {reason!r}"
            pacer.record_refusal()

        if attempt == _RETRIES - 1:
            break
    raise NarrativeUnavailableError(
        f"{country} {start}..{end}: {last_reason}"
        + (
            f"; pacing cooldown {pacer.cooldown_remaining():.0f}s before the next call"
            if pacer.cooldown_remaining() > 0
            else ""
        )
    )


def fetch_daily_volume(
    country: str,
    start: date,
    end: date,
    *,
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    query: str | None = None,
    topic: str | None = None,
) -> dict[date, int]:
    """Daily article volume for one country over one window.

    Raises `NarrativeUnavailableError` rather than returning an empty series: a window
    with no narrative data cannot be scored, and pretending otherwise is what
    made the gate report FAIL on missing data.
    """
    if query is None:
        # GDELT's sourcecountry: operator takes a country NAME. Sending the ISO
        # code returned nothing for Japan, the Philippines, Russia, China and
        # Chile — five of the largest news markets there are (#520).
        name = country_name(country)
        if not name:
            raise NarrativeUnavailableError(
                f"{country} {start}..{end}: no country name for ISO {country!r}; "
                "refusing to send the raw code, which GDELT answers with silence"
            )
        query = build_query(name, topic)

    path = _cache_path(cache_dir, country, start, end, query) if cache_dir else None
    if path is not None and path.exists():
        cached = json.loads(path.read_text())
        return {date.fromisoformat(k): int(v) for k, v in cached.items()}

    params = {
        "query": query,
        "mode": "timelinevolraw",
        "format": "csv",
        "startdatetime": f"{start:%Y%m%d}000000",
        "enddatetime": f"{end:%Y%m%d}235959",
    }
    body = _get_with_pacing(params, country, start, end)
    counts = parse_timeline(body)
    if not counts:
        raise NarrativeUnavailableError(
            f"{country} {start}..{end}: no daily rows parsed — "
            "an empty window is not evidence of a quiet one"
        )

    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({d.isoformat(): v for d, v in counts.items()}, indent=0))
    return counts
