"""Tests for `app.sources.nasa_firms_fetcher`."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise

import httpx
import pytest
import respx

from app import settings as settings_module
from app.models import Category
from app.sources.nasa_firms_fetcher import (
    FIRMS_URL_TEMPLATE,
    FRP_REFERENCE_MW,
    FRP_SEVERITY_CEILING,
    NasaFirmsFetcher,
    confidence_quality,
    frp_to_severity,
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


class TestConfidenceQuality:
    def test_text_low(self) -> None:
        assert confidence_quality("low") == 0.2

    def test_text_nominal(self) -> None:
        assert confidence_quality("nominal") == 0.5

    def test_text_high(self) -> None:
        assert confidence_quality("HIGH") == 0.9

    def test_numeric(self) -> None:
        assert confidence_quality("80") == pytest.approx(0.8)
        assert confidence_quality("0") == 0.0
        assert confidence_quality("100") == 1.0

    def test_numeric_clamps(self) -> None:
        assert confidence_quality("150") == 1.0
        assert confidence_quality("-5") == 0.0

    def test_unknown_returns_none(self) -> None:
        assert confidence_quality("garbage") is None
        assert confidence_quality("") is None
        assert confidence_quality(None) is None


class TestFrpToSeverity:
    """Severity comes from radiative power, not detection confidence (#579)."""

    def test_zero_frp_is_zero(self) -> None:
        assert frp_to_severity("0", confidence_raw="n") == 0.0

    def test_monotonic_in_frp(self) -> None:
        # The property the old mapping broke: more radiative power always
        # means more severity, whatever the confidence letter says.
        # min, p50, p99 and max of the 536,097 stored rows.
        measured = (0.0, 1.0, 5.37, 105.69, 1488.19)
        values = [frp_to_severity(str(f), confidence_raw="n") for f in measured]
        assert all(v is not None for v in values)
        assert all(a < b for a, b in pairwise(values))

    def test_a_low_confidence_big_fire_outranks_a_high_confidence_small_one(self) -> None:
        # The measured inversion: `l` pixels average 18.27 MW against 8.91 for
        # `n`, so the old confidence mapping ranked these two backwards.
        big_but_uncertain = frp_to_severity("500", confidence_raw="l")
        small_but_certain = frp_to_severity("2", confidence_raw="h")
        assert big_but_uncertain is not None and small_but_certain is not None
        assert big_but_uncertain > small_but_certain

    def test_never_reaches_the_lethal_floor(self) -> None:
        # A detection knows nothing about casualties. It must not outrank a
        # confirmed-fatality event sharing its country-month.
        from app.severity import scale

        hottest = frp_to_severity(str(FRP_REFERENCE_MW * 100), confidence_raw="h")
        assert hottest is not None
        assert hottest <= FRP_SEVERITY_CEILING < scale.LETHAL_FLOOR

    def test_reference_frp_lands_at_the_ceiling(self) -> None:
        assert frp_to_severity(str(FRP_REFERENCE_MW), confidence_raw="n") == pytest.approx(
            FRP_SEVERITY_CEILING, abs=1e-6
        )

    def test_the_measured_distribution_spreads(self) -> None:
        # The whole complaint in #579 was three distinct values. p50 and p99
        # of the stored FRP must not collapse to the same number.
        p50 = frp_to_severity("5.37", confidence_raw="n")
        p99 = frp_to_severity("105.69", confidence_raw="n")
        assert p50 == pytest.approx(0.139, abs=0.005)
        assert p99 == pytest.approx(0.351, abs=0.005)

    def test_unreadable_confidence_still_refuses(self) -> None:
        # #574's lesson: an encoding change must fail loudly at the boundary,
        # not quietly become "no fire happened".
        assert frp_to_severity("12.3", confidence_raw="bananas") is None
        assert frp_to_severity("12.3", confidence_raw=None) is None

    def test_unreadable_frp_returns_none_rather_than_falling_back(self) -> None:
        # Falling back to confidence would silently restore the wrong quantity.
        assert frp_to_severity(None, confidence_raw="h") is None
        assert frp_to_severity("", confidence_raw="h") is None
        assert frp_to_severity("not-a-number", confidence_raw="h") is None

    def test_nonsense_frp_values_are_refused(self) -> None:
        assert frp_to_severity("-1", confidence_raw="h") is None
        assert frp_to_severity("nan", confidence_raw="h") is None
        assert frp_to_severity("inf", confidence_raw="h") is None


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
            "frp": "12.3",
        }
        event = row_to_event(row, fetched_at=datetime.now(UTC))
        assert event is not None
        assert event.source == "nasa-firms"
        # Still stored as a hazard — it is one, and the map treats it as one.
        # The composite routes it to the wildfire domain by source (#579).
        assert event.category == Category.HAZARD
        assert event.severity == frp_to_severity("12.3", confidence_raw="high")
        assert event.payload["severity_method"] == "firms-frp-v1"
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
        assert row_to_event(row, fetched_at=datetime.now(UTC)) is None

    def test_bad_lat_skipped(self) -> None:
        row = {
            "latitude": "not-a-number",
            "longitude": "-46.63",
            "acq_date": "2026-06-17",
            "acq_time": "0314",
            "satellite": "N20",
            "confidence": "high",
        }
        assert row_to_event(row, fetched_at=datetime.now(UTC)) is None

    def test_bad_acq_time_skipped(self) -> None:
        row = {
            "latitude": "-23.45",
            "longitude": "-46.63",
            "acq_date": "2026-06-17",
            "acq_time": "abcd",
            "satellite": "N20",
            "confidence": "high",
        }
        assert row_to_event(row, fetched_at=datetime.now(UTC)) is None


