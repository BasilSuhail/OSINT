"""What it is like at a point, right now (#932).

The place screen answers what somewhere *is*. This answers what it is like to
stand there this afternoon — the question a reader is usually asking when they
right-click a specific spot rather than a country.

MET Norway's Locationforecast is free, needs no key, and is CC-BY 4.0: usable
commercially with attribution, which #400 makes a real constraint rather than
an academic one. It asks two things of callers in return, both honoured here —
an identifying User-Agent (the place screen's client already sends one), and
coordinates truncated to four decimals so their cache is not defeated by noise
in the fifth.

## Why a rolling window and not "today"

"Today's high" needs the local timezone at an arbitrary coordinate: another
lookup, another upstream, and a number that is quietly wrong either side of
midnight. The next 24 hours needs nothing but the series already in hand, and
the screen can say precisely what was measured. When the forecast is shorter
than that — the far end of the series, a partial response — the window reports
its own real length rather than claiming a day.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx

_FORECAST_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"

#: How far ahead the high and low look. A day, because that is the span a
#: reader plans against; longer would need a forecast strip, not a line.
FORECAST_HOURS: int = 24

#: MET asks for at most four decimals — about 11 m, far finer than a
#: right-click — so that their cache can do its job.
_COORD_DECIMALS = 4


def _details(entry: dict) -> dict:
    return ((entry.get("data") or {}).get("instant") or {}).get("details") or {}


def _symbol(entry: dict) -> str | None:
    data = entry.get("data") or {}
    # The last entry of a series has no following hour, and some first entries
    # have no icon either. A missing picture is not a missing temperature.
    for window in ("next_1_hours", "next_6_hours", "next_12_hours"):
        code = ((data.get(window) or {}).get("summary") or {}).get("symbol_code")
        if code:
            return code
    return None


def _words(symbol: str | None) -> str | None:
    """`partlycloudy_day` → `Partly cloudy`.

    MET's codes are a closed vocabulary, but transliterating rather than
    mapping means a code added upstream next year reads as English instead of
    disappearing. The trailing `_day` / `_night` is dropped: the screen shows a
    time already, and "Partly cloudy day" is not how anyone says it.
    """
    if not symbol:
        return None
    stem = symbol.split("_")[0]
    words = {
        "partlycloudy": "Partly cloudy",
        "lightrain": "Light rain",
        "heavyrain": "Heavy rain",
        "lightsnow": "Light snow",
        "heavysnow": "Heavy snow",
        "clearsky": "Clear sky",
        "fair": "Fair",
        "cloudy": "Cloudy",
        "fog": "Fog",
        "rain": "Rain",
        "sleet": "Sleet",
        "snow": "Snow",
    }.get(stem)
    if words:
        return words
    # Unknown code: drop the daylight suffix the vocabulary puts on every
    # variant, then read the underscores as spaces. A code added upstream next
    # year arrives as English rather than disappearing.
    parts = [part for part in symbol.split("_") if part not in {"day", "night", "polartwilight"}]
    return " ".join(parts).capitalize() or None


def summarise(body: dict[str, Any]) -> dict:
    """Now, and the range over the next day, from one Locationforecast body."""
    series = ((body.get("properties") or {}).get("timeseries")) or []
    if not series:
        raise LookupError("the forecast carried no entries for this point")

    head = series[0]
    now = _details(head)

    #: Selected by time, not by index. Checked against the live service, a
    #: forecast is hourly for the first days and six-hourly after that — 89
    #: entries, not 24 — so "the first 25 rows" would quietly report a week's
    #: high as a day's.
    start = _moment(head)
    window = [head]
    if start is not None:
        cutoff = start + timedelta(hours=FORECAST_HOURS)
        window = [
            entry
            for entry in series
            if (moment := _moment(entry)) is not None and start <= moment <= cutoff
        ]

    temperatures = [
        value
        for value in (_details(entry).get("air_temperature") for entry in window)
        if value is not None
    ]

    last = _moment(window[-1]) if window else None
    covered = 0 if start is None or last is None else round((last - start).total_seconds() / 3600)

    humidity = now.get("relative_humidity")
    #: No "feels like". The compact endpoint carries no apparent temperature,
    #: and deriving one from wind and humidity would put a number on the screen
    #: that no source stands behind. Wind and humidity are shown instead, and
    #: the reader can do what every weather app is doing for them anyway.
    return {
        "temperature_c": now.get("air_temperature"),
        "wind_ms": now.get("wind_speed"),
        "wind_from_deg": now.get("wind_from_direction"),
        "humidity_pct": None if humidity is None else round(humidity),
        "conditions": _words(_symbol(head)),
        "high_c": max(temperatures) if temperatures else None,
        "low_c": min(temperatures) if temperatures else None,
        #: What the range actually covers. A six-hour forecast reporting a
        #: "24 hour" high would be a claim about hours nobody looked at.
        "range_hours": covered,
        "observed_at": _instant(head),
    }


def _moment(entry: dict) -> datetime | None:
    raw = entry.get("time")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _instant(entry: dict) -> str | None:
    moment = _moment(entry)
    if moment is None:
        return entry.get("time")
    return moment.isoformat().replace("+00:00", "Z")


def conditions(client: httpx.Client, lat: float, lon: float) -> dict:
    """Current conditions at a coordinate. Raises, so the block can degrade."""
    response = client.get(
        _FORECAST_URL,
        params={
            "lat": round(lat, _COORD_DECIMALS),
            "lon": round(lon, _COORD_DECIMALS),
        },
    )
    response.raise_for_status()
    return summarise(response.json())
