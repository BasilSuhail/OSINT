"""Sentence-level claim checks (#413 roadmap item 4, #465).

A [n] citation only proves a story was in context. These tests pin the
deterministic sentence → story mapping and the eval artifact's
unsupported-claim count.
"""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import qa, qa_eval
from app.db_models import Base
from tests.test_brain_qa_stories import _add_story

SUPPORT = {
    1: "strikes resume along the border cross-border strikes after the truce",
    2: "typhoon slams coastal provinces landfall evacuations",
}


def test_check_claims_maps_sentences_to_stories():
    answer = "Strikes resumed at the border [1]. Aliens landed in the capital [1]."
    out = qa.check_claims(answer, SUPPORT)
    first, second = out["claims"]
    assert first["supported"] is True
    assert first["matched_story"] == 1
    assert first["cited"] == [1]
    assert second["supported"] is False
    assert second["matched_story"] is None
    assert out["unsupported"] == 1


def test_check_claims_finds_support_beyond_wrong_citation():
    # Right claim, wrong citation: supported, but cited ≠ matched_story.
    answer = "The typhoon made landfall near coastal provinces [1]."
    out = qa.check_claims(answer, SUPPORT)
    claim = out["claims"][0]
    assert claim["supported"] is True
    assert claim["cited"] == [1]
    assert claim["matched_story"] == 2
    assert out["unsupported"] == 0


def test_check_claims_skips_canned_and_uncheckable():
    for canned in (qa.REFUSAL_ANSWER, qa.NO_EVIDENCE_ANSWER, qa.NO_LOCAL_EVIDENCE_ANSWER):
        assert qa.check_claims(canned, SUPPORT) == {"claims": [], "unsupported": 0}
    assert qa.check_claims(None, SUPPORT) == {"claims": [], "unsupported": 0}
    #: One content term is not checkable — no claim, no false alarm.
    out = qa.check_claims("Yes [1].", SUPPORT)
    assert out == {"claims": [], "unsupported": 0}


def test_check_claims_folds_plurals_on_word_boundaries():
    out = qa.check_claims("A strike resumed at the border.", SUPPORT)
    assert out["claims"][0]["supported"] is True
    #: substrings must not count: "order" is not "border".
    bad = qa.check_claims("New order and resume signal.", {1: "border resumed"})
    assert bad["claims"][0]["supported"] is False


def test_story_support_texts_includes_member_payloads():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    sid = _add_story(
        session,
        now,
        title="Strikes resume",
        source="reuters",
        source_event_id="e1",
        outlet_count=3,
        payload={"title": "Explosions rock Qeshm island overnight"},
        keywords=["explosion", "qeshm"],
        gist="Cross-border strikes.",
    )

    texts = qa.story_support_texts(
        session,
        [{"n": 1, "story_id": sid, "title": "Strikes resume", "gist": "Cross-border strikes."}],
    )

    assert "strikes resume" in texts[1]
    assert "cross-border strikes" in texts[1]
    assert "explosions rock qeshm island" in texts[1]
    assert "qeshm" in texts[1]


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_evaluate_answer_counts_unsupported_claims(monkeypatch):
    session = _session()
    monkeypatch.setattr(
        qa_eval.qa,
        "build_qa_context",
        lambda session, now=None, question=None, trace=None: {
            "as_of": "x",
            "stories": [
                {
                    "n": 1,
                    "story_id": 5,
                    "title": "Strikes resume along the border",
                    "gist": "Cross-border strikes after the truce.",
                    "sources": ["Reuters"],
                }
            ],
        },
    )
    monkeypatch.setattr(qa_eval.qa, "build_qa_prompt", lambda ctx, question: "prompt")

    out = qa_eval.evaluate_answer(
        session,
        spec="q",
        model="m",
        now=datetime(2026, 7, 17, tzinfo=UTC),
        generate_json=lambda prompt, *, model, keep_alive: {
            "answer": "Strikes resumed at the border [1]. Aliens landed in the capital [1]."
        },
        clock=iter([1.0, 1.1]).__next__,
    )

    assert out["ok"] is True
    assert out["unsupported_claims"] == 1
    assert [c["supported"] for c in out["claims"]] == [True, False]


def test_evaluate_answer_error_rows_have_no_claim_count(monkeypatch):
    session = _session()
    monkeypatch.setattr(
        qa_eval.qa,
        "build_qa_context",
        lambda session, now=None, question=None, trace=None: {"as_of": "x", "stories": []},
    )
    monkeypatch.setattr(qa_eval.qa, "build_qa_prompt", lambda ctx, question: "prompt")

    def boom(prompt, *, model, keep_alive):
        raise RuntimeError("ollama down")

    out = qa_eval.evaluate_answer(
        session,
        spec="q",
        model="m",
        now=datetime(2026, 7, 17, tzinfo=UTC),
        generate_json=boom,
        clock=iter([1.0, 1.1]).__next__,
    )

    assert out["unsupported_claims"] is None
    assert out["claims"] == []


def test_render_markdown_reports_unsupported_claims():
    report = {
        "created_at": "2026-07-17T00:00:00+00:00",
        "models": ["m1"],
        "questions": ["q"],
        "results": [
            {
                "question": "q",
                "model": "m1",
                "ok": True,
                "elapsed_ms": 12,
                "answer": "Strikes resumed [1]. Aliens landed [1].",
                "n_sources": 1,
                "cited": [1],
                "invalid_citations": [],
                "unsupported_claims": 1,
                "claims": [
                    {"text": "Strikes resumed [1].", "supported": True, "matched_story": 1},
                    {"text": "Aliens landed [1].", "supported": False, "matched_story": None},
                ],
                "rubric": {"passed": True, "reasons": []},
            }
        ],
    }

    md = qa_eval.render_markdown(report)

    assert "| Unsupported claims |" in md
    assert "- unsupported_claims: 1" in md
    assert "  - unsupported: Aliens landed [1]." in md