class TestParseCsvBody:
    def test_empty_body(self) -> None:
        assert parse_csv_body("", fetched_at=datetime.now(UTC)) == []

    def test_header_only_returns_empty(self) -> None:
        assert parse_csv_body(_csv_header(), fetched_at=datetime.now(UTC)) == []

    def test_multi_row_csv(self) -> None:
        body = _csv_header() + _csv_row(latitude="1.0") + _csv_row(latitude="2.0")
        events = parse_csv_body(body, fetched_at=datetime.now(UTC))
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

    def test_fetch_reports_missing_map_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.sources.base import SourceMisconfiguredError

        monkeypatch.setattr(settings_module.settings, "firms_map_key", "")
        with pytest.raises(SourceMisconfiguredError, match="FIRMS_MAP_KEY"):
            NasaFirmsFetcher().fetch()


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


class TestViirsConfidenceEncoding:
    """VIIRS sends l/n/h, not low/nominal/high (#574).

    The map only carried the words, so `float("n")` raised and every row got
    `severity=None` — 536,097 of them. The composite skips null severity, so
    the largest sensor in the system contributed nothing to any analysis for
    its entire life. The value was read and stored correctly the whole time
    (`payload.confidence_raw` == "h"), which is why it stayed invisible.
    """

    def test_single_letter_codes_are_understood(self) -> None:
        from app.sources.nasa_firms_fetcher import confidence_quality

        assert confidence_quality("l") is not None
        assert confidence_quality("n") is not None
        assert confidence_quality("h") is not None

    def test_the_letters_rank_the_same_way_as_the_words(self) -> None:
        from app.sources.nasa_firms_fetcher import confidence_quality

        assert confidence_quality("l") == confidence_quality("low")
        assert confidence_quality("n") == confidence_quality("nominal")
        assert confidence_quality("h") == confidence_quality("high")

    def test_confidence_still_orders_low_below_high(self) -> None:
        from app.sources.nasa_firms_fetcher import confidence_quality

        assert confidence_quality("l") < confidence_quality("n") < confidence_quality("h")

    def test_modis_numeric_confidence_still_works(self) -> None:
        # MODIS reports 0-100 rather than a category; that path must survive.
        from app.sources.nasa_firms_fetcher import confidence_quality

        assert confidence_quality("0") == 0.0
        assert confidence_quality("100") == 1.0

    def test_an_unrecognised_encoding_still_returns_none(self) -> None:
        # If NASA changes the encoding again this must fail loudly at the
        # boundary rather than quietly becoming "no fire happened".
        from app.sources.nasa_firms_fetcher import confidence_quality

        assert confidence_quality("bananas") is None
        assert confidence_quality("") is None
        assert confidence_quality(None) is None
