"""Tests for `app.labels.acled_loader` — regional weekly xlsx → tidy rows."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import openpyxl
import pytest

from app.labels.acled_loader import load_acled_weekly

_HEADER = [
    "WEEK",
    "REGION",
    "COUNTRY",
    "ADMIN1",
    "EVENT_TYPE",
    "SUB_EVENT_TYPE",
    "EVENTS",
    "FATALITIES",
    "POPULATION_EXPOSURE",
    "DISORDER_TYPE",
    "ID",
    "CENTROID_LATITUDE",
    "CENTROID_LONGITUDE",
]


def _write_xlsx(path: Path, rows: list[list[object]]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_HEADER)
    for row in rows:
        ws.append(row)
    wb.save(path)


def _sample_row(
    *,
    week: datetime | str = datetime(2024, 1, 6),
    country: str = "Syria",
    event_type: str = "Battles",
    events: int = 3,
    fatalities: int = 12,
) -> list[object]:
    return [
        week,
        "Middle East",
        country,
        "Aleppo",
        event_type,
        "Armed clash",
        events,
        fatalities,
        100000,
        "Political violence",
        123,
        36.2,
        37.16,
    ]


def test_loads_and_maps_country_to_iso2(tmp_path: Path) -> None:
    _write_xlsx(
        tmp_path / "Middle-East_aggregated_data_up_to_week_of-2026-06-13.xlsx", [_sample_row()]
    )
    result = load_acled_weekly(tmp_path)
    (row,) = result.rows
    assert row["country"] == "SY"
    assert row["week"] == datetime(2024, 1, 6, tzinfo=UTC)
    assert row["event_type"] == "Battles"
    assert row["events"] == 3
    assert row["fatalities"] == 12


def test_reads_all_aggregated_files_and_ignores_others(tmp_path: Path) -> None:
    _write_xlsx(
        tmp_path / "Middle-East_aggregated_data_up_to_week_of-2026-06-13.xlsx",
        [_sample_row()],
    )
    _write_xlsx(
        tmp_path / "Africa_aggregated_data_up_to_week_of-2026-06-13.xlsx",
        [_sample_row(country="Sudan")],
    )
    # country-year summary files must be ignored (different schema)
    _write_xlsx(
        tmp_path / "number_of_political_violence_events_by_country-year_as-of-19Jun2026.xlsx",
        [],
    )
    result = load_acled_weekly(tmp_path)
    assert {row["country"] for row in result.rows} == {"SY", "SD"}
    assert len(result.files_read) == 2


def test_alias_fallback_for_countries_missing_from_geojson(tmp_path: Path) -> None:
    # The shared admin0 geojson lacks several sovereigns ACLED reports on.
    _write_xlsx(
        tmp_path / "X_aggregated_data_up_to_week_of-2026-06-13.xlsx",
        [
            _sample_row(country="Democratic Republic of Congo"),
            _sample_row(country="Norway"),
            _sample_row(country="Kosovo"),
        ],
    )
    result = load_acled_weekly(tmp_path)
    assert {row["country"] for row in result.rows} == {"CD", "NO", "XK"}
    assert not result.unmapped_countries


def test_unmapped_country_skipped_and_reported(tmp_path: Path) -> None:
    _write_xlsx(
        tmp_path / "X_aggregated_data_up_to_week_of-2026-06-13.xlsx",
        [_sample_row(country="Atlantis"), _sample_row()],
    )
    result = load_acled_weekly(tmp_path)
    assert len(result.rows) == 1
    assert result.unmapped_countries == {"Atlantis": 1}


def test_malformed_rows_skipped_and_counted(tmp_path: Path) -> None:
    good = _sample_row()
    missing_week = _sample_row()
    missing_week[0] = None
    missing_events = _sample_row()
    missing_events[6] = None
    _write_xlsx(
        tmp_path / "X_aggregated_data_up_to_week_of-2026-06-13.xlsx",
        [good, missing_week, missing_events],
    )
    result = load_acled_weekly(tmp_path)
    assert len(result.rows) == 1
    assert result.skipped_rows == 2


def test_missing_fatalities_defaults_to_zero(tmp_path: Path) -> None:
    row = _sample_row()
    row[7] = None
    _write_xlsx(tmp_path / "X_aggregated_data_up_to_week_of-2026-06-13.xlsx", [row])
    result = load_acled_weekly(tmp_path)
    assert result.rows[0]["fatalities"] == 0


def test_bogus_declared_dimensions_still_read(tmp_path: Path) -> None:
    # Real ACLED exports declare <dimension ref="A1"/>; openpyxl read-only mode
    # trusts that and yields single-cell rows unless the loader resets dimensions.
    path = tmp_path / "X_aggregated_data_up_to_week_of-2026-06-13.xlsx"
    _write_xlsx(path, [_sample_row()])
    _corrupt_declared_dimensions(path)
    result = load_acled_weekly(tmp_path)
    assert len(result.rows) == 1


def _corrupt_declared_dimensions(path: Path) -> None:
    import re
    import shutil
    import zipfile

    tmp = path.with_suffix(".tmp.xlsx")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = re.sub(rb'<dimension ref="[^"]*"/>', b'<dimension ref="A1"/>', data)
            dst.writestr(item, data)
    shutil.move(tmp, path)


def test_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_acled_weekly(tmp_path / "nope")


def test_dir_without_aggregate_files_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_acled_weekly(tmp_path)
