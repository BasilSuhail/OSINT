"""Deterministic rubric scoring for the brain Q&A eval (#413 roadmap item 1).

Pure functions: no DB access, no model calls. qa_eval orchestrates retrieval
and model answers, then calls score_answer per run. An answer passes only if
every rubric dimension passes; reasons explain each failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.brain import qa

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


_UNCERTAINTY_MARKERS: tuple[str, ...] = (
    "contested",
    "disputed",
    "single",
    "unconfirmed",
    "not confirmed",
    "unverified",
    "claim",
    "reported",
    "unclear",
    "unknown",
    "no local evidence",
    "insufficient",
)
_CONTESTED_MARKERS: tuple[str, ...] = ("contested", "disputed", "disagree")
_COVERAGE_MARKERS: tuple[str, ...] = ("coverage", "source", "outlet", "thin", "few", "only")
_WEAK_CORROBORATION: float = 0.5
_MIN_ANSWER_CHARS: int = 40
_MIN_SHARED_TOKENS: int = 2
_MIN_TOKEN_LEN: int = 4


def _contains_any(answer: str, markers: tuple[str, ...]) -> bool:
    low = answer.lower()
    return any(marker in low for marker in markers)


def _story_weak(story: dict[str, Any]) -> bool:
    """Single-teller, contested, weakly corroborated, or sensor-unconfirmed."""
    if story.get("contested") or story.get("owner_count") == 1:
        return True
    corroboration = story.get("corroboration")
    if corroboration is not None and float(corroboration) < _WEAK_CORROBORATION:
        return True
    sensor = story.get("sensor") or {}
    return any(str(verdict).lower() != "confirmed" for verdict in sensor.values())


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in qa._TERM_RE.findall(text.lower())
        if len(token) >= _MIN_TOKEN_LEN and token not in qa._QUESTION_STOPWORDS
    }


def score_answer(
    spec: EvalQuestion,
    *,
    answer: str | None,
    stories: list[dict[str, Any]],
    invalid_citations: list[int],
    error: str | None = None,
) -> dict[str, Any]:
    """Six pass/fail dimensions + reasons. `passed` only if every dim passes."""
    if not isinstance(answer, str) or not answer.strip():
        reason = f"model error: {error}" if error else "no answer produced"
        return {**dict.fromkeys(DIMENSIONS, False), "passed": False, "reasons": [reason]}

    reasons: list[str] = []
    refusal = answer.strip() == qa.REFUSAL_ANSWER
    cited = qa.valid_citations(answer, len(stories))
    relevant = relevant_sources(spec, stories)
    by_n = {story.get("n"): story for story in stories}
    cited_stories = [by_n[n] for n in cited if n in by_n]

    # refusal correctness: refuse iff there is no relevant local evidence.
    if refusal:
        if spec.mode == "coverage":
            refusal_ok = True
        else:
            refusal_ok = not relevant
            if not refusal_ok:
                reasons.append(f"refused despite relevant sources {relevant}")
    else:
        refusal_ok = bool(relevant)
        if not refusal_ok:
            reasons.append("answered with no relevant local evidence")

    # relevance: at least one citation must point at a relevant source.
    if refusal:
        relevance_ok = True
    else:
        relevance_ok = bool(set(cited) & set(relevant))
        if not relevance_ok:
            reasons.append(f"cited {cited} not among relevant sources {relevant}")
        if spec.mode == "coverage" and not _contains_any(answer, _COVERAGE_MARKERS):
            relevance_ok = False
            reasons.append("coverage question answered without coverage language")

    # citation: production strips invalid [n]; the model still loses the point.
    citation_ok = refusal or (qa.citation_compliant(answer, len(stories)) and not invalid_citations)
    if not citation_ok:
        reasons.append(f"citation failure (invalid={invalid_citations})")

    # uncertainty: risky questions and weak cited sources demand hedged language.
    required = not refusal and (spec.risky or any(_story_weak(s) for s in cited_stories))
    uncertainty_ok = not required or _contains_any(answer, _UNCERTAINTY_MARKERS)
    if not uncertainty_ok:
        reasons.append("risky/weakly-sourced answer lacks uncertainty language")

    # contested: citing a contested story without flagging it flattens dispute.
    contested_cited = [s for s in cited_stories if s.get("contested")]
    contested_ok = not contested_cited or _contains_any(answer, _CONTESTED_MARKERS)
    if not contested_ok:
        reasons.append("cited contested story without contested/disputed framing")

    # usefulness: engage the cited content, not generic filler.
    if refusal:
        usefulness_ok = True
    else:
        answer_tokens = _content_tokens(answer)
        shared = max(
            (len(answer_tokens & _content_tokens(_story_text(s))) for s in cited_stories),
            default=0,
        )
        usefulness_ok = len(answer.strip()) >= _MIN_ANSWER_CHARS and shared >= _MIN_SHARED_TOKENS
        if not usefulness_ok:
            reasons.append("answer too short or does not engage cited story content")

    scores = {
        "relevance": relevance_ok,
        "citation": citation_ok,
        "uncertainty": uncertainty_ok,
        "contested": contested_ok,
        "refusal": refusal_ok,
        "usefulness": usefulness_ok,
    }
    return {**scores, "passed": all(scores.values()), "reasons": reasons}
