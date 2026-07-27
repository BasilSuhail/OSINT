"""The scheduled severity pass — keep new headlines graded (#631).

`grade_run` converts a backlog; this keeps up with the feed. Without it the LLM
grade only exists where someone ran a command, and the 30-day news retention
deletes it again: #597 graded 85 rows, and 30 survived. The CII then falls back
to counting vocabulary, which is the failure #591 was written to end.

Small batches on a schedule rather than one long run. A batch that dies costs at
most one batch, the next tick picks the same rows up, and the box is never held
for hours. The grading logic itself is unchanged — same prompt, same model, same
guards — so the agreement measured in #593 still describes what runs.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db import session_scope
from app.jobs.heartbeat import job_run
from app.settings import settings
from app.severity import grade_run

logger = logging.getLogger(__name__)

#: Job name for the heartbeat row, so the pass shows up in the chips UI (#565)
#: alongside every other beat rather than being invisible until someone greps.
JOB_NAME: str = "severity-grade"

#: Headlines per tick. At the twice-hourly cadence in `beat_schedule` this is
#: ~2,400/day against ~863 arriving, so a backlog drains in days and the pass
#: then idles. Kept small so one tick cannot occupy the model for long.
DEFAULT_BATCH_LIMIT: int = 50


def _grade_body(*, batch_limit: int | None = None) -> dict[str, Any]:
    """Grade one batch of ungraded news rows. Returns counters, never raises
    for a single bad verdict — a rejected row keeps the grade it already had."""
    limit = batch_limit if batch_limit is not None else DEFAULT_BATCH_LIMIT
    counters: dict[str, Any] = {"considered": 0, "graded": 0, "rejected": 0}

    with job_run(JOB_NAME) as progress, session_scope() as session:
        rows = grade_run.pending(session, limit=limit)
        counters["considered"] = len(rows)
        if not rows:
            return counters

        for index, row in enumerate(rows, start=1):
            result = grade_run.grade_row(row, model=settings.severity_model)
            if result is None:
                # Guard rejected it (invented numeral, softened wording) or the
                # row has no title. Leave the stored grade alone.
                counters["rejected"] += 1
                continue
            value, payload = result
            row.severity = value
            row.payload = {**(row.payload or {}), **payload}
            counters["graded"] += 1
            progress(f"{index}/{len(rows)} graded")

    return counters
