"""The filled category sheet → published agreement rates (#951).

Same contract as `app.severity.agreement`, for the same reason: the model is
another fallible annotator, never a judge. A blank human side leaves a row
uncounted — never assumed correct.

Two numbers come out, and they answer different questions.

**Agreement** is how often a model's tag matches the reviewer's, over rows the
reviewer filled. It is reported per stratum, because the `read` block is
deliberately not an unbiased draw: agreement over `random` is the honest
headline figure, and agreement over `read` says what the reader actually meets.

**Forced rate** is the share of rows the reviewer marked `enum ok = no` — where
no word in the vocabulary honestly fits. No model can improve that number. It
is the evidence for widening the enum, and it is reported whether or not any
model is run, because it is a property of the taxonomy rather than of a model.

    python -m app.brain.category_agreement
    python -m app.brain.category_agreement --models llama3.2:3b,qwen3.5:4b-q4_K_M
    make category-agreement
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from app.brain import client
from app.brain.enrich import build_gist_prompt, parse_gist
from app.paths import exports_dir
from app.settings import settings

#: Mirrors `category_audit`. Named here by value rather than imported, so the
#: two modules do not import each other — the audit sheet already imports this
#: one to ask whether it carries labels.
RANDOM_STRATUM: str = "random"
READ_STRATUM: str = "read"

SHEET_NAME: str = "brain-category-audit-sheet.md"
REPORT_NAME: str = "brain-category-model-eval"

_COLUMNS = 6


def _stratum_pct(by_stratum: dict[str, Any], block: str) -> str:
    """One stratum's agreement, or an em dash when the sheet has no such rows."""
    if block not in by_stratum:
        return "—"
    return f"{by_stratum[block]['agreement']:.1%}"


def _cells(line: str) -> list[str] | None:
    """A markdown table row → its cells, or None if the line is not one."""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    if len(cells) != _COLUMNS:
        return None
    if all(set(c) <= {"-", ":"} and c for c in cells):
        return None  # the header underline
    return cells


def parse_sheet(text: str) -> list[dict[str, Any]]:
    """Every data row in the sheet, labelled or not.

    Returns rows as written. Filtering to the labelled ones is `scored_rows`'s
    job, so `category_audit.has_human_labels` can ask whether *any* answer
    exists without duplicating the parse.
    """
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        cells = _cells(line)
        if cells is None:
            continue
        story_id, headlines, human_category, enum_ok, would_rather, stratum = cells
        if story_id == "story" or not story_id:
            continue  # the header row
        try:
            parsed_id = int(story_id)
        except ValueError:
            continue
        rows.append(
            {
                "story_id": parsed_id,
                "titles": [t.strip() for t in headlines.split(" / ") if t.strip()],
                "human_category": human_category.lower(),
                "enum_ok": enum_ok.lower(),
                "would_rather": would_rather.lower(),
                "stratum": stratum,
            }
        )
    return rows


def scored_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows the reviewer actually labelled. A blank category is dropped."""
    return [r for r in rows if r["human_category"]]


def forced_rate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How often the vocabulary had no honest home for the story."""
    answered = [r for r in rows if r["enum_ok"] in {"yes", "no"}]
    forced = [r for r in answered if r["enum_ok"] == "no"]
    return {
        "answered": len(answered),
        "forced": len(forced),
        "rate": (len(forced) / len(answered)) if answered else None,
        "would_rather": Counter(r["would_rather"] for r in forced if r["would_rather"]),
    }


def agreement(rows: list[dict[str, Any]], predictions: dict[int, str]) -> dict[str, Any]:
    """Model-vs-reviewer agreement, overall and per stratum."""
    counted = [r for r in scored_rows(rows) if r["story_id"] in predictions]
    per_stratum: dict[str, list[bool]] = {}
    confusion: Counter[tuple[str, str]] = Counter()
    for row in counted:
        predicted = predictions[row["story_id"]]
        hit = predicted == row["human_category"]
        per_stratum.setdefault(row["stratum"], []).append(hit)
        if not hit:
            confusion[(row["human_category"], predicted)] += 1
    return {
        "n": len(counted),
        "agreement": (sum(sum(v) for v in per_stratum.values()) / len(counted))
        if counted
        else None,
        "by_stratum": {
            name: {"n": len(hits), "agreement": sum(hits) / len(hits)}
            for name, hits in sorted(per_stratum.items())
        },
        "confusion": confusion,
    }


