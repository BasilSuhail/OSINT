"""Journal worker body — emit new predictions from composite scores, then grade.

Orchestrates DB-and-files around the pure layers. Called by the daily Celery
beat task in `app.tasks` and by the `make journal` CLI.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composite.config import DEFAULT_METHOD_VERSION
from app.db import get_engine
from app.db_models import LabelRow, PredictionRow, ScoreRow
from app.journal.emit import predictions_from_scores, upsert_predictions
from app.journal.grade import grade_pending
from app.labels.acled_loader import load_acled_weekly
from app.panel.spine import coverage_windows
from app.settings import settings

_SCORE_NAME = "composite"


def _journal_daily_body() -> dict[str, Any]:
    """Emit + grade once; returns counters for logging/inspection."""
    from app.jobs.heartbeat import job_run

    factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    with job_run("journal", session_factory=factory):
        return _journal_daily_inner()


def _journal_daily_inner() -> dict[str, Any]:
    engine = get_engine()
    with Session(engine) as session:
        scores = [
            {
                "country": row.country,
                "bucket_start": row.bucket_start,
                "score_value": row.score_value,
                "components": row.components,
                "method_version": row.method_version,
            }
            for row in session.execute(
                select(ScoreRow).where(
                    ScoreRow.score_name == _SCORE_NAME,
                    ScoreRow.method_version == DEFAULT_METHOD_VERSION,
                )
            ).scalars()
        ]
        issued = upsert_predictions(predictions_from_scores(scores), session)

        graded = 0
        if settings.acled_csv_dir:
            try:
                coverage = coverage_windows(load_acled_weekly(settings.acled_csv_dir).rows)
            except FileNotFoundError:
                coverage = {}
            if coverage:
                label_months = {
                    (row.country, row.bucket_start)
                    for row in session.execute(select(LabelRow)).scalars()
                }
                graded = grade_pending(session, label_months, coverage)

        total = session.execute(select(PredictionRow.id)).fetchall()
        return {"issued": issued, "graded_now": graded, "total_predictions": len(total)}
