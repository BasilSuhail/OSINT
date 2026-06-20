"""Tests for `app.sources.nasa_firms_fetcher`."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from app import settings as settings_module
from app.models import Category
from app.sources.nasa_firms_fetcher import (
    FIRMS_URL_TEMPLATE,
    NasaFirmsFetcher,
    _confidence_to_severity,
    hash_event_id,
    parse_csv_body,
    row_to_event,
)


def _csv_header() -> str:
    return (
        "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,"
        "instrument,confidence,version,bright_t31,frp,daynight\n"
    )


def _csv_row(
    *,
    latitude: str = "-23.45",
    longitude: str = "-46.63",
    acq_date: str = "2026-06-17",
    acq_time: str = "0314",
    satellite: str = "N20",
    confidence: str = "high",
    brightness: str = "320.5",
) -> str:
    return (
        f"{latitude},{longitude},{brightness},0.5,0.5,{acq_date},{acq_time},"
        f"{satellite},VIIRS,{confidence},2.0NRT,295.1,12.3,N\n"
    )


class TestConfidenceToSeverity:
    def test_text_low(self) -> None:
        assert _confidence_to_severity("low") == 0.2

    def test_text_nominal(self) -> None:
        assert _confidence_to_severity("nominal") == 0.5

    def test_text_high(self) -> None:
        assert _confidence_to_severity("HIGH") == 0.9

    def test_numeric(self) -> None:
        assert _confidence_to_severity("80") == pytest.approx(0.8)
        assert _confidence_to_severity("0") == 0.0
        assert _confidence_to_severity("100") == 1.0

    def test_numeric_clamps(self) -> None:
        assert _confidence_to_severity("150") == 1.0
        assert _confidence_to_severity("-5") == 0.0

    def test_unknown_returns_none(self) -> None:
        assert _confidence_to_severity("garbage") is None
        assert _confidence_to_severity("") is None
        assert _confidence_to_severity(None) is None


class TestHashEventId:
    def test_deterministic(self) -> None:
        a = hash_event_id("-23.45", "-46.63", "2026-06-17", "0314", "N20")
        b = hash_event_id("-23.45", "-46.63", "2026-06-17", "0314", "N20")
        assert a == b

    def test_different_inputs_differ(self) -> None:
        a = hash_event_id("-23.45", "-46.63", "2026-06-17", "0314", "N20")
        b = hash_event_id("-23.45", "-46.63", "2026-06-17", "0315", "N20")
        assert a != b


class TestRowToEvent:
    def test_basic_row_emits_event(self) -> None:
        row = {
            "latitude": "-23.45",
            "longitude": "-46.63",
            "acq_date": "2026-06-17",
            "acq_time": "0314",
            "satellite": "N20",
            "confidence": "high",
            "brightness": "320.5",
        }
        event = row_to_event(row, fetched_at=datetime.now(timezone.utc))
        assert event is not None
        assert event.source == "nasa-firms"
        assert event.category == Category.HAZARD
        assert event.severity == 0.9  # high
        assert event.lat == pytest.approx(-23.45)
        assert event.lon == pytest.approx(-46.63)
        # (-23.45, -46.63) is São Paulo, Brazil — enrichment picks it up.
        assert event.country == "BR"
        assert event.payload["satellite"] == "N20"
        assert event.payload["confidence_raw"] == "high"
        assert event.source_event_id == hash_event_id(
            "-23.45", "-46.63", "2026-06-17", "0314", "N20"
        )

    def test_missing_required_field_skipped(self) -> None:
        row = {
            "latitude": "",
            "longitude": "-46.63",
            "acq_date": "2026-06-17",
            "acq_time": "0314",
            "satellite": "N20",
        }
        assert row_to_event(row, fetched_at=datetime.now(timezone.utc)) is None

    def test_bad_lat_skipped(self) -> None:
        row = {
            "latitude": "not-a-number",
            "longitude": "-46.63",
            "acq_date": "2026-06-17",
            "acq_time": "0314",
            "satellite": "N20",
            "confidence": "high",
        }
        assert row_to_event(row, fetched_at=datetime.now(timezone.utc)) is None

    def test_bad_acq_time_skipped(self) -> None:
        row = {
            "latitude": "-23.45",
            "longitude": "-46.63",
            "acq_date": "2026-06-17",
            "acq_time": "abcd",
            "satellite": "N20",
            "confidence": "high",
        }
        assert row_to_event(row, fetched_at=datetime.now(timezone.utc)) is None


class TestParseCsvBody:
    def test_empty_body(self) -> None:
        assert parse_csv_body("", fetched_at=datetime.now(timezone.utc)) == []

    def test_header_only_returns_empty(self) -> None:
        assert parse_csv_body(_csv_header(), fetched_at=datetime.now(timezone.utc)) == []

    def test_multi_row_csv(self) -> None:
        body = _csv_header() + _csv_row(latitude="1.0") + _csv_row(latitude="2.0")
        events = parse_csv_body(body, fetched_at=datetime.now(timezone.utc))
        assert len(events) == 2
        assert {e.lat for e in events} == {1.0, 2.0}


class TestFetcherContract:
    def test_name_and_queue(self) -> None:
        f = NasaFirmsFetcher()
        assert f.name == "nasa-firms"
        assert f.queue == "slow"

    def test_archive_path(self) -> None:
        path = NasaFirmsFetcher().archive_path()
        assert path.startswith("/mnt/data/parquet/nasa-firms/year=")

    def test_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(ValueError):
            NasaFirmsFetcher(timeout_seconds=0)

    def test_fetch_no_op_without_map_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings_module.settings, "firms_map_key", "")
        assert NasaFirmsFetcher().fetch() == []


class TestFetcherHttp:
    @respx.mock
    def test_fetch_pulls_csv_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings_module.settings, "firms_map_key", "FAKEKEY")
        body = _csv_header() + _csv_row()
        respx.get(url__regex=r"https://firms\.modaps\.eosdis\.nasa\.gov/.*").mock(
            return_value=httpx.Response(200, text=body)
        )
        events = NasaFirmsFetcher().fetch()
        assert len(events) == 1
        assert events[0].source == "nasa-firms"

    @respx.mock
    def test_http_error_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings_module.settings, "firms_map_key", "FAKEKEY")
        respx.get(url__regex=r"https://firms\.modaps\.eosdis\.nasa\.gov/.*").mock(
            return_value=httpx.Response(500)
        )
        with pytest.raises(httpx.HTTPStatusError):
            NasaFirmsFetcher().fetch()


def test_url_template_compiles() -> None:
    assert "{map_key}" in FIRMS_URL_TEMPLATE
    assert "{date}" in FIRMS_URL_TEMPLATE