def predict(rows: list[dict[str, Any]], *, model: str) -> dict[int, str]:
    """Ask one model for a category per row, from the sheet's own headlines.

    Prompting from the sheet rather than the database on purpose: retention
    removes the events within thirty days, and an evaluation that stops being
    reproducible the moment its rows age out is not an evaluation.
    """
    predictions: dict[int, str] = {}
    for row in rows:
        if not row["titles"]:
            continue
        payload = client.generate_json(
            build_gist_prompt(row["titles"]), model=model, keep_alive="5m"
        )
        predictions[row["story_id"]] = parse_gist(payload)["category"]
    return predictions


def build_report(
    *, results: dict[str, dict[str, Any]], forced: dict[str, Any], total: int, labelled: int
) -> str:
    lines = [
        "# Story category model evaluation",
        "",
        f"{labelled} of {total} sheet rows carry a reviewer's label. "
        "Unlabelled rows are dropped, never assumed correct.",
        "",
        "## Does the vocabulary fit?",
        "",
    ]
    if forced["answered"]:
        rate = forced["rate"]
        lines += [
            f"The reviewer answered `enum ok` on {forced['answered']} rows and "
            f"marked {forced['forced']} of them forced — **{rate:.1%}**. No "
            "model can improve this figure; it is a property of the taxonomy.",
        ]
        if forced["would_rather"]:
            lines += ["", "Tags the reviewer would rather have used:", ""]
            for word, count in forced["would_rather"].most_common():
                lines.append(f"- `{word}` on {count} row(s)")
    else:
        lines.append("No `enum ok` answers yet, so nothing can be said about the vocabulary.")
    lines += [
        "",
        "## Agreement by model",
        "",
        "| model | rows | agreement | random | read |",
        "|---|---|---|---|---|",
    ]
    for model, result in results.items():
        if not result["n"]:
            continue
        by = result["by_stratum"]
        lines.append(
            f"| `{model}` | {result['n']} | {result['agreement']:.1%} "
            f"| {_stratum_pct(by, RANDOM_STRATUM)} | {_stratum_pct(by, READ_STRATUM)} |"
        )
    for model, result in results.items():
        if not result["confusion"]:
            continue
        lines += [
            "",
            f"### Where `{model}` disagreed",
            "",
            "| reviewer said | model said | rows |",
            "|---|---|---|",
        ]
        for (human, predicted), count in result["confusion"].most_common(10):
            lines.append(f"| {human} | {predicted} | {count} |")
    lines.append("")
    return "\n".join(lines)


def _run(*, models: list[str]) -> int:
    exports = exports_dir()
    sheet_path = exports / SHEET_NAME
    if not sheet_path.exists():
        print(f"{sheet_path} does not exist — run `make category-audit` first")
        return 1

    rows = parse_sheet(sheet_path.read_text())
    labelled = scored_rows(rows)
    forced = forced_rate(rows)
    if not labelled:
        print(
            f"{sheet_path} carries no reviewer labels yet — nothing to score.\n"
            "Fill the `human category` column and run this again."
        )
        return 1

    results: dict[str, dict[str, Any]] = {}
    for model in models:
        results[model] = agreement(rows, predict(labelled, model=model))

    report = build_report(results=results, forced=forced, total=len(rows), labelled=len(labelled))
    (exports / f"{REPORT_NAME}.md").write_text(report)
    (exports / f"{REPORT_NAME}.json").write_text(
        json.dumps(
            {
                "labelled": len(labelled),
                "total": len(rows),
                "forced": {k: v for k, v in forced.items() if k != "would_rather"},
                "would_rather": dict(forced["would_rather"]),
                "models": {
                    model: {
                        "n": r["n"],
                        "agreement": r["agreement"],
                        "by_stratum": r["by_stratum"],
                        "confusion": {f"{h}->{p}": c for (h, p), c in r["confusion"].items()},
                    }
                    for model, r in results.items()
                },
            },
            indent=2,
        )
    )
    print(report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        default=settings.brain_model,
        help="comma-separated Ollama models to score (default: the configured brain model)",
    )
    args = parser.parse_args()
    return _run(models=[m.strip() for m in args.models.split(",") if m.strip()])


if __name__ == "__main__":
    raise SystemExit(main())
