"""Compare two narrative sources on the window where both exist (#557).

The gate's negative result was measured against DOC API article volume. #555
produces a different quantity — coded event rows from the raw export grid — and
the two are not interchangeable on faith. If they disagree, swapping the source
silently changes what the gate measures and no result survives the swap.

Two numbers, and the second is the one that matters:

- **Spearman** on the daily series, because the archive counts mentions in the
  thousands where the DOC API counts articles in the tens. Only the ordering is
  comparable, so a rank correlation is the honest measure.
- **Spike-day agreement**, because the gate does not consume volume. It
  consumes `detect_lead`'s first narrative spike. Two series can correlate at
  0.95 and still disagree about the only day the gate reads, and a one-day
  disagreement is the whole quantity the gate is trying to measure.

Spike days are found with the gate's own scaling, window and threshold, so what
is compared here is what the gate would actually see.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.divergence.config import LOG_CEILING_NARRATIVE, ROLLING_WINDOW_DAYS, TAU_N
from app.divergence.scoring import _log_scale, rolling_z


@dataclass(frozen=True)
class Comparison:
    """How two narrative series for one country relate over one window."""

    days: int
    spearman: float | None
    doc_spike_day: date | None
    archive_spike_day: date | None
    spike_gap_days: int | None


def _midranks(values: list[float]) -> list[float]:
    """Ranks with ties averaged — quiet days tie at zero constantly."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2 + 1
        for index in order[position : end + 1]:
            ranks[index] = shared
        position = end + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    """Rank correlation, or None when either series is flat.

    A flat series has no ordering to correlate, and reporting 0.0 for it would
    read as "unrelated" rather than "unmeasurable".
    """
    if len(a) != len(b):
        raise ValueError("series must be the same length")
    if len(a) < 2:
        raise ValueError("need at least two points to correlate")

    rank_a = _midranks(a)
    rank_b = _midranks(b)
    n = len(a)
    mean_a = sum(rank_a) / n
    mean_b = sum(rank_b) / n
    da = [r - mean_a for r in rank_a]
    db = [r - mean_b for r in rank_b]
    denominator = (sum(x * x for x in da) ** 0.5) * (sum(x * x for x in db) ** 0.5)
    if denominator == 0:
        return None
    return sum(x * y for x, y in zip(da, db, strict=True)) / denominator


def first_spike_day(days: list[date], values: list[float], *, tau: float = TAU_N) -> date | None:
    """The day `detect_lead` would call this series' first narrative spike."""
    scaled = [_log_scale(v, LOG_CEILING_NARRATIVE) for v in values]
    z_scores = rolling_z(scaled, ROLLING_WINDOW_DAYS)
    index = next((i for i, z in enumerate(z_scores) if z >= tau), None)
    return None if index is None else days[index]


def compare(
    days: list[date], doc: list[float], archive: list[float], *, tau: float = TAU_N
) -> Comparison:
    """Correlation and spike-day agreement between two aligned series."""
    if not (len(days) == len(doc) == len(archive)):
        raise ValueError("days, doc and archive must be equal length")
    if len(days) <= ROLLING_WINDOW_DAYS:
        raise ValueError(
            f"need more than {ROLLING_WINDOW_DAYS} days to establish a baseline; "
            f"got {len(days)}. A shorter window cannot spike at all, so its "
            "spike days would agree without ever having been measured."
        )

    doc_spike = first_spike_day(days, doc, tau=tau)
    archive_spike = first_spike_day(days, archive, tau=tau)
    gap = None if doc_spike is None or archive_spike is None else (archive_spike - doc_spike).days
    return Comparison(
        days=len(days),
        spearman=spearman(doc, archive),
        doc_spike_day=doc_spike,
        archive_spike_day=archive_spike,
        spike_gap_days=gap,
    )
