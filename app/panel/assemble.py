"""Assemble layer — spine + label rows + score rows → panel records.

Pure functions only. Inputs are plain dicts (from DB queries or tests); output
is a list of pandas-ready records with None for missing values.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

_LABEL_CODES = ("P1", "P2", "P3")
_SIGNAL_DOMAINS = ("market", "geopolitical", "hazard")


def _month_key(dt: datetime) -> datetime:
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return datetime(dt.year, dt.month, 1, tzinfo=UTC)


def assemble_panel(
    spine: Iterable[Mapping[str, Any]],
    label_rows: Iterable[Mapping[str, Any]],
    score_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Join labels and scores onto the spine; rows outside the spine are dropped."""
    labels: dict[tuple[str, datetime], dict[str, float]] = {}
    for row in label_rows:
        code = row["label_code"]
        if code not in _LABEL_CODES:
            continue
        key = (row["country"], _month_key(row["bucket_start"]))
        labels.setdefault(key, {})[code] = float(row["magnitude"])

    scores: dict[tuple[str, datetime], Mapping[str, Any]] = {
        (row["country"], _month_key(row["bucket_start"])): row for row in score_rows
    }

    panel: list[dict[str, Any]] = []
    for cell in spine:
        key = (cell["country"], cell["month"])
        cell_labels = labels.get(key, {})
        score = scores.get(key)
        z = (score or {}).get("components", {}).get("z", {})
        record: dict[str, Any] = {
            "country": cell["country"],
            "month": cell["month"],
            "label_any": int(bool(cell_labels)),
        }
        for code in _LABEL_CODES:
            record[f"label_{code.lower()}"] = int(code in cell_labels)
            record[f"magnitude_{code.lower()}"] = cell_labels.get(code)
        for domain in _SIGNAL_DOMAINS:
            value = z.get(domain)
            record[f"signal_{domain}"] = float(value) if value is not None else None
        record["composite_score"] = float(score["score_value"]) if score else None
        record["method_version"] = score["method_version"] if score else None
        panel.append(record)
    return panel
