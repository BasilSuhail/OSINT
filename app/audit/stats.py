"""What the audit measures about one source. No rules here, only the shape."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SourceStats:
    """Measured shape of one source's rows in the events table.

    `severity_top_share` is the fraction of non-null severities taking the most
    common single value — the statistic that exposes a column which is nominally
    continuous but is really a flag. std alone does not: a two-value column split
    evenly has a healthy-looking std.
    """

    source: str
    rows: int
    severity_present: int
    severity_distinct: int
    severity_top_share: float | None
    severity_std: float | None
    country_present: int
    earliest: datetime | None
    latest: datetime | None
    #: Rows that pass the composite's own filter — category in its set, and both
    #: severity and country non-null. Zero here with a source that declares it
    #: feeds the composite means the domain never sees it.
    composite_eligible: int

    @property
    def severity_coverage(self) -> float:
        return self.severity_present / self.rows if self.rows else 0.0

    @property
    def country_coverage(self) -> float:
        return self.country_present / self.rows if self.rows else 0.0
