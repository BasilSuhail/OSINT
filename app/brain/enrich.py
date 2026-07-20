"""The brain's story enrichment (#413) — a light gist + two enum tags per story.

Timely first-look from the 1.5b model on idle windows; complements the nightly
4b claim extraction. No-fabrication: the gist describes only the supplied
headlines, and since #514 that is enforced for figures rather than merely asked
for — a gist carrying a number its headlines lack is retried once and then
dropped. The tags are fixed enums so a small model stays reliable and the
values are filterable — anything off-enum is coerced to a safe fallback.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.brain import client, embeddings, gate, numerals
from app.db import get_engine
from app.db_models import EventRow, StoryGistRow, StoryMemberRow, StoryRow
from app.settings import settings
from app.stories.task import WINDOW_HOURS

CATEGORIES: frozenset[str] = frozenset({"conflict", "economy", "disaster", "politics", "other"})
ESCALATING: frozenset[str] = frozenset({"yes", "no", "unclear"})

METHOD_VERSION: str = "enrich-v1.0"
PROMPT_VERSION: str = "enrich-prompt-v1.0"
GIST_MAX_CHARS: int = 240

#: How many member headlines the prompt carries — enough signal, bounded tokens.
MAX_TITLES: int = 5

DEFAULT_BATCH_LIMIT: int = 20


def build_gist_prompt(titles: list[str], *, rejected: list[float] | None = None) -> str:
    headlines = "\n".join(f"- {t}" for t in titles if t)
    correction = ""
    if rejected:
        figures = ", ".join(_format_figure(v) for v in rejected)
        correction = (
            "\n\nYour previous answer stated figures the headlines do not carry: "
            f"{figures}. Use only numbers that appear in the headlines below, or "
            "write the gist without numbers.\n"
        )
    return (
        "You summarize a news story for an OSINT dashboard. Below are the "
        "headlines of the outlets telling one story. Using ONLY these headlines "
        "(invent nothing), return a JSON object with exactly these keys:\n"
        '  "gist": one short plain-English sentence, what this story is.\n'
        '  "category": one of conflict, economy, disaster, politics, other.\n'
        '  "escalating": one of yes, no, unclear — is the situation intensifying?'
        f"{correction}\n\n"
        f"HEADLINES:\n{headlines}"
    )


def _format_figure(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def parse_gist(raw: dict[str, Any]) -> dict[str, str]:
    gist = raw.get("gist")
    gist = gist.strip()[:GIST_MAX_CHARS] if isinstance(gist, str) else ""
    category = raw.get("category")
    category = category if isinstance(category, str) and category in CATEGORIES else "other"
    escalating = raw.get("escalating")
    escalating = (
        escalating if isinstance(escalating, str) and escalating in ESCALATING else "unclear"
    )
    return {"gist": gist, "category": category, "escalating": escalating}


def _pretty(payload: dict[str, str]) -> str:
    """Compact JSON — handy for `make enrich` output and debugging."""
    return json.dumps(payload, ensure_ascii=False)


def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def _titles_for(session: Session, story_id: int) -> list[str]:
    payloads = (
        session.execute(
            select(EventRow.payload)
            .join(StoryMemberRow, StoryMemberRow.event_id == EventRow.id)
            .where(StoryMemberRow.story_id == story_id)
            .limit(MAX_TITLES)
        )
        .scalars()
        .all()
    )
    return [(p or {}).get("title") or "" for p in payloads]


def _grounded_gist(titles: list[str]) -> dict[str, str] | None:
    """A gist whose figures all appear in `titles`, or None after one retry.

    The gist is what the Q&A model quotes, so a casualty figure the sources do
    not carry must never be stored (#514). The retry names the offending
    figures — a small model corrects far more often when told what was wrong.
    """
    parsed = parse_gist(client.generate_json(build_gist_prompt(titles)))
    invented = numerals.unsupported_numerals(parsed["gist"], titles)
    if not invented:
        return parsed
    parsed = parse_gist(client.generate_json(build_gist_prompt(titles, rejected=invented)))
    if numerals.unsupported_numerals(parsed["gist"], titles):
        return None
    return parsed


def _insert_gist_if_absent(session: Session, *, story_id: int, parsed: dict[str, str]) -> bool:
    values = {
        "story_id": story_id,
        "gist": parsed["gist"],
        "category": parsed["category"],
        "escalating": parsed["escalating"],
        "model": settings.brain_model,
        "method_version": METHOD_VERSION,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        base = pg_insert(StoryGistRow).values(values)
    elif dialect == "sqlite":
        base = sqlite_insert(StoryGistRow).values(values)
    else:
        raise NotImplementedError(f"_insert_gist_if_absent: unsupported dialect {dialect!r}")
    stmt = base.on_conflict_do_nothing(index_elements=["story_id", "method_version"]).returning(
        StoryGistRow.id
    )
    inserted = session.execute(stmt).scalar_one_or_none()
    session.commit()
    return inserted is not None


def _enrich_body(*, now: datetime | None = None, batch_limit: int | None = None) -> dict[str, Any]:
    from app.jobs.heartbeat import job_run

    now = now or datetime.now(UTC)
    limit = batch_limit if batch_limit is not None else DEFAULT_BATCH_LIMIT
    factory = _session_factory()
    counters: dict[str, Any] = {
        "window_stories": 0,
        "enriched": 0,
        "skipped_existing": 0,
        "failed": 0,
        "rejected_numeric": 0,
        "embedded": 0,
        "embed_skipped": 0,
        "embed_failed": 0,
    }

    with (
        job_run(gate.BRAIN_ENRICH_JOB_NAME, session_factory=factory, evict_brain=False),
        factory() as session,
    ):
        allowed, reason = gate.should_run(session, now=now)
        if not allowed:
            counters["reason"] = reason
            return counters

        cutoff = now - timedelta(hours=WINDOW_HOURS)
        stories = (
            session.execute(
                select(StoryRow.id)
                .where(StoryRow.last_seen >= cutoff)
                .order_by(StoryRow.last_seen.desc())
            )
            .scalars()
            .all()
        )
        counters["window_stories"] = len(stories)

        for story_id in stories:
            if counters["enriched"] >= limit:
                break
            existing = session.execute(
                select(StoryGistRow.id).where(
                    StoryGistRow.story_id == story_id,
                    StoryGistRow.method_version == METHOD_VERSION,
                )
            ).scalar_one_or_none()
            if existing is not None:
                counters["skipped_existing"] += 1
                continue
            titles = [t for t in _titles_for(session, story_id) if t]
            if not titles:
                continue
            try:
                parsed = _grounded_gist(titles)
            except Exception:
                counters["failed"] += 1
                continue
            if parsed is None:
                #: Invented a figure twice running (#514). Nothing is stored, so
                #: the story is simply picked up again on a later pass.
                counters["rejected_numeric"] += 1
                continue
            if _insert_gist_if_absent(session, story_id=story_id, parsed=parsed):
                counters["enriched"] += 1
            else:
                counters["skipped_existing"] += 1

        #: Semantic retrieval vectors (#441) ride the same beat: one batched
        #: embed call for window stories still missing a current-version vector.
        embed_counters = embeddings.embed_missing_stories(session, list(stories))
        counters["embedded"] = embed_counters["embedded"]
        counters["embed_skipped"] = embed_counters["skipped_existing"]
        counters["embed_failed"] = embed_counters["failed"]

    return counters
