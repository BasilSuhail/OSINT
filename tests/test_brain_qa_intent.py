"""Intent gate on question-driven retrieval (#413 roadmap item 2, #457).

The live failure this guards against: "is the war back on?" answered by a
loud typhoon story. A question that names a category must never retrieve a
story whose gist category contradicts it.
"""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import qa
from app.db_models import Base
from tests.test_brain_qa_semantic import _add_vector
from tests.test_brain_qa_stories import _add_story


def _fresh_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_question_intents_detects_conflict():
    assert qa.question_intents("is the war back on?") == frozenset({"conflict"})
    assert qa.question_intents("did the ceasefire collapse?") == frozenset({"conflict"})


def test_question_intents_folds_plurals():
    assert qa.question_intents("any missile strikes or clashes?") == frozenset({"conflict"})
    assert qa.question_intents("recent earthquakes?") == frozenset({"disaster"})


def test_question_intents_empty_for_neutral_questions():
    assert qa.question_intents("what happened in Iran?") == frozenset()
    assert qa.question_intents(None) == frozenset()


def test_question_intents_mixed_question_keeps_both():
    assert qa.question_intents("did the war cause flooding?") == frozenset({"conflict", "disaster"})


def test_question_intents_ambiguous_terms_widen():
    assert qa.question_intents("was there a coup?") == frozenset({"conflict", "politics"})
    assert qa.question_intents("new sanctions?") == frozenset({"conflict", "economy"})


def test_war_question_excludes_loud_disaster_semantic(monkeypatch):
    # The #413 live failure: the typhoon is louder AND the better cosine
    # match, yet must not answer a war question.
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    typhoon_id = _add_story(
        session,
        now,
        title="Typhoon slams coastal provinces",
        source="bbc",
        source_event_id="typhoon",
        outlet_count=20,
        category="disaster",
        gist="Typhoon makes landfall; mass evacuations.",
    )
    war_id = _add_story(
        session,
        now,
        title="Strikes resume along the border",
        source="reuters",
        source_event_id="war",
        outlet_count=3,
        category="conflict",
        gist="Cross-border strikes after the truce.",
    )
    _add_vector(session, typhoon_id, [1.0, 0.0])
    _add_vector(session, war_id, [0.0, 1.0])
    monkeypatch.setattr(qa.client, "embed", lambda texts, **kw: [[1.0, 0.0]])

    out = qa.build_qa_stories(session, now=now, question="is the war back on?")

    assert [s["story_id"] for s in out] == [war_id]


def test_war_question_excludes_disaster_in_keyword_fallback(monkeypatch):
    # Keyword ranker would score "war" in the disaster title; the gate must
    # drop it before ranking.
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    _add_story(
        session,
        now,
        title="Weather war: typhoon slams the coast",
        source="bbc",
        source_event_id="typhoon",
        outlet_count=20,
        category="disaster",
        gist="Typhoon makes landfall.",
    )
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

    def boom(texts, **kw):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(qa.client, "embed", boom)

    out = qa.build_qa_stories(session, now=now, question="is the war back on?")

    assert [s["story_id"] for s in out] == [war_id]


def test_war_question_with_only_disaster_coverage_returns_nothing():
    # Done condition (#413 item 2): refuse when local evidence is off-topic —
    # an empty stories list routes the answer path to an honest refusal.
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

    out = qa.build_qa_stories(session, now=now, question="is the war back on?")

    assert out == []


def test_gate_spares_ungisted_stories():
    # A story that enrichment has not reached yet must stay retrievable — only a
    # contradicting category is disqualifying.
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    war_id = _add_story(
        session,
        now,
        title="War resumes at the border",
        source="reuters",
        source_event_id="war",
        outlet_count=3,
    )

    out = qa.build_qa_stories(session, now=now, question="is the war back on?")

    assert [s["story_id"] for s in out] == [war_id]


def test_mixed_question_keeps_both_categories(monkeypatch):
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    typhoon_id = _add_story(
        session,
        now,
        title="Flooding after the typhoon",
        source="bbc",
        source_event_id="typhoon",
        outlet_count=5,
        category="disaster",
        gist="Severe flooding after landfall.",
    )
    war_id = _add_story(
        session,
        now,
        title="War damages flood defences",
        source="reuters",
        source_event_id="war",
        outlet_count=3,
        category="conflict",
        gist="Shelling hit the levees; flooding followed.",
    )

    def boom(texts, **kw):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(qa.client, "embed", boom)

    out = qa.build_qa_stories(session, now=now, question="did the war cause flooding?")

    ids = {s["story_id"] for s in out}
    assert ids == {typhoon_id, war_id}


def test_neutral_question_stays_ungated(monkeypatch):
    # No intent terms → the gate must not run; loud stories still rank.
    now = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    typhoon_id = _add_story(
        session,
        now,
        title="Typhoon slams Iran coast",
        source="bbc",
        source_event_id="typhoon",
        outlet_count=20,
        category="disaster",
        gist="Typhoon makes landfall in Iran.",
    )

    def boom(texts, **kw):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(qa.client, "embed", boom)

    out = qa.build_qa_stories(session, now=now, question="what happened in Iran?")

    assert [s["story_id"] for s in out] == [typhoon_id]
