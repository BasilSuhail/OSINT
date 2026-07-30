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

    Absent domains are excluded and the remaining weights renormalised, so a
    country scored on two domains is scored on two domains (#683). They used to
    enter the sum as z=0.0 — "exactly average" — which is a different claim from
    "we do not know". Every imputed zero pulled the weighted sum toward 0 and
    the score toward `sigmoid(0) = 0.5`, hardest for the countries missing the
    most data, which are the quiet ones the index most needs to discriminate.

    A domain present with value 0.0 is a measurement and still dilutes. Only
    absence is excluded. A cell with no known domains is not scored at all —
    there is nothing to renormalise over, and emitting sigmoid(0) there would be
    the same imputation wearing a different hat.

    `components` records which domains were present and the renormalised weight
    each received, so a stored score can be audited without re-deriving it.
    """
    weights = weights or WeightingConfig()
    method_version = method_version or weights.method_version or DEFAULT_METHOD_VERSION

    weight_dict = weights.as_dict()

    out: list[ComposedScore] = []
    for (country, bucket_start), domain_z in normalized_signals.items():
        present = {d: w for d, w in weight_dict.items() if d in domain_z}
        weight_total = sum(present.values())
        # No known domain, or every present domain carries zero weight: there is
        # no composite to compute. Refusing beats inventing one (#589).
        if not present or weight_total <= 0.0:
            continue

        contributions: dict[str, float] = {}
        weights_used: dict[str, float] = {}
        weighted_sum = 0.0
        for domain, weight in present.items():
            renormalised = weight / weight_total
            z = float(domain_z[domain])
            weights_used[domain] = renormalised
            contributions[domain] = renormalised * z
            weighted_sum += renormalised * z

        score_value = _sigmoid(weighted_sum)
        out.append(
            ComposedScore(
                country=country,
                bucket_start=bucket_start,
                bucket_length=MONTH_BUCKET,
                score_name=score_name,
                score_value=score_value,
                components={
                    "z": {d: float(domain_z[d]) for d in present},
                    "contribution": contributions,
                    "weighted_sum": weighted_sum,
                    "weights_used": weights_used,
                    "domains_present": sorted(present),
                },
                method_version=method_version,
            )
        )
    return out
