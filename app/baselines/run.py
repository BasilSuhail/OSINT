"""One-shot CLI — score every baseline on the panel and write the report.

Usage:
    python -m app.baselines.run       # reads $OSINT_DATA_DIR/exports/panel.parquet
    make baselines

Scores B0-B6 over two windows, reported separately and never pooled:
train+validation 2015-01 → 2022-12, and the held-out test window
2023-01 → 2024-12.

The claim this decides is the project's headline one — that combining three
domains discriminates later instability better than the best single domain.
Until B3/B4/B5 existed it could not be evaluated at all: what had been
measured was the composite against the no-skill trio, which is a different and
much weaker question.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from app.baselines.metrics import aupr, auroc, brier
from app.baselines.predictors import (
    DOMAIN_COLUMNS,
    score_base_rate,
    score_composite,
    score_domain,
    score_persistence,
    score_random,
)
from app.baselines.targets import build_targets
from app.baselines.verdict import judge_claim
from app.paths import exports_dir

EVAL_START = datetime(2015, 1, 1, tzinfo=UTC)
EVAL_END = datetime(2022, 12, 1, tzinfo=UTC)
TEST_START = datetime(2023, 1, 1, tzinfo=UTC)
TEST_END = datetime(2024, 12, 1, tzinfo=UTC)

#: Windows are scored and reported separately, never pooled. A single number
#: spanning both would hide which side of the split it came from.
WINDOWS: tuple[tuple[str, datetime, datetime], ...] = (
    ("train+validation 2015-01 → 2022-12", EVAL_START, EVAL_END),
    ("held-out test 2023-01 → 2024-12", TEST_START, TEST_END),
)

#: The date the held-out window was first opened to scoring.
#:
#: The pre-registered protocol says the test years stay untouched until the
#: methodology is locked, and it was not locked when this landed — the Step 10
#: reporting checklist in docs/methodology.md stood at 0 of 12. Opening it was
#: a deliberate choice, and recording the date is what keeps it visible. A
#: reader comparing this report against the protocol is entitled to know the
#: exam was sat early rather than to infer it was sat under proper conditions.
TEST_WINDOW_OPENED = "2026-08-10"

HORIZONS = (1, 3, 6)
RANDOM_SEED = 20260703

COMPOSITE_NAME = "B6 composite"
DOMAIN_BASELINES: dict[str, str] = {
    "B3 geopolitical only": "geopolitical",
    "B4 market only": "market",
    "B5 hazard only": "hazard",
}


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def _run() -> int:
    exports = exports_dir()
    panel_path = exports / "panel.parquet"
    if not panel_path.exists():
        print(f"{panel_path} not found — run `make panel` first.", file=sys.stderr)
        return 1

    frame = pd.read_parquet(panel_path)
    needed = ["country", "month", "label_any", "composite_score", *DOMAIN_COLUMNS.values()]
    absent = [column for column in needed if column not in frame.columns]
    if absent:
        print(
            f"{panel_path} is missing {', '.join(absent)} — rebuild it with `make panel`.",
            file=sys.stderr,
        )
        return 1
    panel = frame[needed].to_dict("records")

    baselines = {
        "B0 random": score_random(panel, seed=RANDOM_SEED),
        "B1 persistence": score_persistence(panel),
        "B2 base rate": score_base_rate(panel),
    }
    #: B3/B4/B5 — each domain alone. These are the rivals the claim is defined
    #: against; the no-skill trio above only establishes a floor.
    domains = {
        name: score_domain(panel, domain=domain) for name, domain in DOMAIN_BASELINES.items()
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

    contenders = {**baselines, **domains, COMPOSITE_NAME: composite}

    windows: list[dict[str, Any]] = []
    for label, start, end in WINDOWS:
        results: list[dict[str, Any]] = []
        head_to_head: list[dict[str, Any]] = []
        verdicts: list[dict[str, Any]] = []
        for horizon in HORIZONS:
            targets = build_targets(panel, horizon=horizon)
            window_keys = sorted(key for key in targets if start <= key[1] <= end)
            y = [targets[key] for key in window_keys]
            for name, scores in baselines.items():
                results.append(_score_rows(name, scores, window_keys, y, horizon))

            # Common support: only rows every contender can score. The
            # composite and each domain drop out on different months, and
            # scoring them on different populations would compare the
            # difficulty of their rows rather than the quality of their
            # forecasts.
            common = [
                key for key in window_keys if all(key in scores for scores in contenders.values())
            ]
            y_common = [targets[key] for key in common]
            rows = [
                _score_rows(name, scores, common, y_common, horizon)
                for name, scores in contenders.items()
            ]
            head_to_head.extend(rows)

            verdict = judge_claim(rows, composite=COMPOSITE_NAME, rivals=tuple(DOMAIN_BASELINES))
            verdicts.append(
                {
                    "horizon_months": horizon,
                    "n": len(common),
                    "passed": verdict.passed,
                    "undecided": verdict.undecided,
                    "beaten": verdict.beaten,
                    "lost_to": verdict.lost_to,
                    "summary": verdict.summary,
                }
            )

        window_frame = frame[(frame["month"] >= start) & (frame["month"] <= end)]
        windows.append(
            {
                "window": label,
                "span": [start.date().isoformat(), end.date().isoformat()],
                "rows": len(window_frame),
                "results": results,
                "head_to_head_common_support": head_to_head,
                "verdicts": verdicts,
                "code_positive_rates": {
                    code: (
                        round(float(window_frame[code].mean()), 4) if len(window_frame) else None
                    )
                    for code in ("label_p1", "label_p2", "label_p3", "label_any")
                },
            }
        )

    report_md = _render_markdown(windows)
    (exports / "baselines-report.md").write_text(report_md)
    (exports / "baselines-report.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "test_window_opened": TEST_WINDOW_OPENED,
                "random_seed": RANDOM_SEED,
                "windows": windows,
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


def _verdict_lines(verdicts: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| k | n | verdict |",
        "|---|---|---|",
    ]
    for row in verdicts:
        lines.append(f"| {row['horizon_months']} | {row['n']} | {row['summary']} |")
    return lines


def _render_markdown(windows: list[dict[str, Any]]) -> str:
    lines = [
        "# Baseline report — the composite against every rival it is defined against",
        "",
        "The claim under test: a composite of market, geopolitical and hazard",
        "signals discriminates later instability better than the best single",
        "domain. It clears the bar only by beating **each** of B3/B4/B5 on",
        "**both** AUROC and AUPR — beating the no-skill trio is a floor, not the",
        "claim.",
        "",
        f"The held-out test window was first opened to scoring on **{TEST_WINDOW_OPENED}**,",
        "before the methodology was locked: the Step 10 reporting checklist in",
        "`docs/methodology.md` stood at 0 of 12. The test numbers below are",
        "therefore not a clean pre-registered read, and no later write-up should",
        "present them as one.",
        "",
    ]

    for window in windows:
        results = window["results"]
        head_to_head = window["head_to_head_common_support"]
        full_n = results[0]["n"] if results else 0
        common_n = head_to_head[0]["n"] if head_to_head else 0
        coverage = f"{common_n / full_n:.0%}" if full_n else "n/a"

        lines += [
            f"## {window['window']}",
            "",
            f"{window['rows']} country-months in the panel.",
            "",
            "### Verdict",
            "",
            *_verdict_lines(window["verdicts"]),
            "",
            "### Full panel — B0 / B1 / B2",
            "",
            *_table(results),
            "",
            "Per-code positive rates: "
            + ", ".join(f"{code} = {rate}" for code, rate in window["code_positive_rates"].items()),
            "",
            "### Head-to-head on common support — B0-B2, B3-B5, B6",
            "",
            f"Restricted to rows every contender can score ({common_n} of {full_n} "
            f"at k=1, {coverage} coverage). The composite and each domain drop out on "
            "different months, so scoring them on their own rows would compare the "
            "difficulty of those rows rather than the quality of the forecasts.",
            "",
            *_table(head_to_head),
            "",
        ]

    lines += [
        "## Reading the single-domain rivals",
        "",
        "B3/B4/B5 are not separate models. The composite z-scores each domain",
        "before combining them, and the panel stores those components, so each",
        "rival is the composite deprived of its other inputs — the exact",
        "counterfactual the claim needs. If a rival wins, the extra domains are",
        "costing information rather than adding it.",
        "",
        "Rolling within-country z-scores deliberately remove the cross-sectional",
        "differences that dominate P1-P3 incidence, so all six contenders measure",
        "deviation from a country's own baseline. That is an onset-shaped signal,",
        "and against a ~0.93 per-country base rate a coin-flip AUROC is a",
        "statement about construction rather than about signal absence. The",
        "onset-restricted evaluation this points to must be pre-registered before",
        "it is run.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    from app.jobs.heartbeat import job_run

    with job_run("baselines"):
        rc = _run()
        if rc != 0:
            raise SystemExit(f"baselines: exited {rc} — see output above")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
