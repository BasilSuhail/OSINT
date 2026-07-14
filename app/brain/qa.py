"""The brain's Q&A layer (#411).

Builds a compact context = the Phase 1 situation snapshot plus three lightweight
headline facts (latest composite + highest-stress country, most-contested story,
the prediction scoreboard's graded/total counts), then a no-fabrication prompt.
Reuses everything from Phase 1; adds only cheap headline reads.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.brain import context, enrich
from app.db_models import (
    EventRow,
    PredictionRow,
    ScoreRow,
    StoryCorroborationRow,
    StoryDisagreementRow,
    StoryGistRow,
    StoryMemberRow,
    StoryRow,
    StorySensorCheckRow,
)


def _latest_composite(session: Session) -> dict[str, Any] | None:
    latest = session.execute(
        select(func.max(ScoreRow.bucket_start)).where(ScoreRow.score_name == "composite")
    ).scalar_one_or_none()
    if latest is None:
        return None
    mean = session.execute(
        select(func.avg(ScoreRow.score_value)).where(
            ScoreRow.score_name == "composite", ScoreRow.bucket_start == latest
        )
    ).scalar_one()
    top = session.execute(
        select(ScoreRow.country, ScoreRow.score_value)
        .where(ScoreRow.score_name == "composite", ScoreRow.bucket_start == latest)
        .order_by(ScoreRow.score_value.desc())
        .limit(1)
    ).first()
    return {
        "latest_month": latest.isoformat(),
        "global_mean": round(float(mean), 3) if mean is not None else None,
        "highest_stress": ({"country": top[0], "score": round(float(top[1]), 3)} if top else None),
    }


def _most_contested(session: Session) -> dict[str, Any] | None:
    row = session.execute(
        select(StoryDisagreementRow.divergence, StoryRow.title)
        .join(StoryRow, StoryRow.id == StoryDisagreementRow.story_id)
        .order_by(StoryDisagreementRow.divergence.desc())
        .limit(1)
    ).first()
    return {"title": row[1], "divergence": round(float(row[0]), 3)} if row else None


def _scoreboard(session: Session) -> dict[str, int]:
    graded = session.execute(
        select(func.count()).select_from(PredictionRow).where(PredictionRow.outcome.is_not(None))
    ).scalar_one()
    total = session.execute(select(func.count()).select_from(PredictionRow)).scalar_one()
    return {"graded": int(graded), "total": int(total)}


#: divergence at or above this = a contested story (tellers disagree sharply).
CONTESTED_THRESHOLD: float = 0.5
_QA_STORIES: int = 6
_QA_WINDOW_H: int = 72
_MAX_OUTLETS: int = 3
_QA_CANDIDATES: int = 120
_QUESTION_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "anything",
        "around",
        "brain",
        "current",
        "data",
        "does",
        "from",
        "going",
        "happen",
        "happened",
        "happening",
        "latest",
        "news",
        "report",
        "reported",
        "reports",
        "show",
        "status",
        "story",
        "tell",
        "that",
        "the",
        "there",
        "this",
        "today",
        "what",
        "where",
        "with",
    }
)
_TERM_RE = re.compile(r"[a-z0-9]{3,}")
_COUNTRY_CODE_RE = re.compile(r"\b[A-Z]{2}\b")
_CITATION_RE = re.compile(r"\[(\d+)\]")
REFUSAL_ANSWER = "I don't have data on that."


def _question_terms(question: str | None) -> list[str]:
    if not question:
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for code in _COUNTRY_CODE_RE.findall(question):
        term = code.lower()
        terms.append(term)
        seen.add(term)
    for term in _TERM_RE.findall(question.lower()):
        if term in _QUESTION_STOPWORDS or term in seen:
            continue
        terms.append(term)
        seen.add(term)
    return terms


def _payload_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    vals = []
    for key in ("title", "headline", "description", "summary", "place", "country", "country_name"):
        val = payload.get(key)
        if isinstance(val, str):
            vals.append(val)
    return " ".join(vals)


def _member_texts(session: Session, story_ids: list[int]) -> dict[int, str]:
    texts: dict[int, list[str]] = {sid: [] for sid in story_ids}
    rows = session.execute(
        select(
            StoryMemberRow.story_id,
            EventRow.source,
            EventRow.category,
            EventRow.country,
            EventRow.keywords,
            EventRow.payload,
        )
        .join(EventRow, EventRow.id == StoryMemberRow.event_id)
        .where(StoryMemberRow.story_id.in_(story_ids))
    ).all()
    for story_id, source, category, country, keywords, payload in rows:
        parts = [source or "", category or "", country or "", _payload_text(payload)]
        parts.extend(str(k) for k in (keywords or []))
        texts.setdefault(story_id, []).append(" ".join(parts))
    return {sid: " ".join(parts).lower() for sid, parts in texts.items()}


def _rank_story_rows(
    rows: list[tuple[StoryRow, StoryCorroborationRow | None]],
    *,
    gists: dict[int, StoryGistRow],
    member_texts: dict[int, str],
    terms: list[str],
) -> list[tuple[StoryRow, StoryCorroborationRow | None]]:
    scored: list[tuple[int, int, int, tuple[StoryRow, StoryCorroborationRow | None]]] = []
    for story, corro in rows:
        gist = gists.get(story.id)
        title = (story.title or "").lower()
        trust_text = " ".join(
            p
            for p in (
                title,
                gist.gist.lower() if gist and gist.gist else "",
                gist.category.lower() if gist and gist.category else "",
                gist.escalating.lower() if gist and gist.escalating else "",
                member_texts.get(story.id, ""),
            )
            if p
        )
        score = sum((4 if term in title else 1) for term in terms if term in trust_text)
        if score:
            scored.append((score, story.outlet_count, story.member_count, (story, corro)))
    scored.sort(key=lambda row: (-row[0], -row[1], -row[2]))
    return [row for *_unused, row in scored]


def build_qa_stories(
    session: Session,
    *,
    limit: int = _QA_STORIES,
    now: datetime | None = None,
    question: str | None = None,
) -> list[dict[str, Any]]:
    """Relevant recent stories, provenance-tagged with trust signals + outlet sources."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=_QA_WINDOW_H)
    candidate_limit = max(limit, _QA_CANDIDATES)
    candidate_rows = session.execute(
        select(StoryRow, StoryCorroborationRow)
        .outerjoin(StoryCorroborationRow, StoryCorroborationRow.story_id == StoryRow.id)
        .where(StoryRow.last_seen >= cutoff)
        .order_by(StoryRow.outlet_count.desc(), StoryRow.member_count.desc())
        .limit(candidate_limit)
    ).all()
    story_ids = [s.id for s, _ in candidate_rows]
    if not story_ids:
        return []

    gists = {
        g.story_id: g
        for g in session.execute(
            select(StoryGistRow).where(
                StoryGistRow.story_id.in_(story_ids),
                StoryGistRow.method_version == enrich.METHOD_VERSION,
            )
        ).scalars()
    }
    terms = _question_terms(question)
    if terms:
        rows = _rank_story_rows(
            candidate_rows,
            gists=gists,
            member_texts=_member_texts(session, story_ids),
            terms=terms,
        )[:limit]
    else:
        rows = candidate_rows[:limit]
    story_ids = [s.id for s, _ in rows]
    if not story_ids:
        return []

    divs: dict[int, float] = {}
    for sid, div in session.execute(
        select(StoryDisagreementRow.story_id, StoryDisagreementRow.divergence).where(
            StoryDisagreementRow.story_id.in_(story_ids)
        )
    ).all():
        divs[sid] = max(divs.get(sid, 0.0), float(div))
    sensors: dict[int, dict[str, str]] = {}
    for c in session.execute(
        select(StorySensorCheckRow).where(StorySensorCheckRow.story_id.in_(story_ids))
    ).scalars():
        sensors.setdefault(c.story_id, {})[c.claim_type] = c.verdict

    from app.sources.rss_registry import load_feed_configs

    pretty = {cfg.source: cfg.pretty_name for cfg in load_feed_configs()}

    out: list[dict[str, Any]] = []
    for i, (story, corro) in enumerate(rows, 1):
        srcs = (
            session.execute(
                select(EventRow.source)
                .join(StoryMemberRow, StoryMemberRow.event_id == EventRow.id)
                .where(StoryMemberRow.story_id == story.id)
                .distinct()
                .limit(_MAX_OUTLETS)
            )
            .scalars()
            .all()
        )
        div = divs.get(story.id)
        out.append(
            {
                "n": i,
                "story_id": story.id,
                "title": story.title,
                "gist": gists[story.id].gist if story.id in gists else None,
                "corroboration": round(float(corro.score), 3) if corro else None,
                "outlet_count": story.outlet_count,
                "owner_count": story.owner_count,
                "divergence": round(div, 3) if div is not None else None,
                "contested": bool(div is not None and div >= CONTESTED_THRESHOLD),
                "sensor": sensors.get(story.id, {}),
                "sources": [pretty.get(s, s) for s in srcs],
            }
        )
    return out


