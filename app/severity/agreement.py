"""The filled human sheet → published agreement rates (#593).

The gate #591 declared: LLM severity verdicts feed nothing until a human has
said how often they are right. Same contract as `app.validator.agreement`, for
the same reason — the model is another fallible annotator, never a judge.

Severity is a number, so exact match is the wrong test: a human writing 0.62
against the model's 0.60 agrees with it. Band agreement is the headline metric.
Floor violations are counted separately and read first — a headline the human
marks as a death that the model scored below the lethal floor is the failure
that matters, and one of those outweighs ten near-miss band disagreements.

A blank human side leaves a row uncounted. Never assumed correct.

    python -m app.severity.agreement
    make severity-agreement
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.severity import scale


def _float_or_none(cell: str) -> float | None:
    try:
        return float(cell)
    except (TypeError, ValueError):
        return None


def parse_sheet(text: str) -> list[dict[str, Any]]:
    """Rows the human actually graded. Ungraded rows are dropped, not defaulted."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7 or cells[0].lower() == "headline":
            continue

        human_severity = _float_or_none(cells[4])
        human_band = cells[5] or None
        rationale_ok = cells[6].lower() or None
        # A band is enough to count a row: the numeric column is optional, and
        # judging bands is the faster, more reliable thing to ask a human for.
        if human_band is None and human_severity is None and rationale_ok is None:
            continue

        rows.append(
            {
                "headline": cells[0],
                "model_severity": _float_or_none(cells[1]),
                "model_band": cells[2] or None,
                "model_rationale": cells[3],
                "human_severity": human_severity,
                "human_band": human_band,
                "rationale_ok": rationale_ok,
            }
        )
    return rows


def _floor_violation(row: dict[str, Any]) -> bool:
    """Human says someone died; the model scored it below the lethal floor.

    Judged on the human's band rather than their number, since the band is the
    column they are asked to fill. Over-scoring is a calibration miss and is
    deliberately not counted here — this metric is about missed harm only.
    """
    human = row.get("human_band")
    model = row.get("model_severity")
    if human is None or model is None:
        return False
    if human not in ("grave", "mass_casualty"):
        return False
    return model < scale.LETHAL_FLOOR


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Published rates. None rather than a fake number when nothing qualifies."""
    banded = [r for r in rows if r["human_band"] and r["model_band"]]
    numeric = [
        r for r in rows if r["human_severity"] is not None and r["model_severity"] is not None
    ]
    judged = [r for r in rows if r["rationale_ok"] in ("ok", "no", "yes")]

    agreed = sum(1 for r in banded if r["human_band"] == r["model_band"])
    ok = sum(1 for r in judged if r["rationale_ok"] in ("ok", "yes"))

    return {
        "n": len(rows),
        "n_banded": len(banded),
        "band_agreement": agreed / len(banded) if banded else None,
        "floor_violations": sum(1 for r in rows if _floor_violation(r)),
        "rationale_ok_rate": ok / len(judged) if judged else None,
        "mean_absolute_error": (
            sum(abs(r["human_severity"] - r["model_severity"]) for r in numeric) / len(numeric)
            if numeric
            else None
        ),
    }


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "n/a"


def render(result: dict[str, Any]) -> str:
    lines = [
        "# News severity — model vs human agreement (#593)",
        "",
        f"{result['n']} graded row(s), {result['n_banded']} with a band on both sides.",
        "",
        f"- **band agreement**: {_fmt(result['band_agreement'])}",
        f"- **floor violations**: {result['floor_violations']} "
        "(human says a death, model scored below 0.60 — read this first)",
        f"- rationale judged honest: {_fmt(result['rationale_ok_rate'])}",
        f"- mean absolute error on the raw value: {_fmt(result['mean_absolute_error'])}",
        "",
    ]
    if result["floor_violations"]:
        lines += [
            "**A floor violation means the scale failed at the thing it exists for.**",
            "Fix the prompt or the guard before regrading anything, and before "
            "reaching for a bigger model.",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    exports = Path(os.environ.get("OSINT_DATA_DIR", "./data")) / "exports"
    path = exports / "severity-audit-sheet.md"
    if not path.exists():
        print(f"{path} not found — run `make severity-audit` first")
        return 1

    rows = parse_sheet(path.read_text())
    if not rows:
        print(f"{path} has no graded rows yet — fill the human columns first")
        return 1

    report = render(score(rows))
    (exports / "severity-agreement.md").write_text(report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
