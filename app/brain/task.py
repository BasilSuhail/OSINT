"""The brain's narrate worker body (#409).

Gated by resource headroom; when allowed, builds the snapshot, asks the small
model to narrate it, and persists one row. Runs inside job_run with
evict_brain=False so it never evicts the very model it is about to use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.brain import client, context, gate
from app.db import get_engine
from app.db_models import BrainNarrativeRow
from app.settings import settings

#: The four keys the prompt asks for; anything else the model adds is dropped.
_KEYS = ("headline", "world", "system", "watch")


def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def _narrate_body(*, now: datetime | None = None) -> dict[str, Any]:
    from app.jobs.heartbeat import job_run

    now = now or datetime.now(UTC)
    factory = _session_factory()
    with (
        job_run(gate.BRAIN_JOB_NAME, session_factory=factory, evict_brain=False),
        factory() as session,
    ):
        allowed, reason = gate.should_run(session, now=now)
        if not allowed:
            return {"persisted": False, "reason": reason}

        snapshot = context.build_snapshot(session, now=now)
        raw = client.generate_json(context.build_prompt(snapshot))
        payload = {key: raw.get(key) for key in _KEYS}

        session.add(
            BrainNarrativeRow(
                created_at=now,
                model=settings.brain_model,
                payload=payload,
                input_digest=context.input_digest(snapshot),
            )
        )
        session.commit()
        return {"persisted": True, "reason": reason}
