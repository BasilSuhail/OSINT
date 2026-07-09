"""The WS-B forward exam — divergence exposures for the prediction journal (#374).

Pre-registered in docs/disagreement-exam.md. The signal, declared:

    exposure(country, month) = story-count-weighted mean of mean_divergence
                               over that month's pairs containing the country

Already in [0, 1]; used as the prediction score directly — no calibration
knobs. Divergence data exists only from July 2026 (RSS era), so unlike the
composite there is no historical backtest: this is a forward exam with the
same discipline as WS-E — log before the outcome is knowable, grade when the
window matures, publish whatever accumulates.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from app.disagreement.tellings import METHOD_VERSION


def divergence_exposures(pair_rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """disagreement_pairs-shaped rows → composite-score-shaped exposure dicts.

    Output feeds `journal.emit.predictions_from_scores` unchanged: country,
    bucket_start, score_value, components, method_version.
    """
    weighted: dict[tuple[str, datetime], dict[str, float]] = {}
    for row in pair_rows:
        month = datetime(row["month"].year, row["month"].month, 1, tzinfo=UTC)
        for country in (row["country_a"], row["country_b"]):
            slot = weighted.setdefault((country, month), {"sum": 0.0, "n_stories": 0, "n_pairs": 0})
            slot["sum"] += row["mean_divergence"] * row["n_stories"]
            slot["n_stories"] += row["n_stories"]
            slot["n_pairs"] += 1

    return [
        {
            "country": country,
            "bucket_start": month,
            "score_value": slot["sum"] / slot["n_stories"],
            "components": {"n_pairs": int(slot["n_pairs"]), "n_stories": int(slot["n_stories"])},
            "method_version": METHOD_VERSION,
        }
        for (country, month), slot in sorted(weighted.items())
    ]
