"""One-shot CLI — score B0/B1/B2 on the panel and write the report.

Usage:
    python -m app.baselines.run       # reads $OSINT_DATA_DIR/exports/panel.parquet
    make baselines

Eval window 2015-01 → 2022-12 (train + validation years). The 2023-2024 test
window stays untouched per the pre-registered protocol in docs/methodology.md.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.baselines.metrics import aupr, auroc, brier
from app.baselines.predictors import score_base_rate, score_persistence, score_random
from app.baselines.targets import build_targets

EVAL_START = datetime(2015, 1, 1, tzinfo=UTC)
EVAL_END = datetime(2022, 12, 1, tzinfo=UTC)
HORIZONS = (1, 3, 6)
RANDOM_SEED = 20260703


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def main() -> int:
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    panel_path = exports / "panel.parquet"
    if not panel_path.exists():
        print(f"{panel_path} not found — run `make panel` first.", file=sys.stderr)
        return 1

    frame = pd.read_parquet(panel_path)
    panel = frame[["country", "month", "label_any"]].to_dict("records")

    baselines = {
        "B0 random": score_random(panel, seed=RANDOM_SEED),
        "B1 persistence": score_persistence(panel),
        "B2 base rate": score_base_rate(panel),
    }

    results: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        targets = build_targets(panel, horizon=horizon)
        eval_keys = sorted(key for key in targets if EVAL_START <= key[1] <= EVAL_END)
        y = [targets[key] for key in eval_keys]
        for name, scores in baselines.items():
            s = [scores[key] for key in eval_keys]
            results.append(
                {
                    "baseline": name,
                    "horizon_months": horizon,
                    "n": len(y),
                    "positive_rate": round(sum(y) / len(y), 4) if y else None,
                    "auroc": auroc(s, y),
                    "aupr": aupr(s, y),
                    "brier": brier(s, y),
                }
            )

    eval_frame = frame[(frame["month"] >= EVAL_START) & (frame["month"] <= EVAL_END)]
    code_rates = {
        code: round(float(eval_frame[code].mean()), 4)
        for code in ("label_p1", "label_p2", "label_p3", "label_any")
    }

    report_md = _render_markdown(results, code_rates, len(eval_frame))
    (exports / "baselines-report.md").write_text(report_md)
    (exports / "baselines-report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "eval_window": [EVAL_START.date().isoformat(), EVAL_END.date().isoformat()],
                "random_seed": RANDOM_SEED,
                "code_positive_rates": code_rates,
                "results": results,
            },
            indent=2,
        )
        + "\n"
    )
    print(report_md)
    print(f"written: {exports / 'baselines-report.md'} (+ .json)")
    return 0


def _render_markdown(
    results: list[dict[str, Any]], code_rates: dict[str, float], eval_rows: int
) -> str:
    lines = [
        "# Baseline report — B0 / B1 / B2 on the country-month panel",
        "",
        f"Eval window **2015-01 → 2022-12** ({eval_rows} country-months). The 2023-2024",
        "test window is untouched per the pre-registered protocol (methodology.md).",
        "",
        "| baseline | k | n | pos rate | AUROC | AUPR | Brier |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in results:
        lines.append(
            f"| {row['baseline']} | {row['horizon_months']} | {row['n']} "
            f"| {row['positive_rate']} | {_fmt(row['auroc'])} "
            f"| {_fmt(row['aupr'])} | {_fmt(row['brier'])} |"
        )
    lines += [
        "",
        "Per-code positive rates in the eval window: "
        + ", ".join(f"{code} = {rate}" for code, rate in code_rates.items()),
        "",
        "**Composite not scored**: only the live deployment's score rows exist "
        "(no historical signals). Scoring the composite requires the #250 "
        "historical backfill. These baseline numbers are the bar it must clear.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
