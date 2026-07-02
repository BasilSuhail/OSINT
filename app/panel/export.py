"""Export layer — panel records → parquet + csv + meta json.

Overwrites in place: the DB is the source of truth and the export is
reproducible. `panel-meta.json` states exactly what a given build contains so
any downstream analysis can cite it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

_COLUMNS: dict[str, str] = {
    "country": "string",
    "label_p1": "int8",
    "label_p2": "int8",
    "label_p3": "int8",
    "label_any": "int8",
    "magnitude_p1": "float64",
    "magnitude_p2": "float64",
    "magnitude_p3": "float64",
    "signal_market": "float64",
    "signal_geopolitical": "float64",
    "signal_hazard": "float64",
    "composite_score": "float64",
    "method_version": "string",
}


def export_panel(records: list[dict[str, Any]], out_dir: Path | str) -> dict[str, Any]:
    """Write panel.parquet, panel.csv and panel-meta.json; return the meta dict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    frame = pd.DataFrame(records, columns=["month", *_COLUMNS])
    frame["month"] = pd.to_datetime(frame["month"], utc=True)
    frame = frame.astype(_COLUMNS)
    frame = frame.sort_values(["country", "month"]).reset_index(drop=True)
    frame = frame[["country", "month", *(c for c in _COLUMNS if c != "country")]]

    frame.to_parquet(out_dir / "panel.parquet", index=False)
    frame.to_csv(out_dir / "panel.csv", index=False)

    label_cols = ["label_p1", "label_p2", "label_p3", "label_any"]
    meta: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "rows": len(frame),
        "countries": int(frame["country"].nunique()),
        "span": (
            [
                frame["month"].min().date().isoformat(),
                frame["month"].max().date().isoformat(),
            ]
            if len(frame)
            else None
        ),
        "label_counts": {col: int(frame[col].sum()) for col in label_cols},
        "score_rows": int(frame["composite_score"].notna().sum()),
        "method_versions": sorted(frame["method_version"].dropna().unique().tolist()),
    }
    (out_dir / "panel-meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta
