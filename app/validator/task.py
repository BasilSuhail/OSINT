"""Validator worker body — nightly claim extraction over window stories.

For stories in the clustering window without a claims row (under the current
method version), build the prompt from member titles, call the local model,
mechanically validate, and persist. Batch-capped so the nightly run stays a
bounded load on the Pi. Called by the nightly beat in `app.tasks` and by
`make validator`.

Guardrail: these rows feed NOTHING until `make validator-audit`'s human
sample has been filled and an agreement rate published (later WS-G step).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_engine
from app.db_models import EventRow, StoryClaimRow, StoryMemberRow, StoryRow
from app.settings import settings
from app.stories.task import WINDOW_HOURS
from app.validator.claims import METHOD_VERSION, PROMPT_VERSION, build_prompt, parse_claims
from app.validator.client import generate_json

#: How many member titles the prompt carries — enough signal, bounded tokens.
MAX_TITLES: int = 5


#: The batch must end well inside Celery's 1 h redis visibility timeout, or
#: the broker redelivers a live batch and two instances race (#382).
TIME_BUDGET_S: int = 20 * 60


def _validator_body(
    *,
    now: datetime | None = None,
    batch_limit: int | None = None,
    time_budget_s: int | None = None,
) -> dict[str, Any]:
    from app.jobs.heartbeat import job_run

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    with job_run("validator", session_factory=factory):
        return _validator_inner(now=now, batch_limit=batch_limit, time_budget_s=time_budget_s)


def _validator_inner(
    *,
    now: datetime | None = None,
    batch_limit: int | None = None,
    time_budget_s: int | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=WINDOW_HOURS)
    limit = batch_limit if batch_limit is not None else settings.validator_batch_limit
    budget = time_budget_s if time_budget_s is not None else TIME_BUDGET_S
    started = monotonic()
    counters: dict[str, Any] = {
        "window_stories": 0,
        "extracted": 0,
        "failed": 0,
        "skipped_existing": 0,
        "budget_stopped": False,
    }

    with Session(get_engine()) as session:
        stories = (
            session.execute(
                select(StoryRow)
                .where(StoryRow.last_seen >= cutoff)
                .order_by(StoryRow.last_seen.desc())
            )
            .scalars()
            .all()
        )
        counters["window_stories"] = len(stories)

        for story in stories:
            if counters["extracted"] >= limit:
                break
            if monotonic() - started >= budget:
                counters["budget_stopped"] = True
                break
            existing = session.execute(
                select(StoryClaimRow.id).where(
                    StoryClaimRow.story_id == story.id,
                    StoryClaimRow.method_version == METHOD_VERSION,
                )
            ).scalar_one_or_none()
            if existing is not None:
                counters["skipped_existing"] += 1
                continue

            titles = (
                session.execute(
                    select(EventRow.payload)
                    .join(StoryMemberRow, StoryMemberRow.event_id == EventRow.id)
                    .where(StoryMemberRow.story_id == story.id)
                    .limit(MAX_TITLES)
                )
                .scalars()
                .all()
            )
            title_list = [(payload or {}).get("title") or "" for payload in titles]
            if not any(title_list):
                continue

            try:
                raw = generate_json(build_prompt(title_list))
            except Exception:
                counters["failed"] += 1
                continue

            if _insert_claim_if_absent(
                session,
                story_id=story.id,
                claims=parse_claims(raw),
                now=now,
            ):
                counters["extracted"] += 1
            else:
                # A concurrent instance won the race between our SELECT and
                # INSERT (#382) — first writer wins, this is a skip.
                counters["skipped_existing"] += 1

    return counters


def _insert_claim_if_absent(
    session: Session, *, story_id: int, claims: dict[str, Any], now: datetime
) -> bool:
    """ON CONFLICT DO NOTHING on the (story, method version) key; True if inserted."""
    values = {
        "story_id": story_id,
        "claims": claims,
        "model": settings.ollama_model,
        "prompt_version": PROMPT_VERSION,
        "method_version": METHOD_VERSION,
        "extracted_at": now,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        base = pg_insert(StoryClaimRow).values(values)
    elif dialect == "sqlite":
        base = sqlite_insert(StoryClaimRow).values(values)
    else:
        raise NotImplementedError(
            f"_insert_claim_if_absent does not support dialect {dialect!r}; add a branch above"
        )
    stmt = base.on_conflict_do_nothing(index_elements=["story_id", "method_version"]).returning(
        StoryClaimRow.id
    )
    inserted = session.execute(stmt).scalar_one_or_none()
    session.commit()
    return inserted is not None
