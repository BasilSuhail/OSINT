"""Q&A model comparison harness for Phase C (#413).

This does not switch production models. It runs the same retrieved Q&A context
through candidate local Ollama models and writes a decision artifact.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.brain import client, context, qa, qa_rubric
from app.db import get_session_factory
from app.runtime import load as runtime_load
from app.settings import settings


def candidate_models() -> list[str]:
    """Current brain model plus the validator's 4b model, de-duplicated."""
    models: list[str] = []
    for model in (settings.brain_model, settings.ollama_model):
        if model not in models:
            models.append(model)
    return models


def _coerce_spec(question: qa_rubric.EvalQuestion | str) -> qa_rubric.EvalQuestion:
    if isinstance(question, qa_rubric.EvalQuestion):
        return question
    return qa_rubric.EvalQuestion(question=str(question))


def evaluate_answer(
    session: Session,
    *,
    spec: qa_rubric.EvalQuestion | str,
    model: str,
    now: datetime | None = None,
    generate_json: Callable[..., dict[str, Any]] = client.generate_json,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Run one question/model pair and return measured, machine-checkable facts."""
    spec = _coerce_spec(spec)
    qa_context = qa.build_qa_context(session, now=now, question=spec.question)
    prompt = qa.build_qa_prompt(qa_context, spec.question)
    started = clock()
    try:
        raw = generate_json(prompt, model=model, keep_alive="0")
        elapsed_ms = round((clock() - started) * 1000)
        answer = raw.get("answer") if isinstance(raw, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("model returned no answer string")
        sources = qa_context.get("stories") or []
        invalid = qa.invalid_citations(answer, len(sources))
        answer = qa.strip_bad_citations(answer, len(sources))
        repaired = False
        if not qa.citation_compliant(answer, len(sources)):
            repair_raw = generate_json(
                qa.build_citation_repair_prompt(qa_context, spec.question, answer),
                model=model,
                keep_alive="0",
            )
            repair_answer = repair_raw.get("answer") if isinstance(repair_raw, dict) else None
            if isinstance(repair_answer, str) and repair_answer.strip():
                invalid.extend(qa.invalid_citations(repair_answer, len(sources)))
                answer = qa.strip_bad_citations(repair_answer, len(sources))
                repaired = True
        cited = qa.citation_numbers(answer)
        citation_ok = qa.citation_compliant(answer, len(sources))
        if not citation_ok:
            raise ValueError("model returned an uncited answer")
        return {
            "question": spec.question,
            "model": model,
            "ok": True,
            "elapsed_ms": elapsed_ms,
            "answer": answer,
            "context_digest": context.input_digest(qa_context),
            "n_sources": len(sources),
            "cited": cited,
            "invalid_citations": invalid,
            "citation_ok": citation_ok,
            "citation_repaired": repaired,
            "rubric": qa_rubric.score_answer(
                spec, answer=answer, stories=sources, invalid_citations=invalid
            ),
        }
    except Exception as exc:
        stories = qa_context.get("stories") or []
        return {
            "question": spec.question,
            "model": model,
            "ok": False,
            "elapsed_ms": round((clock() - started) * 1000),
            "answer": None,
            "context_digest": context.input_digest(qa_context),
            "n_sources": len(stories),
            "cited": [],
            "invalid_citations": [],
            "citation_ok": False,
            "citation_repaired": False,
            "error": f"{type(exc).__name__}: {exc}",
            "rubric": qa_rubric.score_answer(
                spec,
                answer=None,
                stories=stories,
                invalid_citations=[],
                error=f"{type(exc).__name__}: {exc}",
            ),
        }


def run_eval(
    session: Session,
    *,
    questions: Iterable[qa_rubric.EvalQuestion | str] = qa_rubric.EVAL_QUESTIONS,
    models: Iterable[str] | None = None,
    now: datetime | None = None,
    generate_json: Callable[..., dict[str, Any]] = client.generate_json,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    model_list = list(models or candidate_models())
    spec_list = [_coerce_spec(q) for q in questions if str(getattr(q, "question", q)).strip()]
    results = []
    with runtime_load.activity("brain-qa-eval"):
        for spec in spec_list:
            for model in model_list:
                runtime_load.heartbeat("brain-qa-eval")
                results.append(
                    evaluate_answer(
                        session,
                        spec=spec,
                        model=model,
                        now=now,
                        generate_json=generate_json,
                    )
                )
    return {
        "created_at": now.isoformat(),
        "models": model_list,
        "questions": [s.question for s in spec_list],
        "results": results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Brain Q&A model evaluation",
        "",
        f"Created: `{report['created_at']}`",
        "",
        "| Model | OK | Rubric | "
        + " | ".join(qa_rubric.DIMENSIONS)
        + " | Median latency ms | Invalid citations |",
        "|---|---:|---:|" + "---:|" * len(qa_rubric.DIMENSIONS) + "---:|---:|",
    ]
    for model in report["models"]:
        rows = [r for r in report["results"] if r["model"] == model]
        ok_rows = [r for r in rows if r["ok"]]
        latencies = sorted(r["elapsed_ms"] for r in ok_rows)
        median = latencies[len(latencies) // 2] if latencies else None
        invalid = sum(len(r["invalid_citations"]) for r in rows)
        rubrics = [r.get("rubric") or {} for r in rows]
        passed = sum(1 for rub in rubrics if rub.get("passed"))
        dims = " | ".join(
            f"{sum(1 for rub in rubrics if rub.get(d))}/{len(rows)}" for d in qa_rubric.DIMENSIONS
        )
        lines.append(
            f"| `{model}` | {len(ok_rows)}/{len(rows)} | {passed}/{len(rows)} | {dims} "
            f"| {median or 'n/a'} | {invalid} |"
        )

    lines.extend(["", "## Runs", ""])
    for row in report["results"]:
        status = "ok" if row["ok"] else "failed"
        lines.extend(
            [
                f"### `{row['model']}` — {row['question']}",
                "",
                f"- status: {status}",
                f"- latency_ms: {row['elapsed_ms']}",
                f"- sources: {row['n_sources']}",
                f"- cited: {row['cited']}",
                f"- invalid_citations: {row['invalid_citations']}",
                f"- citation_ok: {row.get('citation_ok', False)}",
                f"- citation_repaired: {row.get('citation_repaired', False)}",
            ]
        )
        rubric = row.get("rubric") or {}
        failed = [d for d in qa_rubric.DIMENSIONS if not rubric.get(d)]
        lines.append(f"- rubric_passed: {bool(rubric.get('passed'))}")
        lines.append(f"- rubric_failed: {failed}")
        for reason in rubric.get("reasons") or []:
            lines.append(f"- reason: {reason}")
        if row["ok"]:
            lines.extend(["", row["answer"] or "", ""])
        else:
            lines.extend([f"- error: {row.get('error')}", ""])
    return "\n".join(lines).strip() + "\n"


def write_report(report: dict[str, Any], *, out_dir: Path | None = None) -> tuple[Path, Path]:
    out = out_dir or Path(settings.data_dir) / "exports"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "brain-qa-model-eval.json"
    md_path = out / "brain-qa-model-eval.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    md_path.write_text(render_markdown(report))
    return json_path, md_path


def main() -> None:
    factory = get_session_factory()
    with factory() as session:
        report = run_eval(session)
    json_path, md_path = write_report(report)
    print(f"written: {md_path} (+ {json_path})")


if __name__ == "__main__":
    main()
