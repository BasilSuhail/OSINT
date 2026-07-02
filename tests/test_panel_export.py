"""Tests for `app.panel.export` — records → parquet + csv + meta json."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.panel.export import export_panel


def _record(month: datetime, *, label: int = 0) -> dict:
    return {
        "country": "SY",
        "month": month,
        "label_p1": label,
        "label_p2": 0,
        "label_p3": 0,
        "label_any": label,
        "magnitude_p1": 12.0 if label else None,
        "magnitude_p2": None,
        "magnitude_p3": None,
        "signal_market": None,
        "signal_geopolitical": None,
        "signal_hazard": None,
        "composite_score": None,
        "method_version": None,
    }


def test_writes_parquet_csv_and_meta(tmp_path: Path) -> None:
    records = [
        _record(datetime(2024, 1, 1, tzinfo=UTC), label=1),
        _record(datetime(2024, 2, 1, tzinfo=UTC)),
    ]
    meta = export_panel(records, tmp_path)
    assert (tmp_path / "panel.parquet").exists()
    assert (tmp_path / "panel.csv").exists()
    assert (tmp_path / "panel-meta.json").exists()
    assert meta["rows"] == 2


def test_parquet_round_trip_preserves_dtypes(tmp_path: Path) -> None:
    export_panel([_record(datetime(2024, 1, 1, tzinfo=UTC), label=1)], tmp_path)
    df = pd.read_parquet(tmp_path / "panel.parquet")
    assert str(df["label_p1"].dtype) == "int8"
    assert str(df["magnitude_p1"].dtype) == "float64"
    assert df["month"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC")
    assert df["country"].iloc[0] == "SY"


def test_meta_contents(tmp_path: Path) -> None:
    export_panel(
        [
            _record(datetime(2024, 1, 1, tzinfo=UTC), label=1),
            _record(datetime(2024, 2, 1, tzinfo=UTC)),
        ],
        tmp_path,
    )
    meta = json.loads((tmp_path / "panel-meta.json").read_text())
    assert meta["rows"] == 2
    assert meta["countries"] == 1
    assert meta["label_counts"]["label_p1"] == 1
    assert meta["span"] == ["2024-01-01", "2024-02-01"]
    assert "generated_at" in meta


def test_creates_output_dir(tmp_path: Path) -> None:
    out = tmp_path / "exports" / "nested"
    export_panel([_record(datetime(2024, 1, 1, tzinfo=UTC))], out)
    assert (out / "panel.parquet").exists()


def test_empty_records_still_writes_files(tmp_path: Path) -> None:
    meta = export_panel([], tmp_path)
    assert meta["rows"] == 0
    assert (tmp_path / "panel.parquet").exists()
