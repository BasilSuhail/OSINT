"""Tests for `app.sources.gdelt_fetcher`.

The HTTP layer is mocked with respx; pure helpers (parse_lastupdate,
read_zip_csv) are tested directly without network access.
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest
import respx

from app.sources.gdelt_fetcher import (
    GDELT_LASTUPDATE_URL,
    GdeltFetcher,
    parse_lastupdate,
    read_zip_csv,
)
from app.sources.gdelt_parser import MIN_FIELD_COUNT


def _build_zip(csv_body: str, inner_filename: str = "export.CSV") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(inner_filename, csv_body)
    return buffer.getvalue()


def _conflict_row(global_event_id: str = "1000000001") -> str:
    fields = [""] * MIN_FIELD_COUNT
    fields[0] = global_event_id
    fields[1] = "20260618"
    fields[28] = "18"  # ASSAULT (conflict)
    fields[30] = "-6.0"  # Goldstein → severity 0.8
    fields[31] = "10"
    fields[34] = "-3.0"
    fields[52] = "UP"  # FIPS Ukraine
    fields[56] = "50.45"
    fields[57] = "30.52"
    fields[59] = "https://example.com/a"
    return "\t".join(fields)


class TestParseLastupdate:
    def test_extracts_export_url(self) -> None:
        body = (
            "123456 abc123 http://data.gdeltproject.org/gdeltv2/"
            "20260618224500.export.CSV.zip\n"
            "789012 def456 http://data.gdeltproject.org/gdeltv2/"
            "20260618224500.mentions.CSV.zip\n"
            "345678 ghi789 http://data.gdeltproject.org/gdeltv2/"
            "20260618224500.gkg.csv.zip\n"
        )
        assert parse_lastupdate(body) == (
            "http://data.gdeltproject.org/gdeltv2/20260618224500.export.CSV.zip"
        )

    def test_empty_body_returns_none(self) -> None:
        assert parse_lastupdate("") is None

    def test_no_export_line_returns_none(self) -> None:
        body = (
            "789012 def456 http://data.gdeltproject.org/gdeltv2/20260618224500.mentions.CSV.zip\n"
        )
        assert parse_lastupdate(body) is None


class TestReadZipCsv:
    def test_extracts_csv_text(self) -> None:
        csv = "row1\nrow2\n"
        zip_bytes = _build_zip(csv)
        assert read_zip_csv(zip_bytes) == csv

    def test_empty_archive_returns_empty_string(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w"):
            pass
        assert read_zip_csv(buffer.getvalue()) == ""


class TestGdeltFetcherContract:
    def test_name_and_queue(self) -> None:
        fetcher = GdeltFetcher()
        assert fetcher.name == "gdelt"
        assert fetcher.queue == "slow"

    def test_archive_path_partitioned_by_date(self) -> None:
        fetcher = GdeltFetcher()
        path = fetcher.archive_path()
        assert path.startswith("/mnt/data/parquet/gdelt/year=")
        assert "month=" in path
        assert "day=" in path

    def test_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(ValueError):
            GdeltFetcher(timeout_seconds=0)


class TestGdeltFetcherHttp:
    @respx.mock
    def test_full_fetch_emits_events(self) -> None:
        export_url = "http://data.gdeltproject.org/gdeltv2/20260618224500.export.CSV.zip"
        lastupdate_body = f"123456 abc {export_url}\n"
        zip_bytes = _build_zip(_conflict_row())

        respx.get(GDELT_LASTUPDATE_URL).mock(return_value=httpx.Response(200, text=lastupdate_body))
        respx.get(export_url).mock(return_value=httpx.Response(200, content=zip_bytes))

        events = GdeltFetcher().fetch()
        assert len(events) == 1
        assert events[0].source == "gdelt"
        assert events[0].country == "UA"
        assert events[0].severity == pytest.approx(0.8, abs=1e-6)

    @respx.mock
    def test_no_export_in_lastupdate_returns_empty(self) -> None:
        respx.get(GDELT_LASTUPDATE_URL).mock(return_value=httpx.Response(200, text=""))
        assert GdeltFetcher().fetch() == []

    @respx.mock
    def test_http_error_raises(self) -> None:
        respx.get(GDELT_LASTUPDATE_URL).mock(return_value=httpx.Response(503))
        with pytest.raises(httpx.HTTPStatusError):
            GdeltFetcher().fetch()
