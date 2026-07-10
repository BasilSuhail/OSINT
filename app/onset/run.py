"""One-shot CLI — the pre-registered onset evaluation (#380).

Protocol: docs/onset-eval.md, frozen before this was first run.

Usage:
    python -m app.onset.run
    make onset-eval
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.baselines.metrics import aupr, auroc
from app.baselines.predictors import (
    score_base_rate,
    score_composite,
    score_persistence,
    score_random,
)
from app.baselines.run import EVAL_END, EVAL_START, HORIZONS, RANDOM_SEED
from app.baselines.targets import build_targets
from app.onset.eligibility import onset_eligible
from app.ranking.rank import rank_indicators

#: Primary calm window (months) — pre-registered; 6 is the declared sensitivity.
CALM_PRIMARY: int = 12
CALM_SENSITIVITY: int = 6

_INDICATORS = ("signal_market", "signal_geopolitical", "signal_hazard", "composite_score")


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def _evaluate(panel: list[dict[str, Any]], *, calm_months: int) -> list[dict[str, Any]]:
    eligible = onset_eligible(panel, calm_months=calm_months)
    contenders = {
        "B0 random": score_random(panel, seed=RANDOM_SEED),
        "B1 persistence": score_persistence(panel),
        "B2 base rate": score_base_rate(panel),
        "B6 composite": score_composite(panel),
    }
    composite = contenders["B6 composite"]

    rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        targets = build_targets(panel, horizon=horizon)
        keys = sorted(
            key
            for key in targets
            if key in eligible and key in composite and EVAL_START <= key[1] <= EVAL_END
        )
        y = [targets[key] for key in keys]
        for name, scores in contenders.items():
            s = [scores[key] for key in keys]
            rows.append(
                {
                    "calm_months": calm_months,
                    "contender": name,
                    "horizon_months": horizon,
                    "n": len(y),
                    "positive_rate": round(sum(y) / len(y), 4) if y else None,
                    "auroc": auroc(s, y),
                    "aupr": aupr(s, y),
                }
            )
    return rows


def _run() -> int:
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    panel_path = exports / "panel.parquet"
    if not panel_path.exists():
        print(f"{panel_path} not found — run `make panel` first.", file=sys.stderr)
        return 1

    frame = pd.read_parquet(panel_path)
    frame = frame.astype(object).where(pd.notnull(frame), None)
    panel = frame[["country", "month", "label_any", *_INDICATORS]].to_dict("records")

    primary = _evaluate(panel, calm_months=CALM_PRIMARY)
    sensitivity = _evaluate(panel, calm_months=CALM_SENSITIVITY)

    # Declared secondary (exploratory): the WS-F variants on the primary
    # onset support — context for the headline, never the headline.
    eligible = onset_eligible(panel, calm_months=CALM_PRIMARY)
    onset_panel = [row for row in panel if (row["country"], row["month"]) in eligible]
    secondary = rank_indicators(
        onset_panel,
        indicators=_INDICATORS,
        horizons=HORIZONS,
        eval_start=EVAL_START,
        eval_end=EVAL_END,
    )

    report_md = _render_markdown(primary, sensitivity, secondary)
    (exports / "onset-eval-report.md").write_text(report_md)
    (exports / "onset-eval-report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "protocol": "docs/onset-eval.md",
                "eval_window": [EVAL_START.date().isoformat(), EVAL_END.date().isoformat()],
                "calm_primary_months": CALM_PRIMARY,
                "calm_sensitivity_months": CALM_SENSITIVITY,
                "primary": primary,
                "sensitivity": sensitivity,
                "secondary_exploratory": secondary,
            },
            indent=2,
        )
        + "\n"
    )
    print(report_md)
    print(f"written: {exports / 'onset-eval-report.md'} (+ .json)")
    return 0


def _table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| k | contender | n | pos rate | AUROC | AUPR |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['horizon_months']} | {row['contender']} | {row['n']} "
            f"| {_fmt(row['positive_rate'])} | {_fmt(row['auroc'])} | {_fmt(row['aupr'])} |"
        )
    return lines


def _render_markdown(
    primary: list[dict[str, Any]],
    sensitivity: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
) -> str:
    lines = [
        "# Onset evaluation — the composite's real exam (#380)",
        "",
        "Protocol pre-registered in `docs/onset-eval.md` before the first run. "
        "Onset months only: country-months whose preceding calm window has no "
        "positive label and full coverage (month t itself is unconstrained — "
        "see amendment A1). Strict common support with the composite.",
        "",
        f"## Primary — {CALM_PRIMARY}-month calm window",
        "",
        *_table(primary),
        "",
        f"## Sensitivity — {CALM_SENSITIVITY}-month calm window (declared)",
        "",
        *_table(sensitivity),
        "",
        "## Secondary (exploratory, declared) — WS-F variants on the primary onset support",
        "",
        "| k | rank | indicator | variant | n | AUROC | AUPR |",
        "|---|---|---|---|---|---|---|",
    ]
    rank = 0
    last_horizon = None
    for row in secondary:
        rank = rank + 1 if row["horizon_months"] == last_horizon else 1
        last_horizon = row["horizon_months"]
        lines.append(
            f"| {row['horizon_months']} | {rank} | {row['indicator']} | {row['variant']} "
            f"| {row['n']} | {_fmt(row['auroc'])} | {_fmt(row['aupr'])} |"
        )
    lines += [
        "",
        "Read AUPR against the onset positive rate above, not the incidence exam's. "
        "The result stands as published whatever it says — see #282 for the trail.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    from app.jobs.heartbeat import job_run

    with job_run("onset-eval"):
        rc = _run()
        if rc != 0:
            raise SystemExit(f"onset-eval: exited {rc} — see output above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
