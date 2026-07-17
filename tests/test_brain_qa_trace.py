"""Question-understood retrieval trace (#413 roadmap item 10, #461).

The trace must explain why retrieval chose each source: parsed intents,
terms, gate rejections, method, and scored-but-rejected candidates. It is
debug/eval-only — behavior is identical when no trace is requested.
"""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import qa, qa_eval
from app.db_models import Base
from tests.test_brain_qa_semantic import _add_vector
from tests.test_brain_qa_stories import _add_story


def _fresh_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_semantic_trace_explains_selection_and_rejections(monkeypatch):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    strikes_id = _add_story(
        session,
        now,
        title="Strikes resume along the border",
        source="reuters",
        source_event_id="strikes",
        outlet_count=3,
        category="conflict",
        gist="Cross-border strikes after the truce.",
    )
    other_id = _add_story(
        session,
        now,
        title="Talks stall in the capital",
        source="aj",
        source_event_id="talks",
        outlet_count=2,
        category="conflict",
        gist="Negotiations stall.",
    )
    typhoon_id = _add_story(
        session,
        now,
        title="Typhoon slams coastal provinces",
        source="bbc",
        source_event_id="typhoon",
        outlet_count=20,
        category="disaster",
        gist="Typhoon makes landfall.",
    )
    _add_vector(session, strikes_id, [1.0, 0.0])
    _add_vector(session, other_id, [0.0, 1.0])
    monkeypatch.setattr(qa.client, "embed", lambda texts, **kw: [[1.0, 0.0]])

    trace: dict = {}
    out = qa.build_qa_stories(
        session, now=now, question="is the war back on?", limit=1, trace=trace
    )

    assert [s["story_id"] for s in out] == [strikes_id]
    assert trace["question"] == "is the war back on?"
    assert trace["intents"] == ["conflict"]
    assert "war" in trace["terms"]
    assert trace["method"] == "semantic"
    assert trace["candidates"] == 3
    assert trace["intent_rejected"] == [
        {"story_id": typhoon_id, "title": "Typhoon slams coastal provinces", "category": "disaster"}
    ]
    assert trace["selected"] == [
        {
            "n": 1,
            "story_id": strikes_id,
            "title": "Strikes resume along the border",
            "retrieval": "semantic",
            "relevance": 1.0,
        }
    ]
    assert trace["rejected"] == [
        {"story_id": other_id, "title": "Talks stall in the capital", "relevance": 0.0}
    ]


def test_keyword_trace_flags_embed_failure(monkeypatch):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    war_id = _add_story(
        session,
        now,
        title="War resumes at the border",
        source="reuters",
        source_event_id="war",
        outlet_count=3,
        category="conflict",
        gist="Border war reignites.",
    )
    talks_id = _add_story(
        session,
        now,
        title="War talks continue",
        source="aj",
        source_event_id="talks",
        outlet_count=2,
        category="conflict",
        gist="Talks about the war continue.",
    )
    _add_vector(session, war_id, [1.0, 0.0])

    def boom(texts, **kw):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(qa.client, "embed", boom)

    trace: dict = {}
    out = qa.build_qa_stories(
        session, now=now, question="is the war back on?", limit=1, trace=trace
    )

    assert len(out) == 1
    assert trace["embed_failed"] is True
    assert trace["method"] == "keyword"
    assert len(trace["rejected"]) == 1
    assert trace["rejected"][0]["story_id"] in {war_id, talks_id}
    assert trace["selected"][0]["retrieval"] == "keyword"


def test_gate_emptying_pool_traces_none_method():
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    _add_story(
        session,
        now,
        title="Typhoon slams coastal provinces",
        source="bbc",
        source_event_id="typhoon",
        outlet_count=20,
        category="disaster",
        gist="Typhoon makes landfall.",
    )

    trace: dict = {}
    out = qa.build_qa_stories(session, now=now, question="is the war back on?", trace=trace)

    assert out == []
    assert trace["method"] == "none"
    assert trace["selected"] == []
    assert len(trace["intent_rejected"]) == 1


