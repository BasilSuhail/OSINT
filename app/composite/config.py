"""Configuration models for the composite worker.

`method_version` is the lock against silently changing the methodology
mid-evaluation. Each WeightingConfig must declare its method_version so the
scores table can carry the rows alongside other versions for ablations.
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Method version stamp emitted on every composite row. Changes to weights,
#: normalisation or aggregation produce a new version — never an in-place edit.
#:
#: v2.0 (#574): the domain signal became the month's strongest event rather
#: than the mean, and FIRMS severity started parsing at all. VIIRS reports
#: confidence as l/n/h and only low/nominal/high were mapped, so all 536,097
#: rows carried severity NULL and were skipped by the aggregator — 99.8% of the
#: hazard domain absent from every score ever computed. Scores either side of
#: this line are not comparable, hence the bump rather than an edit.
DEFAULT_METHOD_VERSION: str = "v2.0"


class WeightingConfig(BaseModel):
    """Per-domain composite weights.

    Weights are normalised to sum to 1 at validation time so the composite
    raw value is bounded regardless of the absolute weights an experimenter
    types in.
    """

    model_config = ConfigDict(extra="forbid")

    market: float = Field(default=1.0 / 3.0, ge=0.0)
    geopolitical: float = Field(default=1.0 / 3.0, ge=0.0)
    hazard: float = Field(default=1.0 / 3.0, ge=0.0)
    method_version: str = Field(default=DEFAULT_METHOD_VERSION)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> WeightingConfig:
        total = self.market + self.geopolitical + self.hazard
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            if total <= 0:
                raise ValueError("at least one weight must be > 0")
            self.market /= total
            self.geopolitical /= total
            self.hazard /= total
        return self

    def as_dict(self) -> dict[str, float]:
        return {
            "market": self.market,
            "geopolitical": self.geopolitical,
            "hazard": self.hazard,
        }
