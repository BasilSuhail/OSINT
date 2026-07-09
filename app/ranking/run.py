"""One-shot CLI — rank every dashboard indicator by measured predictive value.

Usage:
    python -m app.ranking.run
    make indicator-ranking
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.baselines.run import EVAL_END, EVAL_START, HORIZONS
from app.ranking.rank import rank_indicators

INDICATORS: tuple[str, ...] = (
    "signal_market",
    "signal_geopolitical",
    "signal_hazard",
    "composite_score",
)


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def _run() -> int:
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    panel_path = exports / "panel.parquet"
    if not panel_path.exists():
        print(f"{panel_path} not found — run `make panel` first.", file=sys.stderr)
        return 1

    frame = pd.read_parquet(panel_path)
    frame = frame.astype(object).where(pd.notnull(frame), None)
    panel = frame[["country", "month", "label_any", *INDICATORS]].to_dict("records")

    ranked = rank_indicators(
        panel,
        indicators=INDICATORS,
        horizons=HORIZONS,
        eval_start=EVAL_START,
        eval_end=EVAL_END,
    )

    # Strict common support — the fair head-to-head: only rows where every
    # indicator has a value, so no signal wins by cherry-picking its months.
    common_panel = [row for row in panel if all(row.get(ind) is not None for ind in INDICATORS)]
    ranked_common = rank_indicators(
        common_panel,
        indicators=INDICATORS,
        horizons=HORIZONS,
        eval_start=EVAL_START,
        eval_end=EVAL_END,
    )

    report_md = _render_markdown(ranked, ranked_common)
    (exports / "indicator-ranking.md").write_text(report_md)
    (exports / "indicator-ranking.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "eval_window": [EVAL_START.date().isoformat(), EVAL_END.date().isoformat()],
                "indicators": list(INDICATORS),
                "per_indicator_support": ranked,
                "common_support": ranked_common,
            },
            indent=2,
        )
        + "\n"
    )
    print(report_md)
    print(f"written: {exports / 'indicator-ranking.md'} (+ .json)")
    return 0


def _table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| k | rank | indicator | variant | n | pos rate | AUROC | AUPR |",
        "|---|---|---|---|---|---|---|---|",
    ]
    rank = 0
    last_horizon = None
    for row in rows:
        rank = rank + 1 if row["horizon_months"] == last_horizon else 1
        last_horizon = row["horizon_months"]
        lines.append(
            f"| {row['horizon_months']} | {rank} | {row['indicator']} | {row['variant']} "
            f"| {row['n']} | {_fmt(row['positive_rate'])} "
            f"| {_fmt(row['auroc'])} | {_fmt(row['aupr'])} |"
        )
    return lines


def _render_markdown(ranked: list[dict[str, Any]], ranked_common: list[dict[str, Any]]) -> str:
    lines = [
        "# Indicator value ranking — which number predicts best (WS-F)",
        "",
        f"Eval window {EVAL_START.date()} → {EVAL_END.date()}, horizons {HORIZONS}, "
        "target = label_any in [t+1, t+k]. Every indicator takes the same exam the "
        "composite took; `abs` = magnitude variant (deviation signals are two-sided). "
        "No Brier — z-scores are not probabilities.",
        "",
        "## Per-indicator support (each on every month it has a value)",
        "",
        *_table(ranked),
        "",
        "## Strict common support (only months where every indicator exists)",
        "",
        *_table(ranked_common),
        "",
        "Ranking, not aesthetics, decides dashboard prominence — reordering is a "
        "separate frontend task. Same incidence-exam caveat as the baselines report: "
        "per-country base rates ace this target; the deviation signals sit closer to "
        "an onset instrument (see the pinned #282 discussion).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    from app.jobs.heartbeat import job_run

    with job_run("indicator-ranking"):
        rc = _run()
        if rc != 0:
            raise SystemExit(f"indicator-ranking: exited {rc} — see output above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
