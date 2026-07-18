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
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.brain import client, context, embeddings, enrich
from app.db_models import (
    EventRow,
    PredictionRow,
    ScoreRow,
    StoryCorroborationRow,
    StoryDisagreementRow,
    StoryEmbeddingRow,
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
#: Countries the coverage block carries — loudest first (#413 item 7).
_COVERAGE_COUNTRIES: int = 8
#: Fewer independent content owners than this = thin coverage.
THIN_OWNER_COUNT: int = 3


def build_coverage_bias(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Per-country local feed coverage over the QA window (#413 item 7).

    Transparent bias, not fake neutrality: event share, distinct sources, and
    independent content owners per country. Owners come from the registry's
    content-owner map, so a syndicated feed cannot inflate independence. A
    country is `thin` when its owner diversity sits below THIN_OWNER_COUNT.
    """
    from app.sources.rss_registry import content_owner_map

    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=_QA_WINDOW_H)
    rows = session.execute(
        select(EventRow.country, EventRow.source, func.count())
        .where(EventRow.occurred_at >= cutoff, EventRow.country.is_not(None))
        .group_by(EventRow.country, EventRow.source)
    ).all()
    owner_of = content_owner_map()
    events: dict[str, int] = {}
    sources: dict[str, set[str]] = {}
    owners: dict[str, set[str]] = {}
    for country, source, n in rows:
        events[country] = events.get(country, 0) + int(n)
        sources.setdefault(country, set()).add(source)
        owners.setdefault(country, set()).add(owner_of.get(source, source))
    total = sum(events.values())
    top = sorted(events, key=lambda c: (-events[c], c))[:_COVERAGE_COUNTRIES]
    return {
        "window_h": _QA_WINDOW_H,
        "total_events": total,
        "countries": [
            {
                "country": c,
                "events": events[c],
                "share": round(events[c] / total, 3) if total else 0.0,
                "sources": len(sources[c]),
                "owners": len(owners[c]),
                "thin": len(owners[c]) < THIN_OWNER_COUNT,
            }
            for c in top
        ],
    }


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
        # Live junk observed in real user questions (#441): auxiliaries,
        # question words, and meta-words that describe the asking, not the news.
        "any",
        "are",
        "been",
        "could",
        "had",
        "has",
        "have",
        "how",
        "just",
        "know",
        "like",
        "more",
        "most",
        "said",
        "says",
        "should",
        "some",
        "source",
        "sources",
        "theories",
        "theory",
        "they",
        "thing",
        "things",
        "think",
        "want",
        "was",
        "were",
        "when",
        "which",
        "who",
        "why",
        "will",
        "would",
    }
)
_TERM_RE = re.compile(r"[a-z0-9]{3,}")
_COUNTRY_CODE_RE = re.compile(r"\b[A-Z]{2}\b")
_CITATION_RE = re.compile(r"\[(\d+)\]")
REFUSAL_ANSWER = "I don't have data on that."
NO_EVIDENCE_ANSWER = (
    "I don't have enough local evidence to answer that — closest stories are listed as sources."
)
#: No-answer fallback (#413 roadmap item 3): retrieval itself looks off-topic,
#: so nothing retrieved may be presented as the answer's sources — the API
#: moves them to a separate closest-matches list instead.
NO_LOCAL_EVIDENCE_ANSWER = "I do not have enough local evidence for that question."
#: Operational messages (#474) — the API's typed failure answers. Not model
#: output: exempt from claim checks and never treated as content.
BRAIN_BUSY_ANSWER = "Brain busy — the box is loaded right now, try again in a moment."
BRAIN_OFFLINE_ANSWER = "The brain is offline right now."
BRAIN_NOT_WORKING_ANSWER = "The brain is not working right now."
OPERATIONAL_ANSWERS: tuple[str, ...] = (
    BRAIN_BUSY_ANSWER,
    BRAIN_OFFLINE_ANSWER,
    BRAIN_NOT_WORKING_ANSWER,
)
#: A semantic pick (cosine vs the question) below this is a weak match.
SEMANTIC_RELEVANT_MIN: float = 0.55
#: A keyword pick matching less than this fraction of question terms is weak.
KEYWORD_RELEVANT_MIN: float = 1 / 3


def _age_hours(last_seen: datetime, now: datetime) -> float:
    """Hours since a story last moved (#469). The model gets this per story so
    freshness questions get real ages, not guesses from as_of.

    SQLite hands back naive datetimes; everything stored is UTC."""
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    return round((now - last_seen).total_seconds() / 3600, 1)


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


#: Question terms that reveal which gist category is being asked about
#: (#413 roadmap item 2). Ambiguous terms (coup, protest, sanction, trade)
#: sit in several categories on purpose: they widen the allowed set instead
#: of gating the right stories out.
_INTENT_LEXICON: dict[str, frozenset[str]] = {
    "conflict": frozenset(
        {
            "airstrike",
            "artillery",
            "attack",
            "bombardment",
            "bombing",
            "ceasefire",
            "clash",
            "combat",
            "coup",
            "drone",
            "escalation",
            "fighting",
            "frontline",
            "invasion",
            "militia",
            "missile",
            "offensive",
            "protest",
            "rocket",
            "sanction",
            "shelling",
            "strike",
            "troop",
            "truce",
            "war",
        }
    ),
    "disaster": frozenset(
        {
            "aftershock",
            "cyclone",
            "earthquake",
            "eruption",
            "flood",
            "flooding",
            "hurricane",
            "landslide",
            "magnitude",
            "quake",
            "storm",
            "tsunami",
            "typhoon",
            "volcano",
            "wildfire",
        }
    ),
    "economy": frozenset(
        {
            "currency",
            "economy",
            "gdp",
            "inflation",
            "recession",
            "sanction",
            "tariff",
            "trade",
        }
    ),
    "politics": frozenset(
        {
            "coup",
            "election",
            "impeachment",
            "parliament",
            "protest",
            "referendum",
            "vote",
        }
    ),
}


def question_intents(question: str | None) -> frozenset[str]:
    """Gist categories the question explicitly asks about (#413 roadmap item 2).

    Deterministic lexicon lookup with plural folding ("strikes" → "strike",
    "clashes" → "clash") — no model call. Empty set = no detectable intent,
    retrieval stays ungated.
    """
    if not question:
        return frozenset()
    intents: set[str] = set()
    for token in _TERM_RE.findall(question.lower()):
        forms = {token}
        if token.endswith("es") and len(token) > 4:
            forms.add(token[:-2])
        if token.endswith("s") and len(token) > 3:
            forms.add(token[:-1])
        for category, lexicon in _INTENT_LEXICON.items():
            if forms & lexicon:
                intents.add(category)
    return frozenset(intents)


@lru_cache(maxsize=512)
def _term_pattern(term: str) -> re.Pattern[str]:
    """Whole-word match with naive plural folding: 'explosions' ⇄ 'explosion'.

    Substring scoring was the live failure mode (#441): 'any' matched
    'germany', 'was' matched nearly every gist.
    """
    stem = term[:-1] if term.endswith("s") and len(term) > 3 else term
    return re.compile(rf"\b{re.escape(stem)}s?\b")


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
) -> list[tuple[tuple[StoryRow, StoryCorroborationRow | None], float]]:
    """Keyword-ranked (row, relevance) pairs — relevance is the fraction of
    question terms the story matches (#413 roadmap item 3)."""
    scored: list[tuple[int, int, int, tuple[StoryRow, StoryCorroborationRow | None], float]] = []
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
        patterns = [_term_pattern(term) for term in terms]
        matched = [pattern for pattern in patterns if pattern.search(trust_text)]
        score = sum(4 if pattern.search(title) else 1 for pattern in matched)
        if score:
            fraction = len(matched) / len(patterns)
            scored.append((score, story.outlet_count, story.member_count, (story, corro), fraction))
    scored.sort(key=lambda row: (-row[0], -row[1], -row[2]))
    return [(row, fraction) for *_unused, row, fraction in scored]


_CandidateRows = list[tuple[StoryRow, StoryCorroborationRow | None]]
#: story_id → (retrieval method, relevance). Relevance is cosine for
#: "semantic", matched-term fraction for "keyword", None for "fill" — the
#: loudness-ordered padding that never counts as evidence (#413 item 3).
_RetrievalMeta = dict[int, tuple[str, float | None]]
#: Cap on per-list entries in the debug trace (#413 item 10).
_TRACE_REJECTED: int = 10


def _select_rows(
    session: Session,
    candidate_rows: _CandidateRows,
    *,
    gists: dict[int, StoryGistRow],
    question: str | None,
    anchored: str | None,
    limit: int,
    trace: dict[str, Any] | None = None,
) -> tuple[_CandidateRows, _RetrievalMeta]:
    """Pick the context stories: semantic first, repaired keywords as fallback.

    Intent gate (#413 roadmap item 2): when the bare question names a category
    (war → conflict, typhoon → disaster, …), candidates whose gist category
    contradicts it are dropped before any ranking — a loud typhoon must never
    answer a war question, however well it scores. Ungisted and "other"
    stories stay eligible; an emptied pool returns [] so the answer path
    refuses instead of presenting an unrelated story.

    Semantic path (#441/#451): embed the bare question AND the history-anchored
    text in one batched call, score each candidate by its best match — history
    widens retrieval without drowning the question itself. Vectorless
    candidates fill remaining slots in loudness order. Skipped entirely when no
    candidate has a vector; any embed failure falls back to the keyword ranker.

    Question-understood trace (#413 item 10): pass a dict as `trace` and it is
    filled in place with why retrieval chose what it chose — parsed intents,
    terms, gate rejections, method, and scored-but-rejected candidates.
    Debug/eval-only; behavior is identical when no trace is requested.
    """
    intents = question_intents(question)
    if trace is not None:
        trace.update(
            {
                "intents": sorted(intents),
                "terms": _question_terms(anchored or question),
                "candidates": len(candidate_rows),
                "intent_rejected": [],
                "method": "loudness",
                "rejected": [],
            }
        )
    if intents:
        kept: _CandidateRows = []
        for story, corro in candidate_rows:
            gist = gists.get(story.id)
            if gist is None or gist.category in ("other", None) or gist.category in intents:
                kept.append((story, corro))
            elif trace is not None and len(trace["intent_rejected"]) < _TRACE_REJECTED:
                trace["intent_rejected"].append(
                    {"story_id": story.id, "title": story.title, "category": gist.category}
                )
        candidate_rows = kept
        if not candidate_rows:
            if trace is not None:
                trace["method"] = "none"
            return [], {}
    story_ids = [s.id for s, _ in candidate_rows]
    if question:
        vector_rows = session.execute(
            select(StoryEmbeddingRow.story_id, StoryEmbeddingRow.vector).where(
                StoryEmbeddingRow.story_id.in_(story_ids),
                StoryEmbeddingRow.method_version == embeddings.EMBED_METHOD_VERSION,
            )
        ).all()
        if vector_rows:
            query_texts = [question]
            if anchored and anchored != question:
                query_texts.append(anchored)
            try:
                query_vectors = client.embed(query_texts)
            except Exception:
                query_vectors = None
                if trace is not None:
                    trace["embed_failed"] = True
            if query_vectors:
                candidates = [(sid, vec) for sid, vec in vector_rows]
                best: dict[int, float] = {}
                for query_vector in query_vectors:
                    for sid, score in embeddings.cosine_rank(query_vector, candidates):
                        if score > best.get(sid, float("-inf")):
                            best[sid] = score
                ranked_ids = sorted(best, key=lambda sid: -best[sid])
                by_id = {s.id: (s, c) for s, c in candidate_rows}
                chosen = [by_id[sid] for sid in ranked_ids[:limit] if sid in by_id]
                meta: _RetrievalMeta = {s.id: ("semantic", round(best[s.id], 3)) for s, _ in chosen}
                if trace is not None:
                    trace["method"] = "semantic"
                    trace["rejected"] = [
                        {
                            "story_id": sid,
                            "title": by_id[sid][0].title,
                            "relevance": round(best[sid], 3),
                        }
                        for sid in ranked_ids[limit : limit + _TRACE_REJECTED]
                        if sid in by_id
                    ]
                if len(chosen) < limit:
                    have = {s.id for s, _ in chosen}
                    fill = [rc for rc in candidate_rows if rc[0].id not in have]
                    chosen.extend(fill)
                    meta.update({s.id: ("fill", None) for s, _ in fill})
                return chosen[:limit], meta
    terms = _question_terms(anchored or question)
    if terms:
        ranked = _rank_story_rows(
            candidate_rows,
            gists=gists,
            member_texts=_member_texts(session, story_ids),
            terms=terms,
        )
        if trace is not None:
            trace["method"] = "keyword"
            trace["rejected"] = [
                {"story_id": row[0].id, "title": row[0].title, "relevance": round(fraction, 3)}
                for row, fraction in ranked[limit : limit + _TRACE_REJECTED]
            ]
        ranked = ranked[:limit]
        return (
            [row for row, _ in ranked],
            {row[0].id: ("keyword", round(fraction, 3)) for row, fraction in ranked},
        )
    rows = candidate_rows[:limit]
    return rows, {s.id: ("fill", None) for s, _ in rows}


def build_qa_stories(
    session: Session,
    *,
    limit: int = _QA_STORIES,
    now: datetime | None = None,
    question: str | None = None,
    history: list[dict[str, Any]] | None = None,
    trace: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Relevant recent stories, provenance-tagged with trust signals + outlet sources."""
    now = now or datetime.now(UTC)
    if trace is not None:
        trace.update(
            {
                "question": question,
                "anchored": None,
                "intents": [],
                "terms": [],
                "candidates": 0,
                "intent_rejected": [],
                "method": "none",
                "rejected": [],
                "selected": [],
            }
        )
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
    anchored = build_retrieval_text(question, history) if question else question
    if trace is not None and anchored != question:
        trace["anchored"] = anchored
    rows, retrieval_meta = _select_rows(
        session,
        candidate_rows,
        gists=gists,
        question=question,
        anchored=anchored,
        limit=limit,
        trace=trace,
    )
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
                #: Unit spelled out in the value (#475) — the audit's 4b read a
                #: bare `age_h: 47.8` as YEARS ("the data is 47.8 years old").
                "age": f"{_age_hours(story.last_seen, now)} hours ago",
                "gist": gists[story.id].gist if story.id in gists else None,
                "corroboration": round(float(corro.score), 3) if corro else None,
                "outlet_count": story.outlet_count,
                "owner_count": story.owner_count,
                "divergence": round(div, 3) if div is not None else None,
                "contested": bool(div is not None and div >= CONTESTED_THRESHOLD),
                "sensor": sensors.get(story.id, {}),
                "sources": [pretty.get(s, s) for s in srcs],
                "retrieval": retrieval_meta.get(story.id, ("fill", None))[0],
                "relevance": retrieval_meta.get(story.id, ("fill", None))[1],
            }
        )
    if trace is not None:
        trace["selected"] = [
            {
                "n": s["n"],
                "story_id": s["story_id"],
                "title": s["title"],
                "retrieval": s["retrieval"],
                "relevance": s["relevance"],
            }
            for s in out
        ]
    return out


#: How much of a previous answer rides along for retrieval anchoring (#444).
_HISTORY_ANSWER_CHARS: int = 300
#: The prompt sees far less of each previous answer (#451) — enough to resolve
#: "that", too little to parrot back.
_PROMPT_ANSWER_CHARS: int = 120
#: Exchanges the prompt may carry — mirrors the API's max_length cap.
MAX_HISTORY: int = 3

_ECHO_NGRAM: int = 5
_ECHO_THRESHOLD: float = 0.3


def _shingles(text: str, n: int = _ECHO_NGRAM) -> set[tuple[str, ...]]:
    tokens = _TERM_RE.findall(text.lower())
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def answer_echoes(previous: str, current: str) -> bool:
    """Did the model recycle its previous answer? (#451)

    Word 5-gram overlap against the smaller answer — catches copied and
    lightly-edited sentences. Canned answers (refusal, no-evidence) are exempt:
    repeating an honest refusal is correct behaviour, not an echo.
    """
    if not previous or not current:
        return False
    canned = (REFUSAL_ANSWER, NO_EVIDENCE_ANSWER, NO_LOCAL_EVIDENCE_ANSWER)
    if previous.strip() in canned or current.strip() in canned:
        return False
    a = _shingles(previous)
    b = _shingles(current)
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= _ECHO_THRESHOLD


def build_retrieval_text(question: str, history: list[dict[str, Any]] | None) -> str:
    """The text retrieval matches on: the question plus the last exchange.

    A vague follow-up ("what do u think that was?") carries no topic of its
    own — folding in the previous turn lets both the embedding and the keyword
    fallback inherit it.
    """
    if not history:
        return question
    last = history[-1]
    previous_question = str(last.get("question") or "")
    previous_answer = str(last.get("answer") or "")[:_HISTORY_ANSWER_CHARS]
    return " ".join(part for part in (question, previous_question, previous_answer) if part)


def _conversation_block(history: list[dict[str, Any]] | None) -> str:
    if not history:
        return ""
    turns = "\n".join(
        f"Q: {h.get('question', '')}\nA: {str(h.get('answer', ''))[:_PROMPT_ANSWER_CHARS]}"
        for h in history[-MAX_HISTORY:]
    )
    return (
        "RECENT CONVERSATION (ONLY for resolving references like 'that' or 'it'. "
        "Never repeat or rephrase these earlier answers — the new answer must be "
        "freshly worded from CONTEXT and answer only the NEW question):\n"
        f"{turns}\n\n"
    )


def build_qa_context(
    session: Session,
    *,
    now: datetime | None = None,
    question: str | None = None,
    history: list[dict[str, Any]] | None = None,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The model's JSON context. `trace` (debug/eval-only, #413 item 10) is
    filled in place with the retrieval explanation and stays OUT of the
    returned context — the model never sees it and the digest is unchanged."""
    snapshot = context.build_snapshot(session, now=now)
    return {
        **snapshot,
        "latest_composite": _latest_composite(session),
        "most_contested": _most_contested(session),
        "scoreboard": _scoreboard(session),
        "coverage": build_coverage_bias(session, now=now),
        "stories": build_qa_stories(
            session, now=now, question=question, history=history, trace=trace
        ),
    }


def build_qa_prompt(
    qa_context: dict[str, Any],
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    return (
        "You are the Q&A brain of an OSINT early-warning system. Answer the user's "
        "question using ONLY the JSON context below. The context includes a numbered "
        '"stories" list selected by local question-driven retrieval; each story has a '
        "corroboration score (how many INDEPENDENT outlets tell it), a contested flag "
        "(do tellers disagree sharply), sensor verdicts (machine-confirmed claims), and "
        '"age" — how long ago the story last moved, always in hours '
        "(e.g. '3.3 hours ago').\n\n"
        "Rules:\n"
        "- Write like a sharp, neutral analyst talking to a person: plain "
        "conversational English, direct and specific, no boilerplate.\n"
        "- Speak as an analyst who read the local reporting — never say 'the "
        "context', 'the provided context', or 'the available data'. Say 'local "
        "reporting shows…' or 'no local reporting covers…' instead.\n"
        "- Answer THE question asked, freshly worded every time. Never repeat or "
        "rephrase an earlier answer from RECENT CONVERSATION.\n"
        "- If the question asks for a number, date, or name and the context has "
        "it, lead with it in the first sentence.\n"
        "- Direct yes/no questions get a direct opening — yes, no, or unclear, "
        "with its qualifier — then the evidence.\n"
        "- Opinion or judgement questions (who is right, who is the bad guy): do "
        "not take sides. Say the data supports no judgement, then lay out what "
        "each side says or emphasizes, and leave the conclusion to the reader.\n"
        "- Answer only from the context. Invent no facts, names, places, or "
        "numbers.\n"
        "- Refuse ONLY when nothing in the context relates to the question — "
        f"then reply exactly: {REFUSAL_ANSWER} If related stories exist but "
        "answer the question only partly, do not refuse: say what they show, "
        "with caveats, and name what is not known.\n"
        "- When a claim rests on a story, cite it as [n] using that story's number.\n"
        "- Every non-refusal answer that uses any story MUST include at least one valid "
        "[n] citation from the numbered stories list.\n"
        "- A single-source or low-corroboration claim is 'reported', never "
        "established fact. Prefer corroborated stories.\n"
        "- Call out contested stories as disputed and name who says what when "
        "the context shows it.\n"
        "- Say when a claim is sensor-confirmed; mark heavy sensor-unconfirmed "
        "claims as unverified.\n"
        "- Questions about how old or fresh the data is: lead with the newest "
        'story\'s "age" value. Ages are ALWAYS hours — never convert them to '
        "days or years.\n"
        "- Time-window questions ('anything new in the last few hours?'): only "
        "stories whose age falls inside the asked window count as new — cite "
        "the newest first; if every story is older, say nothing new happened "
        "inside that window and give the newest story's age.\n"
        '- CONTEXT.coverage shows per-country local feed coverage (events, share, "sources", '
        'independent "owners", "thin" flag). When the answer centers on a country whose '
        "coverage is thin, say local coverage is thin (few sources/owners) before any "
        "conclusion.\n"
        "- If the context cannot answer part of the question, say what is not "
        "known. Never guess.\n\n"
        'Return a JSON object with exactly one key: "answer" (a short plain-English '
        "string).\n\n"
        f"{_conversation_block(history)}"
        f"CONTEXT:\n{json.dumps(qa_context, ensure_ascii=False)}\n\n"
        f"QUESTION: {question}"
    )


def build_qa_text_prompt(
    qa_context: dict[str, Any],
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> str:
    return build_qa_prompt(qa_context, question, history=history).replace(
        'Return a JSON object with exactly one key: "answer" (a short plain-English string).\n\n',
        "Return only the final plain-English answer text. Do not wrap it in JSON. "
        "Do not include markdown.\n\n",
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
    return n_sources > 0 and answer.strip() not in (
        REFUSAL_ANSWER,
        NO_EVIDENCE_ANSWER,
        NO_LOCAL_EVIDENCE_ANSWER,
    )


def citation_compliant(answer: str, n_sources: int) -> bool:
    if not requires_citation(answer, n_sources):
        return True
    return bool(valid_citations(answer, n_sources))


#: Content terms of a story that must appear in a draft to call it grounded.
_SALVAGE_MIN_TERMS: int = 2


def attach_supported_citation(answer: str, stories: list[dict[str, Any]]) -> str | None:
    """Append the best-matching story's [n] to an uncited but grounded draft (#446).

    Grounded = at least _SALVAGE_MIN_TERMS content terms from one story's
    title+gist appear (word-boundary, plural-folded) in the draft. Returns None
    when nothing grounds the draft — the caller falls through to LLM repair and
    ultimately the deterministic template. Deterministic: no extra model call,
    and the user keeps the prose they watched stream in.
    """
    text = answer.lower()
    best_n = 0
    best_score = 0
    for story in stories:
        terms = _question_terms(f"{story.get('title') or ''} {story.get('gist') or ''}")
        score = sum(1 for term in terms if _term_pattern(term).search(text))
        if score > best_score:
            best_score = score
            best_n = int(story.get("n") or 0)
    if best_n and best_score >= _SALVAGE_MIN_TERMS:
        return f"{answer} [{best_n}]"
    return None


#: Content terms a sentence must share with one story to count as supported,
#: and the minimum for a sentence to be checkable at all (#413 item 4).
_CLAIM_MIN_TERMS: int = 2
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def story_support_texts(session: Session, stories: list[dict[str, Any]]) -> dict[int, str]:
    """Story number → lowercased support text: title + gist + member payload
    text/keywords. The widest deterministic ground truth we hold locally."""
    member = _member_texts(session, [int(s["story_id"]) for s in stories])
    return {
        int(s["n"]): " ".join(
            p
            for p in (
                str(s.get("title") or "").lower(),
                str(s.get("gist") or "").lower(),
                member.get(s["story_id"], ""),
            )
            if p
        )
        for s in stories
    }


def trim_incomplete_tail(answer: str) -> str:
    """Drop a truncated trailing fragment (#474).

    The audit shipped "…the chances are high. The stories consistently report
    that Iran and the United States are [1]" — a token-limit cut mid-sentence.
    A sentence whose text (citations aside) does not end in terminal
    punctuation is a fragment: trim it when at least one complete sentence
    remains; a lone fragment stays untouched (something beats nothing, and the
    citation chain still vets it).
    """
    text = answer.strip()
    if not text:
        return answer
    sentences = _SENTENCE_RE.split(text)
    while len(sentences) > 1:
        tail = _CITATION_RE.sub("", sentences[-1]).strip()
        if tail.endswith((".", "!", "?", "…", '"', "'")):
            break
        sentences.pop()
    return " ".join(sentences)


def check_claims(answer: str | None, support_texts: dict[int, str]) -> dict[str, Any]:
    """Sentence-level claim check (#413 item 4): a [n] citation only proves a
    story was in context; this maps each answer sentence to the stories that
    actually back it.

    Deterministic, no model call. A sentence is supported when one story's
    support text matches at least _CLAIM_MIN_TERMS of its content terms — the
    cited stories are checked first, then the whole context, so a right claim
    with the wrong citation stays visible as cited ≠ matched_story. Sentences
    with fewer than _CLAIM_MIN_TERMS content terms are uncheckable and
    skipped; canned and operational answers carry no claims (#474 — the audit
    once counted "The brain is not working right now." as an unsupported claim).
    """
    canned = (
        REFUSAL_ANSWER,
        NO_EVIDENCE_ANSWER,
        NO_LOCAL_EVIDENCE_ANSWER,
        *OPERATIONAL_ANSWERS,
    )
    if not answer or answer.strip() in canned:
        return {"claims": [], "unsupported": 0}
    claims: list[dict[str, Any]] = []
    unsupported = 0
    for sentence in _SENTENCE_RE.split(answer.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        cited = [n for n in citation_numbers(sentence) if n in support_texts]
        patterns = [_term_pattern(t) for t in _question_terms(sentence)]
        if len(patterns) < _CLAIM_MIN_TERMS:
            continue

        def _supports(n: int, patterns=tuple(patterns)) -> bool:
            text = support_texts.get(n, "")
            return sum(1 for p in patterns if p.search(text)) >= _CLAIM_MIN_TERMS

        matched = next((n for pool in (cited, support_texts) for n in pool if _supports(n)), None)
        if matched is None:
            unsupported += 1
        claims.append(
            {
                "text": sentence,
                "cited": cited,
                "supported": matched is not None,
                "matched_story": matched,
            }
        )
    return {"claims": claims, "unsupported": unsupported}


def build_echo_retry_prompt(
    qa_context: dict[str, Any], question: str, answer: str, previous_answer: str
) -> str:
    """One retry when a draft parrots the previous answer (#451)."""
    return (
        "Your draft repeats your previous answer. The user asked a NEW question "
        "and deserves a fresh, specific answer to it.\n\n"
        "Rules:\n"
        "- Answer ONLY the new question, freshly worded. Reuse no sentences from "
        "PREVIOUS_ANSWER.\n"
        "- If the new question asks for a number, date, or name and the context "
        "has it, lead with it.\n"
        "- Use ONLY the JSON context; cite stories as [n]. If the context cannot "
        f"answer, reply exactly: {REFUSAL_ANSWER}\n"
        '- Return a JSON object with exactly one key: "answer".\n\n'
        f"CONTEXT:\n{json.dumps(qa_context, ensure_ascii=False)}\n\n"
        f"NEW QUESTION: {question}\n"
        f"PREVIOUS_ANSWER: {previous_answer}\n"
        f"DRAFT_ANSWER: {answer}"
    )


def build_refusal_retry_prompt(qa_context: dict[str, Any], question: str) -> str:
    """One retry when the model refuses despite relevant local evidence (#467).

    Fired only when retrieval itself judged the stories plausibly relevant
    (has_relevant_evidence, #460) — the model's refusal contradicts its own
    context. A retry that still refuses is kept: refusal beats invention.
    """
    return (
        "You refused, but the numbered stories in the context ARE relevant to "
        "the question. Do not refuse.\n\n"
        "Rules:\n"
        "- Answer from those stories: say what they show, with caveats, and "
        "name what is not known. Partial evidence deserves a partial answer, "
        "not a refusal.\n"
        "- Use ONLY the JSON context; cite stories as [n]. Invent nothing.\n"
        "- Keep uncertainty framing: single-source claims stay 'reported', "
        "contested stays disputed.\n"
        "- Only if truly NOTHING in the context relates to the question, reply "
        f"exactly: {REFUSAL_ANSWER}\n"
        '- Return a JSON object with exactly one key: "answer".\n\n'
        f"CONTEXT:\n{json.dumps(qa_context, ensure_ascii=False)}\n\n"
        f"QUESTION: {question}"
    )


def build_citation_repair_prompt(qa_context: dict[str, Any], question: str, answer: str) -> str:
    return (
        "Rewrite the draft answer so it satisfies the citation rules. Use ONLY the "
        "JSON context below. If the context does not support the draft, reply exactly: "
        f"{REFUSAL_ANSWER}\n\n"
        "Rules:\n"
        "- Every non-refusal answer MUST include at least one valid [n] citation from "
        'the numbered "stories" list.\n'
        "- Remove unsupported claims instead of inventing citations.\n"
        "- Keep uncertainty framing: disputed stays disputed, single-source "
        "stays 'reported'.\n"
        '- Return a JSON object with exactly one key: "answer".\n\n'
        f"CONTEXT:\n{json.dumps(qa_context, ensure_ascii=False)}\n\n"
        f"QUESTION: {question}\n"
        f"DRAFT_ANSWER: {answer}"
    )


def has_relevant_evidence(stories: list[dict[str, Any]]) -> bool:
    """Does any retrieved story plausibly relate to the question? (#413 item 3)

    Judged from retrieval provenance: a semantic pick needs a decent cosine,
    a keyword pick a decent term-match fraction. "fill" padding (loudness
    order, no match signal) never counts as evidence.
    """
    for story in stories:
        relevance = story.get("relevance")
        if relevance is None:
            continue
        retrieval = story.get("retrieval")
        if retrieval == "semantic" and relevance >= SEMANTIC_RELEVANT_MIN:
            return True
        if retrieval == "keyword" and relevance >= KEYWORD_RELEVANT_MIN:
            return True
    return False


def build_no_evidence_answer(stories: list[dict[str, Any]]) -> str:
    """Honest last resort when a draft can be neither salvaged nor repaired.

    Replaces the old "The retrieved story is: ..." template (#446) — Basil
    never wanted a robotic dump in place of the answer. Split into two modes
    (#413 item 3): with plausibly relevant retrieval the closest stories stay
    visible as sources; with weak retrieval the answer must not lean on them
    at all — the API moves them to a separate closest-matches list.
    """
    if not stories:
        return REFUSAL_ANSWER
    return NO_EVIDENCE_ANSWER if has_relevant_evidence(stories) else NO_LOCAL_EVIDENCE_ANSWER
