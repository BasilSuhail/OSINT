"""One-shot CLI — the pre-registered within-country evaluation (#582).

Protocol: docs/within-country-eval.md, frozen before this was first run.

Usage:
    python -m app.within.run
    make within-eval
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.baselines.predictors import (
    score_base_rate,
    score_composite,
    score_persistence,
    score_random,
)
from app.baselines.run import EVAL_END, EVAL_START, HORIZONS, RANDOM_SEED
from app.baselines.targets import build_targets
from app.onset.eligibility import onset_eligible
from app.within import metrics

#: Calm windows, reused unchanged from the onset exam (#380).
CALM_PRIMARY: int = 12
CALM_SENSITIVITY: int = 6

#: Pre-registered: a country needs this many of each class for its own AUROC.
MIN_PER_CLASS: int = 3

#: Pre-registered bootstrap settings.
BOOTSTRAP_RESAMPLES: int = 1000

#: Pre-registered decision threshold on the primary metric.
SIGNAL_THRESHOLD: float = 0.55


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def _interval(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "n/a"
    return f"[{low:.3f}, {high:.3f}]"


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
        # Strict common support: every contender is scored on identical rows.
        keys = sorted(
            key
            for key in targets
            if key in eligible and key in composite and EVAL_START <= key[1] <= EVAL_END
        )
        for name, scores in contenders.items():
            records = [
                {"country": key[0], "score": scores[key], "target": targets[key]} for key in keys
            ]
            concordance = metrics.within_country_concordance(records)
            low, high = metrics.bootstrap_ci(
                records,
                metrics.within_country_concordance,
                resamples=BOOTSTRAP_RESAMPLES,
                seed=RANDOM_SEED,
            )
            rows.append(
                {
                    "calm_months": calm_months,
                    "contender": name,
                    "horizon_months": horizon,
                    "n": len(records),
                    "countries_with_pairs": _countries_with_pairs(records),
                    "concordance": concordance,
                    "ci_low": low,
                    "ci_high": high,
                    "mean_country_auroc": metrics.mean_per_country_auroc(
                        records, min_per_class=MIN_PER_CLASS
                    ),
                    "qualifying_countries": metrics.qualifying_countries(
                        records, min_per_class=MIN_PER_CLASS
                    ),
                }
            )
    return rows


def _countries_with_pairs(records: list[dict[str, Any]]) -> int:
    """Countries carrying both classes — the ones the primary metric can use."""
    by_country: dict[str, set[int]] = {}
    for record in records:
        by_country.setdefault(record["country"], set()).add(int(record["target"]))
    return sum(1 for classes in by_country.values() if len(classes) == 2)


def _verdict(primary: list[dict[str, Any]]) -> str:
    """The pre-registered decision rule, applied mechanically."""
    composite = [r for r in primary if r["contender"] == "B6 composite"]
    base = {r["horizon_months"]: r for r in primary if r["contender"] == "B2 base rate"}
    for row in composite:
        value, low = row["concordance"], row["ci_low"]
        rival = base[row["horizon_months"]]["concordance"]
        if value is None or low is None or rival is None:
            continue
        if value > SIGNAL_THRESHOLD and low > 0.5 and value > rival:
            return (
                f"**SIGNAL** — composite {value:.3f} at k={row['horizon_months']}, "
                f"CI low {low:.3f} > 0.5, above B2 {rival:.3f}."
            )
    return (
        "**NEGATIVE** — no horizon met the pre-registered rule "
        f"(concordance > {SIGNAL_THRESHOLD}, CI excluding 0.5, above B2)."
    )


def _table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| contender | k | n | countries | concordance | 95% CI | "
        "mean country AUROC | qualifying |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['contender']} | {row['horizon_months']} | {row['n']} | "
            f"{row['countries_with_pairs']} | {_fmt(row['concordance'])} | "
            f"{_interval(row['ci_low'], row['ci_high'])} | "
            f"{_fmt(row['mean_country_auroc'])} | {row['qualifying_countries']} |"
        )
    return lines


def _render_markdown(primary: list[dict[str, Any]], sensitivity: list[dict[str, Any]]) -> str:
    return "\n".join(
        [
            "# Within-country evaluation — result",
            "",
            f"Generated {datetime.now(UTC).isoformat()}. Protocol: "
            "`docs/within-country-eval.md`, fixed before this ran.",
            "",
            f"## Primary — calm window {CALM_PRIMARY} months",
            "",
            *_table(primary),
            "",
            f"## Sensitivity — calm window {CALM_SENSITIVITY} months",
            "",
            *_table(sensitivity),
            "",
            "## Verdict (pre-registered rule, applied mechanically)",
            "",
            _verdict(primary),
            "",
            "A null here does not separate 'the composite's construction carries "
            "no signal' from 'the inputs carry no signal'. #580 found severity "
            "near-degenerate across nearly every source and #579 that the FIRMS "
            "value is the wrong quantity — see the protocol's interpretation limits.",
            "",
        ]
    )


def _run() -> int:
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    panel_path = exports / "panel.parquet"
    if not panel_path.exists():
        print(f"{panel_path} not found — run `make panel` first.", file=sys.stderr)
        return 1

    frame = pd.read_parquet(panel_path)
    frame = frame.astype(object).where(pd.notnull(frame), None)
    panel = frame[["country", "month", "label_any", "composite_score"]].to_dict("records")

    primary = _evaluate(panel, calm_months=CALM_PRIMARY)
    sensitivity = _evaluate(panel, calm_months=CALM_SENSITIVITY)

    (exports / "within-country-eval.md").write_text(_render_markdown(primary, sensitivity))
    (exports / "within-country-eval.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "protocol": "docs/within-country-eval.md",
                "primary": primary,
                "sensitivity": sensitivity,
            },
            indent=2,
            default=str,
        )
    )
    print(_render_markdown(primary, sensitivity))
    return 0


def main() -> int:
    from app.jobs.heartbeat import job_run

    with job_run("within-eval"):
        return _run()


if __name__ == "__main__":
    raise SystemExit(main())