def build_qa_context(
    session: Session, *, now: datetime | None = None, question: str | None = None
) -> dict[str, Any]:
    snapshot = context.build_snapshot(session, now=now)
    return {
        **snapshot,
        "latest_composite": _latest_composite(session),
        "most_contested": _most_contested(session),
        "scoreboard": _scoreboard(session),
        "stories": build_qa_stories(session, now=now, question=question),
    }


def build_qa_prompt(qa_context: dict[str, Any], question: str) -> str:
    return (
        "You are the Q&A brain of an OSINT early-warning system. Answer the user's "
        "question using ONLY the JSON context below. The context includes a numbered "
        '"stories" list selected by local question-driven retrieval; each story has a '
        "corroboration score (how many INDEPENDENT outlets tell it), a contested flag "
        "(do tellers disagree sharply), and sensor verdicts (machine-confirmed claims).\n\n"
        "Rules:\n"
        "- Answer only from the context. If it is not there, reply exactly: "
        f"{REFUSAL_ANSWER} Invent no facts, names, places, or numbers.\n"
        "- When a claim rests on a story, cite it as [n] using that story's number.\n"
        "- Every non-refusal answer that uses any story MUST include at least one valid "
        "[n] citation from the numbered stories list.\n"
        "- Flag trust: call out a story that is single-source (low corroboration or "
        "owner_count 1), contested (contested: true), or sensor-unconfirmed. Prefer "
        "corroborated stories; never present a single-teller claim as established fact.\n\n"
        'Return a JSON object with exactly one key: "answer" (a short plain-English '
        "string).\n\n"
        f"CONTEXT:\n{json.dumps(qa_context, ensure_ascii=False)}\n\n"
        f"QUESTION: {question}"
    )


