"""Journal worker body — emit new predictions from composite scores, then grade.

Orchestrates DB-and-files around the pure layers. Called by the daily Celery
beat task in `app.tasks` and by the `make journal` CLI.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composite import degeneracy
from app.composite.config import DEFAULT_METHOD_VERSION
from app.db import get_engine
from app.db_models import DisagreementPairRow, LabelRow, PredictionRow, ScoreRow
from app.disagreement.exam import divergence_exposures
from app.disagreement.tellings import METHOD_VERSION as DISAGREEMENT_VERSION
from app.journal.emit import predictions_from_scores, upsert_predictions
from app.journal.grade import grade_pending
from app.labels.acled_loader import load_acled_weekly
from app.panel.spine import coverage_windows
from app.settings import settings

logger = logging.getLogger(__name__)

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
        # Refuse to forecast from a score with no variance (#589). The live
        # composite returns 0.5 for every country because retention deletes the
        # history its rolling z-score needs (#586), and 501 of the 582
        # predictions already issued carry that constant. A constant scores
        # AUROC 0.5 by construction, so those rows cannot become a track record
        # however long they run. This is a check rather than a flag: when the
        # composite varies again, emission resumes with no code change.
        refusal = degeneracy.describe(
            [score["score_value"] for score in scores],
            label=f"{_SCORE_NAME} {DEFAULT_METHOD_VERSION}",
        )
        if refusal is None:
            issued = upsert_predictions(predictions_from_scores(scores), session)
        else:
            issued = 0
            logger.warning("journal: not issuing composite predictions — %s", refusal)

        # WS-B forward exam (#374, pre-registered in docs/disagreement-exam.md):
        # divergence exposures ride the same journal — same hindcast guard,
        # same immutability, same grader, own scoreboard line.
        exposures = divergence_exposures(
            {
                "country_a": row.country_a,
                "country_b": row.country_b,
                "month": row.month,
                "n_stories": row.n_stories,
                "mean_divergence": row.mean_divergence,
            }
            for row in session.execute(
                select(DisagreementPairRow).where(
                    DisagreementPairRow.method_version == DISAGREEMENT_VERSION
                )
            ).scalars()
        )
        issued_disagreement = upsert_predictions(
            predictions_from_scores(exposures, source="disagreement"), session
        )

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
        return {
            "issued": issued,
            "composite_refused": refusal,
            "issued_disagreement": issued_disagreement,
            "graded_now": graded,
            "total_predictions": len(total),
        }
