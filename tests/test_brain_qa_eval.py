from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import qa_eval
from app.db_models import Base


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_evaluate_answer_records_latency_and_invalid_citations(monkeypatch):
    session = _session()
    monkeypatch.setattr(
        qa_eval.qa,
        "build_qa_context",
        lambda session, now=None, question=None: {
            "as_of": "x",
            "stories": [{"n": 1, "story_id": 5, "title": "x", "sources": ["Reuters"]}],
        },
    )
    monkeypatch.setattr(qa_eval.qa, "build_qa_prompt", lambda ctx, question: "prompt")
    ticks = iter([1.0, 1.25])

    def _generate(prompt, *, model, keep_alive):
        assert model == "candidate"
        assert keep_alive == "0"
        return {"answer": "Grounded [1], invented [9]."}

    out = qa_eval.evaluate_answer(
        session,
        spec="q",
        model="candidate",
        now=datetime(2026, 7, 14, tzinfo=UTC),
        generate_json=_generate,
        clock=lambda: next(ticks),
    )

    assert out["ok"] is True
    assert out["elapsed_ms"] == 250
    assert out["cited"] == [1]
    assert out["invalid_citations"] == [9]
    assert out["citation_ok"] is True
    assert out["rubric"]["citation"] is False  # invalid [9] counts against the model
    assert out["rubric"]["passed"] is False


def test_evaluate_answer_scores_rubric_on_error_rows(monkeypatch):
    session = _session()
    monkeypatch.setattr(
        qa_eval.qa,
        "build_qa_context",
        lambda session, now=None, question=None: {"as_of": "x", "stories": []},
    )
    monkeypatch.setattr(qa_eval.qa, "build_qa_prompt", lambda ctx, question: "prompt")

    def _boom(prompt, *, model, keep_alive):
        raise RuntimeError("ollama down")

    out = qa_eval.evaluate_answer(
        session,
        spec="q",
        model="candidate",
        now=datetime(2026, 7, 14, tzinfo=UTC),
        generate_json=_boom,
        clock=iter([1.0, 1.5]).__next__,
    )

    assert out["ok"] is False
    assert out["rubric"]["passed"] is False
    assert all(out["rubric"][d] is False for d in qa_eval.qa_rubric.DIMENSIONS)


def test_evaluate_answer_fails_uncited_story_answer(monkeypatch):
    session = _session()
    monkeypatch.setattr(
        qa_eval.qa,
        "build_qa_context",
        lambda session, now=None, question=None: {
            "as_of": "x",
            "stories": [{"n": 1, "story_id": 5, "title": "x", "sources": ["Reuters"]}],
        },
    )
    monkeypatch.setattr(qa_eval.qa, "build_qa_prompt", lambda ctx, question: "prompt")
    ticks = iter([1.0, 1.25, 1.25])

    out = qa_eval.evaluate_answer(
        session,
        spec="q",
        model="candidate",
        now=datetime(2026, 7, 14, tzinfo=UTC),
        generate_json=lambda prompt, *, model, keep_alive: {"answer": "Uncited."},
        clock=lambda: next(ticks),
    )

    assert out["ok"] is False
    assert out["citation_ok"] is False
    assert "uncited" in out["error"]


def test_evaluate_answer_repairs_uncited_story_answer(monkeypatch):
    session = _session()
    monkeypatch.setattr(
        qa_eval.qa,
        "build_qa_context",
        lambda session, now=None, question=None: {
            "as_of": "x",
            "stories": [{"n": 1, "story_id": 5, "title": "x", "sources": ["Reuters"]}],
        },
    )
    monkeypatch.setattr(qa_eval.qa, "build_qa_prompt", lambda ctx, question: "prompt")
    ticks = iter([1.0, 1.25])
    calls = iter([{"answer": "Uncited."}, {"answer": "Cited [1]."}])

    out = qa_eval.evaluate_answer(
        session,
        spec="q",
        model="candidate",
        now=datetime(2026, 7, 14, tzinfo=UTC),
        generate_json=lambda prompt, *, model, keep_alive: next(calls),
        clock=lambda: next(ticks),
    )

    assert out["ok"] is True
    assert out["answer"] == "Cited [1]."
    assert out["citation_repaired"] is True


def test_run_eval_crosses_questions_and_models(tmp_path, monkeypatch):
    session = _session()
    monkeypatch.setattr(qa_eval.runtime_load.settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(
        qa_eval.qa,
        "build_qa_context",
        lambda session, now=None, question=None: {"as_of": "x", "stories": []},
    )
    monkeypatch.setattr(qa_eval.qa, "build_qa_prompt", lambda ctx, question: "prompt")

    report = qa_eval.run_eval(
        session,
        questions=["q1", "q2"],
        models=["m1", "m2"],
        now=datetime(2026, 7, 14, tzinfo=UTC),
        generate_json=lambda prompt, *, model, keep_alive: {"answer": f"{model} ok"},
    )

    assert report["models"] == ["m1", "m2"]
    assert report["questions"] == ["q1", "q2"]
    assert len(report["results"]) == 4
    assert all(row["ok"] for row in report["results"])
    assert all("rubric" in row for row in report["results"])


def test_render_markdown_summarizes_models():
    report = {
        "created_at": "2026-07-14T00:00:00+00:00",
        "models": ["m1"],
        "questions": ["q"],
        "results": [
            {
                "question": "q",
                "model": "m1",
                "ok": True,
                "elapsed_ms": 12,
                "answer": "A [1]",
                "n_sources": 1,
                "cited": [1],
                "invalid_citations": [],
                "rubric": {
                    "relevance": True,
                    "citation": True,
                    "uncertainty": False,
                    "contested": True,
                    "refusal": True,
                    "usefulness": True,
                    "passed": False,
                    "reasons": ["risky/weakly-sourced answer lacks uncertainty language"],
                },
            }
        ],
    }

    md = qa_eval.render_markdown(report)

    assert "Brain Q&A model evaluation" in md
    assert "| Rubric | relevance |" in md
    assert "| `m1` | 1/1 | 0/1 |" in md
    assert "- rubric_failed: ['uncertainty']" in md
    assert "risky/weakly-sourced answer lacks uncertainty language" in md
    assert "A [1]" in md