def citation_numbers(answer: str) -> list[int]:
    return [int(match.group(1)) for match in _CITATION_RE.finditer(answer)]


def strip_bad_citations(answer: str, n_sources: int) -> str:
    """Remove [n] citations that point past the sources we actually supplied."""
    return _CITATION_RE.sub(
        lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_sources else "", answer
    ).strip()


def invalid_citations(answer: str, n_sources: int) -> list[int]:
    return [n for n in citation_numbers(answer) if n < 1 or n > n_sources]


def valid_citations(answer: str, n_sources: int) -> list[int]:
    return [n for n in citation_numbers(answer) if 1 <= n <= n_sources]


def requires_citation(answer: str, n_sources: int) -> bool:
    return n_sources > 0 and answer.strip() != REFUSAL_ANSWER


def citation_compliant(answer: str, n_sources: int) -> bool:
    if not requires_citation(answer, n_sources):
        return True
    return bool(valid_citations(answer, n_sources))


def build_citation_repair_prompt(qa_context: dict[str, Any], question: str, answer: str) -> str:
    return (
        "Rewrite the draft answer so it satisfies the citation rules. Use ONLY the "
        "JSON context below. If the context does not support the draft, reply exactly: "
        f"{REFUSAL_ANSWER}\n\n"
        "Rules:\n"
        "- Every non-refusal answer MUST include at least one valid [n] citation from "
        'the numbered "stories" list.\n'
        "- Remove unsupported claims instead of inventing citations.\n"
        '- Return a JSON object with exactly one key: "answer".\n\n'
        f"CONTEXT:\n{json.dumps(qa_context, ensure_ascii=False)}\n\n"
        f"QUESTION: {question}\n"
        f"DRAFT_ANSWER: {answer}"
    )
