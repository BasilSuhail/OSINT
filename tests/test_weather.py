"""Conditions at a coordinate, and the honest window over them (#932).

MET Norway answers with a timeseries in UTC. The screen wants two things from
it: what it is like now, and how far it moves over the next day.

"Next 24 hours" rather than "today" is the whole reason this parse is small.
"Today" needs the local timezone at an arbitrary coordinate — another lookup,
and another thing to be quietly wrong about either side of midnight. A rolling
window needs nothing but the series it was given, and says exactly what it
measured.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.enrichment.weather import (
    FORECAST_HOURS,
    conditions,
    summarise,
)


def _series(start: datetime, temps: list[float]) -> dict:
    """A Locationforecast body carrying one entry per hour from `start`."""
    return {
        "properties": {
            "timeseries": [
                {
                    "time": (start + timedelta(hours=index)).isoformat().replace("+00:00", "Z"),
                    "data": {
                        "instant": {
                            "details": {
                                "air_temperature": temp,
                                "wind_speed": 3.5,
                                "wind_from_direction": 200.0,
                                "relative_humidity": 71.0,
                            }
                        },
                        "next_1_hours": {"summary": {"symbol_code": "partlycloudy_day"}},
                    },
                }
                for index, temp in enumerate(temps)
            ]
        }
    }


NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)


def test_now_comes_from_the_first_entry() -> None:
    answer = summarise(_series(NOW, [17.2, 18.0, 19.0]))
    assert answer["temperature_c"] == 17.2
    assert answer["wind_ms"] == 3.5
    assert answer["humidity_pct"] == 71
    assert answer["observed_at"] == "2026-08-12T09:00:00Z"


def test_the_range_covers_the_next_twenty_four_hours() -> None:
    """Now through +24 h inclusive — 25 hourly entries. The hour after that is
    outside the window the screen names, and must not move the numbers."""
    temps = [10.0] + [5.0] * 23 + [7.0] + [-40.0]
    answer = summarise(_series(NOW, temps))
    assert answer["high_c"] == 10.0
    assert answer["low_c"] == 5.0
    assert answer["range_hours"] == FORECAST_HOURS


def test_a_short_series_reports_the_window_it_actually_had() -> None:
    """Six hours of forecast is not a day, and must not be labelled as one."""
    answer = summarise(_series(NOW, [10.0, 12.0, 14.0, 9.0, 8.0, 11.0]))
    assert answer["high_c"] == 14.0
    assert answer["low_c"] == 8.0
    assert answer["range_hours"] == 5


def test_the_window_is_hours_and_not_rows() -> None:
    """A live forecast is hourly for two days and six-hourly after that — 89
    entries, checked against the service. Counting rows instead of reading
    times would report a week's extreme as tomorrow's."""
    hourly = [
        {
            "time": (NOW + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
            "data": {"instant": {"details": {"air_temperature": 10.0}}},
        }
        for hour in range(0, 24, 1)
    ]
    six_hourly = [
        {
            "time": (NOW + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
            "data": {"instant": {"details": {"air_temperature": 45.0}}},
        }
        for hour in range(30, 96, 6)
    ]
    answer = summarise({"properties": {"timeseries": hourly + six_hourly}})

    assert answer["high_c"] == 10.0
    assert answer["range_hours"] == 23


def test_the_symbol_becomes_words() -> None:
    answer = summarise(_series(NOW, [17.0, 18.0]))
    assert answer["conditions"] == "Partly cloudy"


def test_an_unknown_symbol_is_passed_through_readably() -> None:
    body = _series(NOW, [17.0])
    body["properties"]["timeseries"][0]["data"]["next_1_hours"]["summary"]["symbol_code"] = (
        "meteor_shower_night"
    )
    assert summarise(body)["conditions"] == "Meteor shower"


def test_a_missing_symbol_block_is_not_a_failure() -> None:
    """The last entry of a forecast carries no next_1_hours. Neither do some
    first entries, and a missing icon is not a missing temperature."""
    body = _series(NOW, [17.0])
    del body["properties"]["timeseries"][0]["data"]["next_1_hours"]
    answer = summarise(body)
    assert answer["conditions"] is None
    assert answer["temperature_c"] == 17.0


def test_an_empty_series_is_an_error_not_an_empty_screen() -> None:
    with pytest.raises(LookupError):
        summarise({"properties": {"timeseries": []}})


def test_conditions_identifies_itself_and_truncates_the_coordinate() -> None:
    """MET requires a User-Agent, and asks that coordinates carry at most four
    decimals so their cache is not defeated by noise."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["agent"] = request.headers.get("user-agent")
        return httpx.Response(200, json=_series(NOW, [17.0, 18.0]))

    client = httpx.Client(
        transport=httpx.MockTransport(handler), headers={"User-Agent": "OSINT-console/1.0 (x)"}
    )
    answer = conditions(client, 48.856614243, 2.352221901)

    assert answer["temperature_c"] == 17.0
    assert "lat=48.8566" in str(seen["url"])
    assert "lon=2.3522" in str(seen["url"])
    assert "OSINT-console" in str(seen["agent"])
