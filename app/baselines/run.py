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
from app.baselines.predictors import (
    score_base_rate,
    score_composite,
    score_persistence,
    score_random,
)
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
    panel = frame[["country", "month", "label_any", "composite_score"]].to_dict("records")

    baselines = {
        "B0 random": score_random(panel, seed=RANDOM_SEED),
        "B1 persistence": score_persistence(panel),
        "B2 base rate": score_base_rate(panel),
    }
    composite = score_composite(panel)

    def _score_rows(
        name: str, scores: dict, keys: list, y: list[int], horizon: int
    ) -> dict[str, Any]:
        s = [scores[key] for key in keys]
        return {
            "baseline": name,
            "horizon_months": horizon,
            "n": len(y),
            "positive_rate": round(sum(y) / len(y), 4) if y else None,
            "auroc": auroc(s, y),
            "aupr": aupr(s, y),
            "brier": brier(s, y),
        }

    results: list[dict[str, Any]] = []
    head_to_head: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        targets = build_targets(panel, horizon=horizon)
        eval_keys = sorted(key for key in targets if EVAL_START <= key[1] <= EVAL_END)
        y = [targets[key] for key in eval_keys]
        for name, scores in baselines.items():
            results.append(_score_rows(name, scores, eval_keys, y, horizon))

        # Head-to-head on common support: only rows where the composite has a
        # value, with the no-skill trio recomputed on the same rows.
        common = [key for key in eval_keys if key in composite]
        y_common = [targets[key] for key in common]
        for name, scores in {**baselines, "B6 composite": composite}.items():
            head_to_head.append(_score_rows(name, scores, common, y_common, horizon))

    eval_frame = frame[(frame["month"] >= EVAL_START) & (frame["month"] <= EVAL_END)]
    code_rates = {
        code: round(float(eval_frame[code].mean()), 4)
        for code in ("label_p1", "label_p2", "label_p3", "label_any")
    }

    report_md = _render_markdown(results, head_to_head, code_rates, len(eval_frame))
    (exports / "baselines-report.md").write_text(report_md)
    (exports / "baselines-report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "eval_window": [EVAL_START.date().isoformat(), EVAL_END.date().isoformat()],
                "random_seed": RANDOM_SEED,
                "code_positive_rates": code_rates,
                "results": results,
                "head_to_head_common_support": head_to_head,
            },
            indent=2,
        )
        + "\n"
    )
    print(report_md)
    print(f"written: {exports / 'baselines-report.md'} (+ .json)")
    return 0


def _table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| baseline | k | n | pos rate | AUROC | AUPR | Brier |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['baseline']} | {row['horizon_months']} | {row['n']} "
            f"| {row['positive_rate']} | {_fmt(row['auroc'])} "
            f"| {_fmt(row['aupr'])} | {_fmt(row['brier'])} |"
        )
    return lines


def _render_markdown(
    results: list[dict[str, Any]],
    head_to_head: list[dict[str, Any]],
    code_rates: dict[str, float],
    eval_rows: int,
) -> str:
    full_n = results[0]["n"] if results else 0
    common_n = head_to_head[0]["n"] if head_to_head else 0
    coverage = f"{common_n / full_n:.0%}" if full_n else "n/a"
    lines = [
        "# Baseline report — no-skill trio + composite on the country-month panel",
        "",
        f"Eval window **2015-01 → 2022-12** ({eval_rows} country-months). The 2023-2024",
        "test window is untouched per the pre-registered protocol (methodology.md).",
        "",
        "## Full panel — B0 / B1 / B2",
        "",
        *_table(results),
        "",
        "Per-code positive rates in the eval window: "
        + ", ".join(f"{code} = {rate}" for code, rate in code_rates.items()),
        "",
        "## Head-to-head on common support — B6 composite vs the trio",
        "",
        f"Restricted to eval-window rows where the composite has a value "
        f"({common_n} of {full_n} rows at k=1, {coverage} coverage); B0-B2 recomputed "
        "on the same rows so the comparison is apples-to-apples.",
        "",
        *_table(head_to_head),
        "",
        "**Reading**: the composite carries all three domains (market + "
        "geopolitical + hazard; GDELT-backfilled, #331). A coin-flip AUROC "
        "against a ~0.93 per-country base rate is a statement about "
        "construction, not about signal absence: rolling within-country "
        "z-scores deliberately remove the cross-sectional differences that "
        "dominate P1-P3 *incidence* (chronically conflicted countries stay "
        "positive month after month, and the base rate collects exactly "
        "that). What the composite measures is deviation from a country's "
        "own baseline — an *onset/escalation*-shaped signal. The natural "
        "next evaluation, to be pre-registered before running, restricts "
        "scoring to onset months (no positive in the preceding window), "
        "where per-country base rates lose their advantage by construction.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
