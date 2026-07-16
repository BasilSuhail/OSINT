"""Semantic story vectors for ask retrieval (#441).

The enrich beat embeds each story once (title · gist · top member keywords)
via the tiny local embedder; ask-time retrieval ranks candidates by cosine
against the question's vector. No pgvector — candidates are ≤120 rows, so the
maths happens in-process.
"""

from __future__ import annotations

from collections import Counter

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.brain import client
from app.db_models import EventRow, StoryEmbeddingRow, StoryGistRow, StoryMemberRow, StoryRow
from app.settings import settings

EMBED_METHOD_VERSION: str = "embed-v1.0"

#: Most-frequent member keywords carried into the embed text.
MAX_KEYWORDS: int = 8


def story_embed_text(*, title: str, gist: str | None, keywords: list[str]) -> str:
    parts = [title]
    if gist:
        parts.append(gist)
    if keywords:
        parts.append(" ".join(keywords[:MAX_KEYWORDS]))
    return " · ".join(p for p in parts if p)


def cosine_rank(
    query: list[float], candidates: list[tuple[int, list[float]]]
) -> list[tuple[int, float]]:
    """Candidates as (story_id, vector) → (story_id, cosine) sorted best-first.

    Zero or dimension-mismatched vectors score 0.0 rather than raising — a
    model swap mid-window must degrade, not 500 the ask endpoint.
    """
    q = np.asarray(query, dtype=float)
    q_norm = float(np.linalg.norm(q))
    scored: list[tuple[int, float]] = []
    for story_id, vector in candidates:
        v = np.asarray(vector, dtype=float)
        if v.shape != q.shape:
            scored.append((story_id, 0.0))
            continue
        denom = q_norm * float(np.linalg.norm(v))
        scored.append((story_id, float(q @ v) / denom if denom else 0.0))
    scored.sort(key=lambda item: -item[1])
    return scored


def _story_text(session: Session, story_id: int) -> str:
    title = session.execute(
        select(StoryRow.title).where(StoryRow.id == story_id)
    ).scalar_one_or_none()
    if not title:
        return ""
    #: Latest gist regardless of method version — embeddings must not import
    #: enrich (enrich calls back into this module).
    gist = session.execute(
        select(StoryGistRow.gist)
        .where(StoryGistRow.story_id == story_id)
        .order_by(StoryGistRow.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    counts: Counter[str] = Counter()
    for keywords in session.execute(
        select(EventRow.keywords)
        .join(StoryMemberRow, StoryMemberRow.event_id == EventRow.id)
        .where(StoryMemberRow.story_id == story_id)
    ).scalars():
        counts.update(str(k) for k in (keywords or []))
    top = [k for k, _ in counts.most_common(MAX_KEYWORDS)]
    return story_embed_text(title=title, gist=gist, keywords=top)


def _insert_embedding_if_absent(session: Session, *, story_id: int, vector: list[float]) -> bool:
    values = {
        "story_id": story_id,
        "model": settings.embed_model,
        "method_version": EMBED_METHOD_VERSION,
        "vector": vector,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        base = pg_insert(StoryEmbeddingRow).values(values)
    elif dialect == "sqlite":
        base = sqlite_insert(StoryEmbeddingRow).values(values)
    else:
        raise NotImplementedError(f"_insert_embedding_if_absent: unsupported dialect {dialect!r}")
    stmt = base.on_conflict_do_nothing(index_elements=["story_id", "method_version"]).returning(
        StoryEmbeddingRow.id
    )
    inserted = session.execute(stmt).scalar_one_or_none()
    session.commit()
    return inserted is not None


def embed_missing_stories(session: Session, story_ids: list[int]) -> dict[str, int]:
    """Embed every story in `story_ids` lacking a current-version vector.

    One batched client.embed call per invocation; an embed failure counts and
    returns rather than failing the caller's job.
    """
    counters = {"embedded": 0, "skipped_existing": 0, "failed": 0}
    if not story_ids:
        return counters
    existing = set(
        session.execute(
            select(StoryEmbeddingRow.story_id).where(
                StoryEmbeddingRow.story_id.in_(story_ids),
                StoryEmbeddingRow.method_version == EMBED_METHOD_VERSION,
            )
        ).scalars()
    )
    counters["skipped_existing"] = sum(1 for sid in story_ids if sid in existing)
    pending = [
        (sid, text)
        for sid in story_ids
        if sid not in existing and (text := _story_text(session, sid))
    ]
    if not pending:
        return counters
    try:
        vectors = client.embed([text for _, text in pending])
    except Exception:
        counters["failed"] = len(pending)
        return counters
    for (story_id, _), vector in zip(pending, vectors, strict=False):
        if _insert_embedding_if_absent(session, story_id=story_id, vector=vector):
            counters["embedded"] += 1
        else:
            counters["skipped_existing"] += 1
    return counters
