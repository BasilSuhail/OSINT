"""Tests for ``app.sources.acled_fetcher``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import Category
from app.sources.acled_fetcher import AcledFetcher, parse_acled_response, record_to_event

FETCHED_AT = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


def _record(**overrides):
    row = {
        "event_id_cnty": "UKR123",
        "event_date": "2026-06-28",
        "year": "2026",
        "event_type": "Battles",
        "sub_event_type": "Armed clash",
        "actor1": "Actor A",
        "actor2": "Actor B",
        "fatalities": "3",
        "location": "Kyiv",
        "latitude": "50.45",
        "longitude": "30.52",
        "iso3": "UKR",
        "source": "Local source",
    }
    row.update(overrides)
    return row


def test_record_to_event_shape() -> None:
    ev = record_to_event(_record(), fetched_at=FETCHED_AT)
    assert ev is not None
    assert ev.source == "acled"
    assert ev.source_event_id == "UKR123"
    assert ev.category == Category.GEOPOLITICAL
    assert ev.country == "UA"
    assert ev.lat == pytest.approx(50.45)
    assert ev.lon == pytest.approx(30.52)
    assert ev.payload["sub_event_type"] == "Armed clash"
    assert ev.payload["fatalities"] == 3


def test_record_to_event_skips_bad_rows() -> None:
    assert record_to_event(_record(event_id_cnty=""), fetched_at=FETCHED_AT) is None
    assert record_to_event(_record(event_date="not-a-date"), fetched_at=FETCHED_AT) is None


def test_parse_acled_response_reads_data_list() -> None:
    events = parse_acled_response(
        {"data": [_record(), _record(event_id_cnty="UKR124")]},
        fetched_at=FETCHED_AT,
    )
    assert [e.source_event_id for e in events] == ["UKR123", "UKR124"]


def test_fetch_noops_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "acled_email", "")
    monkeypatch.setattr(settings_module.settings, "acled_api_key", "")
    assert AcledFetcher().fetch() == []
