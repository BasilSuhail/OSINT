"""Composite scoring — weighted z-scores → sigmoid → [0, 1] score.

Pure function. The Celery task in `app.composite.task` orchestrates HTTP-of-DB
around this.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.composite.config import DEFAULT_METHOD_VERSION, WeightingConfig

#: Monthly bucket length. Stored on the scores row so future evaluators can
#: filter on it without parsing semantics.
MONTH_BUCKET: timedelta = timedelta(days=30)


class ComposedScore(BaseModel):
    """One row destined for the scores table."""

    model_config = ConfigDict(extra="forbid")

    country: str = Field(..., min_length=2, max_length=2)
    bucket_start: datetime
    bucket_length: timedelta
    score_name: str
    score_value: float = Field(..., ge=0.0, le=1.0)
    components: dict[str, Any]
    method_version: str


def _sigmoid(x: float) -> float:
    """Map an unbounded weighted z to [0, 1] for the scores table."""
    if x >= 0:
        # Numerically stable for positive x.
        e = math.exp(-x)
        return 1.0 / (1.0 + e)
    e = math.exp(x)
    return e / (1.0 + e)


def compute_scores(
    normalized_signals: dict[tuple[str, datetime], dict[str, float]],
    weights: WeightingConfig | None = None,
    *,
    score_name: str = "composite",
    method_version: str | None = None,
) -> list[ComposedScore]:
    """Combine per-domain z-scores into a [0, 1] composite per (country, month).

    Missing domains in the inner dict are treated as z=0 (no contribution).
    The components field stores both the per-domain z used and the weighted
    contribution for downstream interpretability.
    """
    weights = weights or WeightingConfig()
    method_version = method_version or weights.method_version or DEFAULT_METHOD_VERSION

    weight_dict = weights.as_dict()

    out: list[ComposedScore] = []
    for (country, bucket_start), domain_z in normalized_signals.items():
        # Default missing domains to 0 so the composite is well-defined on
        # cold starts and gappy inputs.
        contributions: dict[str, float] = {}
        weighted_sum = 0.0
        for domain, weight in weight_dict.items():
            z = float(domain_z.get(domain, 0.0))
            contributions[domain] = weight * z
            weighted_sum += weight * z

        score_value = _sigmoid(weighted_sum)
        out.append(
            ComposedScore(
                country=country,
                bucket_start=bucket_start,
                bucket_length=MONTH_BUCKET,
                score_name=score_name,
                score_value=score_value,
                components={
                    "z": {d: float(domain_z.get(d, 0.0)) for d in weight_dict},
                    "contribution": contributions,
                    "weighted_sum": weighted_sum,
                },
                method_version=method_version,
            )
        )
    return out
