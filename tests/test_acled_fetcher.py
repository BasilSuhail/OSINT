"""Tests for ``app.sources.acled_fetcher``."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from app.models import Category
from app.sources.acled_fetcher import (
    AcledFetcher,
    aggregate_record_to_event,
    parse_acled_csv,
    parse_acled_file,
    parse_acled_response,
    record_to_event,
)
from scripts.acled_discover import extract_download_links

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


def test_parse_acled_csv_reads_export_rows() -> None:
    body = (
        "event_id_cnty,event_date,year,event_type,sub_event_type,actor1,actor2,"
        "fatalities,location,latitude,longitude,iso3,source\n"
        "UKR123,2026-06-28,2026,Battles,Armed clash,Actor A,Actor B,3,"
        "Kyiv,50.45,30.52,UKR,Local source\n"
    )
    events = parse_acled_csv(body, fetched_at=FETCHED_AT)
    assert len(events) == 1
    assert events[0].country == "UA"


def test_record_to_event_accepts_variant_event_columns() -> None:
    ev = record_to_event(
        {
            "event_id": "VAR123",
            "date": "2026-06-28",
            "event type": "Protests",
            "fatalities": "0",
            "lat": "33.31",
            "lng": "44.36",
            "country": "Iraq",
        },
        fetched_at=FETCHED_AT,
    )
    assert ev is not None
    assert ev.source_event_id == "VAR123"
    assert ev.country == "IQ"
    assert ev.lon == pytest.approx(44.36)


def test_aggregate_record_to_event_country_year() -> None:
    ev = aggregate_record_to_event(
        {
            "Country": "Ukraine",
            "Year": "2026",
            "Number of political violence events": "42",
        },
        fetched_at=FETCHED_AT,
        source_name="country-year.csv",
    )
    assert ev is not None
    assert ev.source == "acled"
    assert ev.country == "UA"
    assert ev.lat is not None
    assert ev.lon is not None
    assert ev.occurred_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert ev.payload["aggregate"] is True
    assert ev.payload["metric_name"] == "number_of_political_violence_events"
    assert ev.payload["metric_value"] == 42


def test_aggregate_record_to_event_country_month() -> None:
    ev = aggregate_record_to_event(
        {
            "ISO3": "NGA",
            "Year": "2026",
            "Month": "6",
            "Reported fatalities": "12",
        },
        fetched_at=FETCHED_AT,
        source_name="country-month.csv",
    )
    assert ev is not None
    assert ev.country == "NG"
    assert ev.occurred_at == datetime(2026, 6, 1, tzinfo=UTC)
    assert ev.payload["metric_name"] == "reported_fatalities"


def test_parse_acled_csv_accepts_aggregate_rows() -> None:
    body = "Country,Year,Number of political violence events\nUkraine,2026,42\n"
    events = parse_acled_csv(body, fetched_at=FETCHED_AT, source_name="aggregate.csv")
    assert len(events) == 1
    assert events[0].country == "UA"

def test_parse_acled_file_accepts_excel_aggregate_rows(tmp_path) -> None:
    pd = pytest.importorskip("pandas")

    path = tmp_path / "aggregate.xlsx"
    pd.DataFrame(
        [
            {
                "Country": "Ukraine",
                "Year": 2026,
                "Month": 6,
                "Number of political violence events": 42,
            }
        ]
    ).to_excel(path, index=False)

    events = parse_acled_file(path, fetched_at=FETCHED_AT)

    assert len(events) == 1
    assert events[0].country == "UA"
    assert events[0].occurred_at == datetime(2026, 6, 1, tzinfo=UTC)
    assert events[0].payload["metric_value"] == 42

def test_fetch_noops_without_csv_or_enabled_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "acled_csv_path", "")
    monkeypatch.setattr(settings_module.settings, "acled_csv_dir", "")
    monkeypatch.setattr(settings_module.settings, "acled_api_enabled", False)
    assert AcledFetcher().fetch() == []


def test_fetch_reads_configured_csv(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import settings as settings_module

    path = tmp_path / "acled.csv"
    path.write_text(
        "event_id_cnty,event_date,year,event_type,sub_event_type,actor1,actor2,"
        "fatalities,location,latitude,longitude,iso3,source\n"
        "UKR123,2026-06-28,2026,Battles,Armed clash,Actor A,Actor B,3,"
        "Kyiv,50.45,30.52,UKR,Local source\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_module.settings, "acled_csv_path", str(path))
    monkeypatch.setattr(settings_module.settings, "acled_csv_dir", "")
    monkeypatch.setattr(settings_module.settings, "acled_api_enabled", False)
    events = AcledFetcher(lookback_days=30).fetch()
    assert len(events) == 1
    assert events[0].source == "acled"


def test_fetch_reads_mixed_spreadsheet_directory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import settings as settings_module

    (tmp_path / "events.csv").write_text(
        "event_id_cnty,event_date,event_type,fatalities,latitude,longitude,iso3\n"
        "UKR123,2026-06-28,Battles,3,50.45,30.52,UKR\n",
        encoding="utf-8",
    )
    (tmp_path / "aggregate.csv").write_text(
        "Country,Year,Month,Events targeting civilians\nUkraine,2026,6,9\n",
        encoding="utf-8",
    )
    with pd.ExcelWriter(tmp_path / "events.xlsx", engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "event_id_cnty": "UKR124",
                    "event_date": "2026-06-27",
                    "event_type": "Protests",
                    "fatalities": 0,
                    "latitude": 50.45,
                    "longitude": 30.52,
                    "iso3": "UKR",
                }
            ]
        ).to_excel(writer, sheet_name="Events", index=False)
    monkeypatch.setattr(settings_module.settings, "acled_csv_path", "")
    monkeypatch.setattr(settings_module.settings, "acled_csv_dir", str(tmp_path))
    monkeypatch.setattr(settings_module.settings, "acled_api_enabled", False)

    events = AcledFetcher(lookback_days=30).fetch()

    assert len(events) == 3
    assert {event.payload.get("aggregate", False) for event in events} == {False, True}


def test_fetch_reads_mixed_csv_and_excel_directory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pd = pytest.importorskip("pandas")
    from app import settings as settings_module

    (tmp_path / "events.csv").write_text(
        "event_id_cnty,event_date,event_type,fatalities,latitude,longitude,iso3\n"
        "UKR123,2026-06-28,Battles,3,50.45,30.52,UKR\n",
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "Country": "Ukraine",
                "Year": 2026,
                "Month": 6,
                "Events targeting civilians": 9,
            }
        ]
    ).to_excel(tmp_path / "aggregate.xlsx", index=False)
    monkeypatch.setattr(settings_module.settings, "acled_csv_path", "")
    monkeypatch.setattr(settings_module.settings, "acled_csv_dir", str(tmp_path))
    monkeypatch.setattr(settings_module.settings, "acled_api_enabled", False)

    events = AcledFetcher(lookback_days=30).fetch()

    assert len(events) == 2
    assert {event.payload.get("aggregate", False) for event in events} == {False, True}


def test_extract_download_links_finds_visible_files() -> None:
    html = """
    <html>
      <a href="/downloads/acled.csv">CSV</a>
      <a href="https://example.com/data.xlsx">XLSX</a>
      <a href="/page">Page</a>
    </html>
    """
    assert extract_download_links(html, "https://acleddata.com/source") == [
        "https://acleddata.com/downloads/acled.csv",
        "https://example.com/data.xlsx",
    ]
