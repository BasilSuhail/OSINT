"""One-shot CLI — run the journal body once and print the scoreboard.

Usage:
    python -m app.journal.run
    make journal
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.db_models import PredictionRow
from app.journal.scoreboard import build_scoreboard
from app.journal.task import _journal_daily_body


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def main() -> int:
    counters = _journal_daily_body()

    with Session(get_engine()) as session:
        rows = [
            {
                "source": row.source,
                "method_version": row.method_version,
                "horizon_months": row.horizon_months,
                "score": row.score,
                "outcome": row.outcome,
            }
            for row in session.execute(select(PredictionRow)).scalars()
        ]
    lines = build_scoreboard(rows)

    report = _render_markdown(lines, counters)
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "prediction-journal.md").write_text(report)
    (exports / "prediction-journal.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "run": counters,
                "scoreboard": lines,
            },
            indent=2,
        )
        + "\n"
    )
    print(report)
    print(f"written: {exports / 'prediction-journal.md'} (+ .json)")
    return 0


def _render_markdown(lines: list[dict[str, Any]], counters: dict[str, Any]) -> str:
    out = [
        "# Prediction journal — forward track record (WS-E)",
        "",
        f"This run: {counters['issued']} newly issued, {counters['graded_now']} newly "
        f"graded, {counters['total_predictions']} total on record.",
        "",
        "| source | version | k | issued | graded | pending | pos rate | mean score | Brier |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for line in lines:
        out.append(
            f"| {line['source']} | {line['method_version']} | {line['horizon_months']} "
            f"| {line['issued']} | {line['graded']} | {line['pending']} "
            f"| {_fmt(line['positive_rate'])} | {_fmt(line['mean_score'])} "
            f"| {_fmt(line['brier'])} |"
        )
    out += [
        "",
        "Predictions are immutable once issued (server-stamped, never rewritten). "
        "Grading happens exactly once per prediction, only when its whole window is "
        "past and inside label coverage. Pending counts fall as windows mature.",
        "",
    ]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
