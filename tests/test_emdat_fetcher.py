"""Tests for ``app.sources.emdat_fetcher``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import Category
from app.sources.emdat_fetcher import EmdatFetcher, parse_emdat_csv

FETCHED_AT = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)

CSV_SAMPLE = "\n".join(
    [
        "DisNo.,ISO,Country,Disaster Type,Disaster Subtype,Event Name,Start Year,"
        "Start Month,Start Day,Total Deaths,Total Affected,Total Damages ('000 US$),"
        "Latitude,Longitude",
        "2026-0001-PAK,PAK,Pakistan,Flood,Flash flood,Monsoon flood,2026,6,20,12,"
        "50000,1000,30.1,71.5",
    ]
)


def test_parse_emdat_csv_shape() -> None:
    events = parse_emdat_csv(CSV_SAMPLE, fetched_at=FETCHED_AT)
    assert len(events) == 1
    ev = events[0]
    assert ev.source == "emdat"
    assert ev.source_event_id == "2026-0001-PAK"
    assert ev.category == Category.HAZARD
    assert ev.country == "PK"
    assert ev.lat == pytest.approx(30.1)
    assert ev.lon == pytest.approx(71.5)
    assert ev.payload["disaster_type"] == "Flood"
    assert ev.payload["total_deaths"] == 12


def test_fetch_noops_without_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "emdat_csv_path", "")
    assert EmdatFetcher().fetch() == []


def test_fetch_reads_configured_csv(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import settings as settings_module

    path = tmp_path / "emdat.csv"
    path.write_text(CSV_SAMPLE, encoding="utf-8")
    monkeypatch.setattr(settings_module.settings, "emdat_csv_path", str(path))
    events = EmdatFetcher().fetch()
    assert len(events) == 1
    assert events[0].source == "emdat"
