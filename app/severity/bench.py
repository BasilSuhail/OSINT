"""Candidate graders replayed against the human sheet (#646).

#630 refused to swap the 4b grader for something faster, and the reason stands:
the band agreement published in #593 describes `qwen3.5:4b-q4_K_M` reading the
`news.build_prompt` rubric. Swap the model and that number stops describing what
runs. So the swap is not forbidden — it is gated on the same measurement being
taken again.

This replays the 50 rows a human already graded in
`data/exports/severity-audit-sheet.md` through each candidate, using the
unchanged prompt and the unchanged guards, and reports what each one scores
against that same human. Nothing here writes to the database and nothing here
changes which model production uses: it emits a decision artifact, exactly as
`brain/qa_eval.py` does for the Q&A side.

Two things it deliberately does not reuse from the sheet:

- **the human's `rationale ok` column** — that judgement was passed on the
  incumbent's wording, not on a candidate's. Carrying it over would credit a new
  model with a human's opinion of a different sentence, so it is dropped and the
  rate reads `n/a`. Re-auditing rationales is a human's job, per candidate.
- **the sheet's model columns** — every candidate is re-run live, including the
  incumbent. A control measured in the same conditions is the only honest
  comparison for a seconds-per-headline number.

    python -m app.severity.bench
    python -m app.severity.bench --models qwen3:1.7b,gemma3:1b
    make severity-bench
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from typing import Any

from app.brain import client
from app.paths import exports_dir
from app.settings import settings
from app.severity import agreement, news

#: Models to bench when none are named. The incumbent leads so the run starts
#: with its control while the box is in whatever state it is in, and the sizes
#: descend from there — the question this issue asks is how far down the scale
#: the gate still holds.
CANDIDATES: tuple[str, ...] = (
    "qwen3.5:4b-q4_K_M",
    "qwen3:1.7b",
    "gemma3:1b",
    "llama3.2:3b",
    "phi4-mini",
)

#: The bar a replacement has to clear: the band agreement #593 published for the
#: incumbent. A candidate that is faster and scores 0.79 has not earned the
#: swap, and writing the constant down stops that being re-litigated per run.
BAND_AGREEMENT_GATE: float = 0.860


def human_cases(sheet_text: str) -> list[dict[str, Any]]:
    """Headlines the human actually banded, with their judgement kept.

    Rows the human left blank are dropped rather than defaulted — the same rule
    `agreement.parse_sheet` applies, for the same reason: an ungraded row is not
    evidence of agreement.
    """
    return [
        {
            "headline": row["headline"],
            "human_severity": row["human_severity"],
            "human_band": row["human_band"],
        }
        for row in agreement.parse_sheet(sheet_text)
        if row["human_band"]
    ]


#: How the model is asked. `number` is #591's protocol, the one production runs.
#: `band` asks for the band's name and maps it to a value in code (#649), after
#: #646 found small models classifying correctly in prose and emitting an
#: unrelated float. Both go through the same guards.
PROTOCOLS: dict[str, tuple[Any, Any]] = {
    "number": (news.build_prompt, news.verdict_from_payload),
    "band": (news.build_band_prompt, news.band_verdict_from_payload),
}


def bench_model(
    cases: list[dict[str, Any]],
    *,
    model: str,
    protocol: str = "number",
    generate_json: Callable[..., dict[str, Any]] = client.generate_json,
) -> dict[str, Any]:
    """Grade every case with one model. Returns its scores plus what it cost.

    A guard rejection is counted and excluded from the agreement rows, matching
    `audit._run`: a rejected verdict never reaches stored data, so scoring it
    would measure an answer the system would have thrown away. The rejection
    rate is reported next to the agreement so a model that scores well on the
    third of rows it did not mangle cannot hide behind the average.
    """
    build, parse = PROTOCOLS[protocol]
    rows: list[dict[str, Any]] = []
    rejected = 0
    errors = 0
    elapsed = 0.0

    for case in cases:
        headline = case["headline"]
        started = time.perf_counter()
        try:
            payload = generate_json(build(headline), model=model, keep_alive="5m")
        except Exception:
            # A missing model or a dead daemon fails this candidate, not the
            # whole bench — the remaining candidates still have numbers worth
            # having, and the count is printed rather than swallowed.
            errors += 1
            elapsed += time.perf_counter() - started
            continue
        elapsed += time.perf_counter() - started

        verdict = parse(payload, headline=headline)
        if verdict is None:
            rejected += 1
            continue
        rows.append(
            {
                "headline": headline,
                "model_severity": verdict.value,
                "model_band": verdict.as_payload()["severity_band"],
                "human_severity": case["human_severity"],
                "human_band": case["human_band"],
                # Never carried over from the sheet: see the module docstring.
                "rationale_ok": None,
            }
        )

    attempts = len(cases)
    result: dict[str, Any] = {
        "model": model,
        "protocol": protocol,
        "attempted": attempts,
        "rejected": rejected,
        "errors": errors,
        "rejection_rate": rejected / attempts if attempts else None,
        "seconds_per_headline": elapsed / attempts if attempts else None,
        **agreement.score(rows),
    }
    result["passes_gate"] = passes_gate(result)
    return result


def passes_gate(result: dict[str, Any]) -> bool:
    """Both conditions, or no swap.

    Floor violations first and absolutely: a headline the human marked as a
    death that the model scored below 0.60 is the failure the scale exists to
    prevent, and one of those outweighs any speed. Band agreement second, at no
    worse than what is already published.
    """
    if result["errors"]:
        return False
    if result["floor_violations"]:
        return False
    band = result["band_agreement"]
    return band is not None and band >= BAND_AGREEMENT_GATE


def _fmt(value: float | None, places: int = 3) -> str:
    return f"{value:.{places}f}" if value is not None else "n/a"


def render(results: list[dict[str, Any]], *, incumbent: str) -> str:
    protocols = sorted({result.get("protocol", "number") for result in results})
    lines = [
        "# News severity — candidate grader bench (#646)",
        "",
        f"{len(results)} run(s) over the same human-graded rows from "
        f"`severity-audit-sheet.md`, protocol: {', '.join(protocols)}. Guards "
        "unchanged; the incumbent is re-run as a control rather than quoted "
        "from #593.",
        "",
        "| model | protocol | band agreement | floor violations | MAE | rejected "
        "| s/headline | gate |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for result in results:
        name = result["model"]
        label = f"`{name}`" + (" (incumbent)" if name == incumbent else "")
        label = f"{label} | {result.get('protocol', 'number')}"
        verdict = "**pass**" if result["passes_gate"] else "fail"
        if result["errors"]:
            verdict = f"error ({result['errors']})"
        lines.append(
            f"| {label} | {_fmt(result['band_agreement'])} | {result['floor_violations']} "
            f"| {_fmt(result['mean_absolute_error'])} | {_fmt(result['rejection_rate'], 2)} "
            f"| {_fmt(result['seconds_per_headline'], 2)} | {verdict} |"
        )

    lines += [
        "",
        f"**Gate**: floor violations 0 **and** band agreement >= {BAND_AGREEMENT_GATE:.3f} "
        "(what #593 published for the incumbent). A candidate that is faster and "
        "scores below the gate is recorded and rejected — speed does not buy a "
        "missed death.",
        "",
        "Rationale honesty is not scored here: the human judged the incumbent's "
        "wording, and reusing that column would credit a candidate with an "
        "opinion of a different sentence. A winner needs its own `severity-audit`.",
        "",
    ]

    passing = [r for r in results if r["passes_gate"] and r["model"] != incumbent]
    if passing:
        best = min(passing, key=lambda r: r["seconds_per_headline"] or float("inf"))
        lines += [
            f"Fastest candidate clearing the gate: **`{best['model']}`** on the "
            f"{best.get('protocol', 'number')} protocol, at "
            f"{_fmt(best['seconds_per_headline'], 2)} s/headline.",
            "",
        ]
    else:
        lines += [
            "**No candidate cleared the gate.** The incumbent keeps the job. A "
            "cascade — small model everywhere, incumbent re-grading only rows near "
            "a band boundary or carrying a lethal cue — is the remaining option, "
            "and it is a separate change with its own measurement.",
            "",
        ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bench candidate severity graders (#646)")
    parser.add_argument(
        "--models",
        default=",".join(CANDIDATES),
        help="comma-separated Ollama model tags to bench",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="bench only the first N human-graded rows"
    )
    parser.add_argument(
        "--protocols",
        default="number",
        help="comma-separated protocols to bench: number (#591), band (#649)",
    )
    args = parser.parse_args()

    exports = exports_dir()
    sheet = exports / "severity-audit-sheet.md"
    if not sheet.exists():
        print(f"{sheet} not found — run `make severity-audit` first")
        return 1

    cases = human_cases(sheet.read_text())
    if not cases:
        print(f"{sheet} has no human-banded rows yet — fill the human columns first")
        return 1
    if args.limit:
        cases = cases[: args.limit]

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    protocols = [p.strip() for p in args.protocols.split(",") if p.strip()]
    for protocol in protocols:
        if protocol not in PROTOCOLS:
            print(f"unknown protocol {protocol!r} — choose from {', '.join(PROTOCOLS)}")
            return 1

    results = []
    for protocol in protocols:
        for model in models:
            print(f"benching {model} ({protocol}) over {len(cases)} row(s)…", flush=True)
            result = bench_model(cases, model=model, protocol=protocol)
            print(
                f"  band agreement {_fmt(result['band_agreement'])} · "
                f"floors {result['floor_violations']} · "
                f"{_fmt(result['seconds_per_headline'], 2)} s/headline · "
                f"{'pass' if result['passes_gate'] else 'fail'}",
                flush=True,
            )
            results.append(result)

    report = render(results, incumbent=settings.severity_model)
    exports.mkdir(parents=True, exist_ok=True)
    (exports / "severity-model-bench.md").write_text(report)
    print()
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
