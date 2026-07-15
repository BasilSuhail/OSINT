from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import qa
from app.db_models import (
    Base,
    PredictionRow,
    ScoreRow,
    StoryDisagreementRow,
    StoryRow,
)


def _seeded(now):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    story = StoryRow(
        title="Border clashes reported",
        first_seen=now - timedelta(hours=3),
        last_seen=now,
        member_count=12,
        outlet_count=7,
        owner_count=3,
        method_version="stories-v1.0",
    )
    session.add(story)
    session.flush()
    story_id = story.id
    session.add_all(
        [
            ScoreRow(
                country="SD",
                bucket_start=now,
                bucket_length=timedelta(days=30),
                score_name="composite",
                score_value=0.81,
                components={},
                method_version="composite-v1.0",
                computed_at=now,
            ),
            ScoreRow(
                country="RU",
                bucket_start=now,
                bucket_length=timedelta(days=30),
                score_name="composite",
                score_value=0.44,
                components={},
                method_version="composite-v1.0",
                computed_at=now,
            ),
            StoryDisagreementRow(
                story_id=story_id,
                divergence=0.83,
                components={},
                method_version="disagreement-v1.0",
                computed_at=now,
            ),
            PredictionRow(
                source="composite",
                method_version="composite-v1.0",
                country="SD",
                bucket_start=now,
                horizon_months=1,
                score=0.7,
                outcome=1,
                payload={},
            ),
            PredictionRow(
                source="composite",
                method_version="composite-v1.0",
                country="RU",
                bucket_start=now,
                horizon_months=1,
                score=0.3,
                outcome=None,
                payload={},
            ),
        ]
    )
    session.commit()
    return session


def test_build_qa_context_has_snapshot_plus_extras():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    ctx = qa.build_qa_context(_seeded(now), now=now)
    # snapshot keys carried through
    assert "top_stories" in ctx and "jobs" in ctx
    # three extra facts
    assert ctx["latest_composite"]["highest_stress"]["country"] == "SD"
    assert ctx["most_contested"]["title"] == "Border clashes reported"
    assert ctx["scoreboard"] == {"graded": 1, "total": 2}


def test_build_qa_context_handles_empty_db():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    ctx = qa.build_qa_context(Session(engine), now=now)
    assert ctx["latest_composite"] is None
    assert ctx["most_contested"] is None
    assert ctx["scoreboard"] == {"graded": 0, "total": 0}


def test_build_qa_prompt_is_grounded_and_bounded():
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    ctx = qa.build_qa_context(_seeded(now), now=now)
    prompt = qa.build_qa_prompt(ctx, "What is most contested?")
    assert "only" in prompt.lower()  # no-fabrication instruction
    assert "What is most contested?" in prompt
    assert '"answer"' in prompt  # asks for the answer schema
    assert len(prompt) < 8000


def test_build_qa_prompt_asks_for_citations_and_flags():
    ctx = {"stories": [{"n": 1, "title": "X", "corroboration": 0.2, "contested": True}]}
    prompt = qa.build_qa_prompt(ctx, "what is going on?")
    low = prompt.lower()
    assert "[n]" in low or "cite" in low
    assert "must include at least one valid" in low
    assert "contested" in low
    assert "single" in low or "corrobor" in low
    assert "what is going on?" in prompt


def test_citation_compliance_requires_valid_citation_for_story_answer():
    assert qa.citation_compliant("Border clashes [1].", 2) is True
    assert qa.citation_compliant("Border clashes [9].", 2) is False
    assert qa.citation_compliant("Border clashes.", 2) is False
    assert qa.citation_compliant(qa.REFUSAL_ANSWER, 2) is True
    assert qa.strip_bad_citations("Good [1], bad [9].", 1) == "Good [1], bad ."


def test_build_cited_fallback_answer_uses_first_story():
    answer = qa.build_cited_fallback_answer(
        [
            {
                "n": 1,
                "title": "Thailand fire kills 27",
                "sources": ["Al Jazeera English", "BBC World"],
                "contested": True,
                "corroboration": 1.0,
                "sensor": {},
            }
        ]
    )

    assert "Thailand fire kills 27 [1]" in answer
    assert "Al Jazeera English" in answer
    assert "contested" in answer.lower()
    assert qa.citation_compliant(answer, 1) is True


def test_qa_prompt_requires_uncertainty_framing():
    prompt = qa.build_qa_prompt({"stories": []}, "is the war back on?")
    assert "never established fact" in prompt
    assert "disputed" in prompt
    assert "sensor-confirmed" in prompt
    assert "what is not known" in prompt


def test_qa_text_prompt_keeps_framing_rules():
    prompt = qa.build_qa_text_prompt({"stories": []}, "q")
    assert "never established fact" in prompt
    assert "Do not wrap it in JSON" in prompt


def test_repair_prompt_keeps_uncertainty_framing():
    prompt = qa.build_citation_repair_prompt({"stories": []}, "q", "draft")
    assert "disputed stays disputed" in prompt
