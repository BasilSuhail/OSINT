"""Q&A model comparison harness for Phase C (#413).

This does not switch production models. It runs the same retrieved Q&A context
through candidate local Ollama models and writes a decision artifact.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.brain import client, context, qa
from app.db import get_session_factory
from app.runtime import load as runtime_load
from app.settings import settings

DEFAULT_QUESTIONS: tuple[str, ...] = (
    "what is happening with Iran?",
    "what are the most contested stories?",
    "what has sensor confirmation?",
    "where is coverage thin?",
)
_CITATION_RE = re.compile(r"\[(\d+)\]")


def candidate_models() -> list[str]:
    """Current brain model plus the validator's 4b model, de-duplicated."""
    models: list[str] = []
    for model in (settings.brain_model, settings.ollama_model):
        if model not in models:
            models.append(model)
    return models


def _citation_numbers(answer: str) -> list[int]:
    return [int(match.group(1)) for match in _CITATION_RE.finditer(answer)]


def evaluate_answer(
    session: Session,
    *,
    question: str,
    model: str,
    now: datetime | None = None,
    generate_json: Callable[..., dict[str, Any]] = client.generate_json,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Run one question/model pair and return measured, machine-checkable facts."""
    qa_context = qa.build_qa_context(session, now=now, question=question)
    prompt = qa.build_qa_prompt(qa_context, question)
    started = clock()
    try:
        raw = generate_json(prompt, model=model, keep_alive="0")
        elapsed_ms = round((clock() - started) * 1000)
        answer = raw.get("answer") if isinstance(raw, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("model returned no answer string")
        sources = qa_context.get("stories") or []
        cited = _citation_numbers(answer)
        invalid = [n for n in cited if n < 1 or n > len(sources)]
        return {
            "question": question,
            "model": model,
            "ok": True,
            "elapsed_ms": elapsed_ms,
            "answer": answer,
            "context_digest": context.input_digest(qa_context),
            "n_sources": len(sources),
            "cited": cited,
            "invalid_citations": invalid,
        }
    except Exception as exc:
        return {
            "question": question,
            "model": model,
            "ok": False,
            "elapsed_ms": round((clock() - started) * 1000),
            "answer": None,
            "context_digest": context.input_digest(qa_context),
            "n_sources": len(qa_context.get("stories") or []),
            "cited": [],
            "invalid_citations": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_eval(
    session: Session,
    *,
    questions: Iterable[str] = DEFAULT_QUESTIONS,
    models: Iterable[str] | None = None,
    now: datetime | None = None,
    generate_json: Callable[..., dict[str, Any]] = client.generate_json,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    model_list = list(models or candidate_models())
    question_list = [q for q in questions if q.strip()]
    results = []
    with runtime_load.activity("brain-qa-eval"):
        for question in question_list:
            for model in model_list:
                runtime_load.heartbeat("brain-qa-eval")
                results.append(
                    evaluate_answer(
                        session,
                        question=question,
                        model=model,
                        now=now,
                        generate_json=generate_json,
                    )
                )
    return {
        "created_at": now.isoformat(),
        "models": model_list,
        "questions": question_list,
        "results": results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Brain Q&A model evaluation",
        "",
        f"Created: `{report['created_at']}`",
        "",
        "| Model | OK | Median latency ms | Invalid citations |",
        "|---|---:|---:|---:|",
    ]
    for model in report["models"]:
        rows = [r for r in report["results"] if r["model"] == model]
        ok_rows = [r for r in rows if r["ok"]]
        latencies = sorted(r["elapsed_ms"] for r in ok_rows)
        median = latencies[len(latencies) // 2] if latencies else None
        invalid = sum(len(r["invalid_citations"]) for r in rows)
        lines.append(f"| `{model}` | {len(ok_rows)}/{len(rows)} | {median or 'n/a'} | {invalid} |")

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
            ]
        )
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
