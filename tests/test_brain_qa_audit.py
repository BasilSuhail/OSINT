"""Human answer-audit sheet generator + scorer (#413 roadmap item 9, #471)."""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import qa_audit, qa_rubric
from app.db_models import Base
from tests.test_brain_qa_stories import _add_story


def test_audit_question_set_is_rubric_plus_live():
    rubric = [spec.question for spec in qa_rubric.EVAL_QUESTIONS]
    assert list(qa_audit.AUDIT_QUESTIONS[: len(rubric)]) == rubric
    assert qa_audit.AUDIT_QUESTIONS[len(rubric) :] == qa_audit.LIVE_QUESTIONS
    assert len(qa_audit.AUDIT_QUESTIONS) == 12


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_run_audit_collects_answer_aids():
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _session()
    sid = _add_story(
        session,
        now,
        title="War strikes resume at the border",
        source="reuters",
        source_event_id="e1",
        outlet_count=3,
        category="conflict",
        gist="Cross-border strikes after the truce.",
    )

    def ask(question):
        return {
            "answer": "Strikes resumed at the border [1]. Aliens landed too [1].",
            "sources": [{"n": 1, "story_id": sid, "title": "Strikes resume", "outlets": ["R"]}],
            "closest_matches": [],
        }

    rows = qa_audit.run_audit(ask=ask, session=session, questions=("is the war back on?",), now=now)

    row = rows[0]
    assert row["question"] == "is the war back on?"
    assert row["unsupported_claims"] == 1  # the aliens sentence
    assert row["sources"][0]["age"] == "0.0 hours ago"  # joined from the recomputed context
    assert row["trace"]["method"] in {"semantic", "keyword"}
    assert row["trace"]["intents"] == ["conflict"]


def test_build_sheet_has_grade_cells_per_question():
    rows = [
        {
            "question": "q one?",
            "answer": "line one\nline two [1]",
            "sources": [
                {"n": 1, "story_id": 5, "title": "T", "outlets": ["BBC"], "age": "2.1 hours ago"}
            ],
            "closest_matches": [],
            "unsupported_claims": 0,
            "trace": {"method": "semantic", "intents": [], "candidates": 3, "intent_rejected": []},
        },
        {
            "question": "q two?",
            "answer": "",
            "sources": [],
            "closest_matches": [{"n": 1, "story_id": 6, "title": "C", "outlets": []}],
            "unsupported_claims": 2,
            "trace": {},
        },
    ]

    sheet = qa_audit.build_sheet(rows, created="2026-07-17", model="m4b")

    assert "# Answer audit — 2026-07-17" in sheet
    assert "## 1. q one?" in sheet
    assert "## 2. q two?" in sheet
    assert "line one line two [1]" in sheet  # newlines flattened
    assert "[1] BBC (2.1 hours ago)" in sheet
    assert "- closest_matches: [1] C" in sheet
    assert sheet.count("| ? | ? | ? | ? |") == 2
    assert "| accuracy | citation | bias | refusal |" in sheet


def test_score_roundtrip_counts_grades():
    rows = [
        {
            "question": f"q{i}?",
            "answer": "a",
            "sources": [],
            "closest_matches": [],
            "unsupported_claims": 0,
            "trace": {},
        }
        for i in range(3)
    ]
    sheet = qa_audit.build_sheet(rows, created="2026-07-17", model="m")
    graded = sheet.replace("| ? | ? | ? | ? |", "| pass | fail | pass | pass |", 1)
    graded = graded.replace("| ? | ? | ? | ? |", "| pass | pass | ? | fail |", 1)

    score = qa_audit.score_sheet(graded)

    assert score["answers"] == 3
    assert score["fully_graded"] == 1
    assert score["dimensions"]["accuracy"] == {"pass": 2, "graded": 2}
    assert score["dimensions"]["citation"] == {"pass": 1, "graded": 2}
    assert score["dimensions"]["bias"] == {"pass": 1, "graded": 1}
    assert score["dimensions"]["refusal"] == {"pass": 1, "graded": 2}

    rendered = qa_audit.render_score(score, source="2026-07-17-answer-audit.md")
    assert "accuracy: 2/2 pass" in rendered
    assert "answers: 3 (1 fully graded)" in rendered


def test_score_main_reports_missing_sheet(tmp_path, monkeypatch):
    monkeypatch.setattr(qa_audit, "AUDITS_DIR", tmp_path / "audits")
    assert qa_audit.main(["score"]) == 1


def test_score_main_reads_latest_sheet(tmp_path, monkeypatch, capsys):
    audits = tmp_path / "audits"
    audits.mkdir()
    (audits / "2026-07-16-answer-audit.md").write_text("| pass | pass | pass | pass |\n")
    (audits / "2026-07-17-answer-audit.md").write_text("| fail | pass | pass | pass |\n")
    monkeypatch.setattr(qa_audit, "AUDITS_DIR", audits)

    assert qa_audit.main(["score"]) == 0
    out = capsys.readouterr().out
    assert "2026-07-17-answer-audit.md" in out  # newest wins
    assert "accuracy: 0/1 pass" in out
