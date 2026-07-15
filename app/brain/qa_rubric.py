"""Deterministic rubric scoring for the brain Q&A eval (#413 roadmap item 1).

Pure functions: no DB access, no model calls. qa_eval orchestrates retrieval
and model answers, then calls score_answer per run. An answer passes only if
every rubric dimension passes; reasons explain each failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DIMENSIONS: tuple[str, ...] = (
    "relevance",
    "citation",
    "uncertainty",
    "contested",
    "refusal",
    "usefulness",
)


@dataclass(frozen=True)
class EvalQuestion:
    """One eval question plus its deterministic relevance ground truth."""

    question: str
    topic_terms: tuple[str, ...] = ()
    risky: bool = False
    mode: str = "topic"  # topic | sensor | contested | coverage


EVAL_QUESTIONS: tuple[EvalQuestion, ...] = (
    EvalQuestion(
        question="is the war back on?",
        topic_terms=(
            "war",
            "ceasefire",
            "strike",
            "iran",
            "israel",
            "conflict",
            "attack",
            "truce",
            "mideast",
            "military",
        ),
        risky=True,
    ),
    EvalQuestion(
        question="did the ceasefire collapse?",
        topic_terms=(
            "ceasefire",
            "truce",
            "collapse",
            "war",
            "iran",
            "israel",
            "strike",
            "mideast",
        ),
        risky=True,
    ),
    EvalQuestion(
        question="what happened in Iran?",
        topic_terms=("iran", "iranian", "tehran"),
        risky=True,
    ),
    EvalQuestion(question="what is sensor confirmed?", mode="sensor"),
    EvalQuestion(question="where is coverage thin?", mode="coverage"),
    EvalQuestion(question="what is contested right now?", mode="contested"),
)


def _story_text(story: dict[str, Any]) -> str:
    return " ".join(str(story.get(key) or "") for key in ("title", "gist")).lower()


def relevant_sources(spec: EvalQuestion, stories: list[dict[str, Any]]) -> list[int]:
    """Story numbers that can ground an answer to this question."""
    out: list[int] = []
    for story in stories:
        n = story.get("n")
        if not isinstance(n, int):
            continue
        if spec.mode == "sensor":
            hit = bool(story.get("sensor"))
        elif spec.mode == "contested":
            hit = bool(story.get("contested"))
        elif spec.mode == "coverage":
            hit = True
        else:
            text = _story_text(story)
            hit = any(term in text for term in spec.topic_terms)
        if hit:
            out.append(n)
    return out
