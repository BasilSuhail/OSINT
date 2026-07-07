"""Tests for `app.composite.gdelt` — GDELT historical geopolitical signal."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from app.composite import gdelt
from app.composite.fips import FIPS_TO_ISO2
from app.composite.gdelt import (
    build_month_checkpoint,
    download_day,
    fetch_gdelt_history,
    goldstein_to_severity,
    iter_months,
    load_or_build_month,
    month_days,
    parse_export_csv,
    unzip_export,
)


def _row(sqldate: str, goldstein: str, fips: str, columns: int = 58) -> str:
    cols = ["x"] * columns
    cols[gdelt.COL_SQLDATE] = sqldate
    cols[gdelt.COL_GOLDSTEIN] = goldstein
    cols[gdelt.COL_ACTIONGEO_COUNTRY] = fips
    return "\t".join(cols)


def _csv(*rows: str) -> bytes:
    return ("\n".join(rows) + "\n").encode()


def _zip(payload: bytes, name: str = "20150115.export.CSV") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, payload)
    return buffer.getvalue()


WINDOW = dict(window_start=date(2015, 1, 1), window_end=date(2015, 12, 31))


class TestGoldsteinToSeverity:
    def test_endpoints_and_midpoint(self) -> None:
        assert goldstein_to_severity(-10.0) == 1.0
        assert goldstein_to_severity(10.0) == 0.0
        assert goldstein_to_severity(0.0) == 0.5

    def test_clamped_outside_scale(self) -> None:
        assert goldstein_to_severity(-99.0) == 1.0
        assert goldstein_to_severity(99.0) == 0.0


class TestFipsTable:
    @pytest.mark.parametrize(
        ("fips", "iso2"),
        [
            ("GM", "DE"),  # Germany, not Gambia
            ("GA", "GM"),  # Gambia, not Gabon
            ("GB", "GA"),  # Gabon, not Great Britain
            ("UK", "GB"),  # United Kingdom
            ("CH", "CN"),  # China, not Switzerland
            ("SZ", "CH"),  # Switzerland, not Swaziland
            ("WZ", "SZ"),  # Eswatini
            ("AS", "AU"),  # Australia, not American Samoa
            ("SP", "ES"),  # Spain
            ("RS", "RU"),  # Russia, not Serbia
            ("RI", "RS"),  # Serbia
            ("UP", "UA"),  # Ukraine
            ("JA", "JP"),  # Japan
            ("KS", "KR"),  # South Korea
            ("KN", "KP"),  # North Korea
            ("IZ", "IQ"),  # Iraq
            ("IS", "IL"),  # Israel, not Iceland
            ("IC", "IS"),  # Iceland
            ("CG", "CD"),  # DR Congo
            ("CF", "CG"),  # Congo-Brazzaville
        ],
    )
    def test_trap_pairs(self, fips: str, iso2: str) -> None:
        assert FIPS_TO_ISO2[fips] == iso2

    def test_values_are_iso2_shaped(self) -> None:
        assert all(len(v) == 2 and v.isupper() for v in FIPS_TO_ISO2.values())


class TestParseExportCsv:
    def test_aggregates_by_country_and_event_month(self) -> None:
        raw = _csv(
            _row("20150115", "-5.0", "SY"),
            _row("20150120", "-3.0", "SY"),
            _row("20150215", "4.0", "SY"),
            _row("20150115", "2.0", "GM"),
        )
        sums, unmapped = parse_export_csv(raw, **WINDOW)
        assert sums[("SY", "2015-01")] == (-8.0, 2)
        assert sums[("SY", "2015-02")] == (4.0, 1)
        assert sums[("DE", "2015-01")] == (2.0, 1)
        assert unmapped == 0

    def test_unmapped_fips_counted_not_guessed(self) -> None:
        raw = _csv(_row("20150115", "1.0", "OS"))  # oceans — no ISO2 home
        sums, unmapped = parse_export_csv(raw, **WINDOW)
        assert sums == {}
        assert unmapped == 1

    def test_window_clips_anniversary_mentions(self) -> None:
        raw = _csv(
            _row("19990101", "-9.0", "SY"),  # resurfaced old event
            _row("20160101", "-9.0", "SY"),  # beyond window end
            _row("20150601", "-9.0", "SY"),
        )
        sums, _ = parse_export_csv(raw, **WINDOW)
        assert list(sums) == [("SY", "2015-06")]

    def test_malformed_rows_skipped(self) -> None:
        raw = _csv(
            "too\tfew\tcolumns",
            _row("not-a-date", "1.0", "SY"),
            _row("20150115", "not-a-float", "SY"),
            _row("20150115", "", "SY"),
            _row("20150115", "1.0", ""),
            _row("20150115", "1.5", "SY"),
        )
        sums, unmapped = parse_export_csv(raw, **WINDOW)
        assert sums == {("SY", "2015-01"): (1.5, 1)}
        assert unmapped == 0


class TestUnzipExport:
    def test_roundtrip(self) -> None:
        assert unzip_export(_zip(b"payload")) == b"payload"

    def test_empty_archive_raises(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w"):
            pass
        with pytest.raises(ValueError):
            unzip_export(buffer.getvalue())


class TestDownloadDay:
    def test_gap_day_returns_none(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(404))
        with httpx.Client(transport=transport) as client:
            assert download_day("http://x/20150101.export.CSV.zip", client=client) is None

    def test_retries_then_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(gdelt.time, "sleep", lambda _: None)
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(500)

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            pytest.raises(RuntimeError),
        ):
            download_day("http://x/y.zip", client=client)
        assert calls["n"] == gdelt.DOWNLOAD_RETRIES

    def test_success_returns_bytes(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"zipbytes"))
        with httpx.Client(transport=transport) as client:
            assert download_day("http://x/y.zip", client=client) == b"zipbytes"


class TestCalendarHelpers:
    def test_iter_months_spans_year_boundary(self) -> None:
        months = list(iter_months(date(2014, 11, 15), date(2015, 2, 1)))
        assert months == [date(2014, 11, 1), date(2014, 12, 1), date(2015, 1, 1), date(2015, 2, 1)]

    def test_iter_months_invalid_range_raises(self) -> None:
        with pytest.raises(ValueError):
            list(iter_months(date(2015, 1, 1), date(2014, 1, 1)))

    def test_month_days_february_leap(self) -> None:
        days = month_days(date(2024, 2, 1))
        assert len(days) == 29
        assert days[0] == date(2024, 2, 1)
        assert days[-1] == date(2024, 2, 29)


def _fake_download_for(days: dict[str, bytes | None]):
    def download(url: str) -> bytes | None:
        yyyymmdd = url.rsplit("/", 1)[1].split(".")[0]
        return days[yyyymmdd]

    return download


class TestBuildMonthCheckpoint:
    def test_merges_days_and_records_gaps(self) -> None:
        days: dict[str, bytes | None] = {f"201501{d:02d}": None for d in range(1, 32)}
        days["20150101"] = _zip(_csv(_row("20150101", "-4.0", "SY")))
        days["20150102"] = _zip(_csv(_row("20150102", "-6.0", "SY"), _row("20150102", "2.0", "OS")))
        checkpoint = build_month_checkpoint(
            date(2015, 1, 1), download=_fake_download_for(days), **WINDOW
        )
        assert checkpoint["days_ok"] == 2
        assert len(checkpoint["days_missing"]) == 29
        assert checkpoint["unmapped_rows"] == 1
        assert checkpoint["countries"] == {"SY:2015-01": [-10.0, 2]}


class TestLoadOrBuildMonth:
    def test_builds_persists_then_reads_cache(self, tmp_path: Path) -> None:
        days = {f"201501{d:02d}": None for d in range(1, 32)}
        days["20150101"] = _zip(_csv(_row("20150101", "-4.0", "SY")))
        calls = {"n": 0}

        def counting_download(url: str) -> bytes | None:
            calls["n"] += 1
            return _fake_download_for(days)(url)

        first = load_or_build_month(
            date(2015, 1, 1), cache_dir=tmp_path, download=counting_download, **WINDOW
        )
        assert calls["n"] == 31
        second = load_or_build_month(
            date(2015, 1, 1), cache_dir=tmp_path, download=counting_download, **WINDOW
        )
        assert calls["n"] == 31  # cache hit — no re-download
        assert second == first
        on_disk = json.loads((tmp_path / "gdelt-2015-01.json").read_text())
        assert on_disk == first


class TestFetchGdeltHistory:
    def test_monthly_mean_to_severity_events(self, tmp_path: Path) -> None:
        days: dict[str, bytes | None] = {f"201501{d:02d}": None for d in range(1, 32)}
        # SY mean Goldstein = (-4 + -6) / 2 = -5 → severity 0.75
        days["20150101"] = _zip(_csv(_row("20150101", "-4.0", "SY")))
        days["20150102"] = _zip(_csv(_row("20150102", "-6.0", "SY")))
        events = fetch_gdelt_history(
            date(2015, 1, 1),
            date(2015, 1, 31),
            cache_dir=tmp_path,
            download=_fake_download_for(days),
            log=lambda _: None,
        )
        assert events == [
            {
                "country": "SY",
                "category": "geopolitical",
                "severity": 0.75,
                "occurred_at": datetime(2015, 1, 1, tzinfo=UTC),
            }
        ]

    def test_resumes_from_checkpoints_without_downloader(self, tmp_path: Path) -> None:
        (tmp_path / "gdelt-2015-01.json").write_text(
            json.dumps(
                {
                    "days_ok": 31,
                    "days_missing": [],
                    "unmapped_rows": 0,
                    "countries": {"UA:2015-01": [-20.0, 4]},
                }
            )
        )

        def exploding_download(url: str) -> bytes | None:
            raise AssertionError("cache was complete — downloader must not run")

        events = fetch_gdelt_history(
            date(2015, 1, 1),
            date(2015, 1, 31),
            cache_dir=tmp_path,
            download=exploding_download,
            log=lambda _: None,
        )
        assert len(events) == 1
        assert events[0]["country"] == "UA"
        assert events[0]["severity"] == goldstein_to_severity(-5.0)