def test_no_question_traces_loudness():
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    _add_story(
        session,
        now,
        title="Border clashes reported",
        source="reuters",
        source_event_id="e",
        outlet_count=8,
    )

    trace: dict = {}
    out = qa.build_qa_stories(session, now=now, trace=trace)

    assert len(out) == 1
    assert trace["question"] is None
    assert trace["method"] == "loudness"
    assert trace["selected"][0]["retrieval"] == "fill"


def test_trace_untouched_paths_behave_identically(monkeypatch):
    # Same DB, with and without a trace: identical story selection.
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    _add_story(
        session,
        now,
        title="Strikes resume along the border",
        source="reuters",
        source_event_id="s",
        outlet_count=3,
        category="conflict",
        gist="Cross-border strikes.",
    )
    plain = qa.build_qa_stories(session, now=now, question="is the war back on?")
    traced = qa.build_qa_stories(session, now=now, question="is the war back on?", trace={})
    assert plain == traced


def test_evaluate_answer_carries_trace(monkeypatch):
    session = _fresh_session()

    def fake_context(session, now=None, question=None, trace=None):
        if trace is not None:
            trace.update({"method": "semantic", "selected": [], "intents": ["conflict"]})
        return {"as_of": "x", "stories": []}

    monkeypatch.setattr(qa_eval.qa, "build_qa_context", fake_context)
    monkeypatch.setattr(qa_eval.qa, "build_qa_prompt", lambda ctx, question: "prompt")

    ok = qa_eval.evaluate_answer(
        session,
        spec="q",
        model="m",
        now=datetime(2026, 7, 17, tzinfo=UTC),
        generate_json=lambda prompt, *, model, keep_alive: {"answer": "Fine."},
        clock=iter([1.0, 1.1]).__next__,
    )
    assert ok["trace"]["method"] == "semantic"

    def boom(prompt, *, model, keep_alive):
        raise RuntimeError("ollama down")

    failed = qa_eval.evaluate_answer(
        session,
        spec="q",
        model="m",
        now=datetime(2026, 7, 17, tzinfo=UTC),
        generate_json=boom,
        clock=iter([1.0, 1.1]).__next__,
    )
    assert failed["trace"]["intents"] == ["conflict"]


def test_render_markdown_explains_source_selection():
    report = {
        "created_at": "2026-07-17T00:00:00+00:00",
        "models": ["m1"],
        "questions": ["is the war back on?"],
        "results": [
            {
                "question": "is the war back on?",
                "model": "m1",
                "ok": True,
                "elapsed_ms": 12,
                "answer": "Strikes resumed [1]",
                "n_sources": 1,
                "cited": [1],
                "invalid_citations": [],
                "rubric": {"passed": True, "reasons": []},
                "trace": {
                    "question": "is the war back on?",
                    "intents": ["conflict"],
                    "terms": ["war", "back"],
                    "candidates": 3,
                    "method": "semantic",
                    "selected": [
                        {
                            "n": 1,
                            "story_id": 5,
                            "title": "Strikes resume",
                            "retrieval": "semantic",
                            "relevance": 0.71,
                        }
                    ],
                    "rejected": [{"story_id": 6, "title": "Talks stall", "relevance": 0.42}],
                    "intent_rejected": [
                        {"story_id": 7, "title": "Typhoon slams coast", "category": "disaster"}
                    ],
                },
            }
        ],
    }

    md = qa_eval.render_markdown(report)

    assert "understood: intents=['conflict'] terms=['war', 'back']" in md
    assert "retrieval: semantic — 3 candidates, 1 intent-rejected" in md
    assert "[1] Strikes resume — semantic 0.71" in md
    assert "rejected: Talks stall — 0.42" in md
    assert "intent-rejected: Typhoon slams coast (disaster)" in md
