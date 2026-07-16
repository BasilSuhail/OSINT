from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.brain import embeddings, qa
from app.db_models import Base, StoryEmbeddingRow
from tests.test_brain_qa_stories import _add_story


def _fresh_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def _add_vector(session, story_id, vector):
    session.add(
        StoryEmbeddingRow(
            story_id=story_id,
            model="nomic-embed-text",
            method_version=embeddings.EMBED_METHOD_VERSION,
            vector=vector,
        )
    )
    session.commit()


def test_semantic_ranking_beats_loudness(monkeypatch):
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    loud_id = _add_story(
        session,
        now,
        title="World Cup semi-final",
        source="bbc",
        source_event_id="loud",
        outlet_count=20,
    )
    quiet_id = _add_story(
        session,
        now,
        title="Explosion heard on Qeshm island",
        source="aj",
        source_event_id="quiet",
        outlet_count=2,
    )
    _add_vector(session, loud_id, [1.0, 0.0])
    _add_vector(session, quiet_id, [0.0, 1.0])
    monkeypatch.setattr(qa.client, "embed", lambda texts, **kw: [[0.0, 1.0]])

    out = qa.build_qa_stories(session, now=now, question="whatt explosions?")

    assert [s["story_id"] for s in out] == [quiet_id, loud_id]


def test_semantic_falls_back_to_keywords_when_embed_fails(monkeypatch):
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    _add_story(
        session,
        now,
        title="Flooding in coastal towns",
        source="bbc",
        source_event_id="flood",
        outlet_count=20,
    )
    iran_id = _add_story(
        session,
        now,
        title="Iran border clashes intensify",
        source="reuters",
        source_event_id="iran",
        outlet_count=3,
    )
    _add_vector(session, iran_id, [1.0, 0.0])

    def boom(texts, **kw):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(qa.client, "embed", boom)

    out = qa.build_qa_stories(session, now=now, question="what is happening with iran?")

    assert [s["story_id"] for s in out] == [iran_id]


def test_semantic_skipped_entirely_without_vectors(monkeypatch):
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    iran_id = _add_story(
        session,
        now,
        title="Iran border clashes intensify",
        source="reuters",
        source_event_id="iran",
        outlet_count=3,
    )

    def must_not_call(texts, **kw):
        raise AssertionError("embed called although no story has a vector")

    monkeypatch.setattr(qa.client, "embed", must_not_call)

    out = qa.build_qa_stories(session, now=now, question="iran clashes")

    assert [s["story_id"] for s in out] == [iran_id]


def test_stories_without_vectors_fill_after_semantic_picks(monkeypatch):
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    with_vec = _add_story(
        session, now, title="Explosion on Qeshm", source="aj", source_event_id="v1", outlet_count=2
    )
    no_vec = _add_story(
        session,
        now,
        title="Loud unrelated story",
        source="bbc",
        source_event_id="v2",
        outlet_count=20,
    )
    _add_vector(session, with_vec, [1.0, 0.0])
    monkeypatch.setattr(qa.client, "embed", lambda texts, **kw: [[1.0, 0.0]])

    out = qa.build_qa_stories(session, now=now, question="explosion?")

    assert [s["story_id"] for s in out] == [with_vec, no_vec]


def test_question_terms_drop_live_junk():
    terms = qa._question_terms(
        "whatt explosions? what do u think that was? are there any sources or any theories?"
    )
    assert terms == ["whatt", "explosions"]


def test_rank_requires_word_boundaries():
    # "art" must not score against "quarterfinal" by substring.
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    _add_story(
        session,
        now,
        title="World Cup quarterfinal predictions",
        source="bbc",
        source_event_id="q",
        outlet_count=9,
    )
    out = qa.build_qa_stories(session, now=now, question="art exhibition opening")
    assert out == []


def test_rank_folds_plurals_both_ways():
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    singular_title = _add_story(
        session,
        now,
        title="Explosion heard on Qeshm island",
        source="aj",
        source_event_id="s",
        outlet_count=2,
    )
    out = qa.build_qa_stories(session, now=now, question="explosions in iran")
    assert [s["story_id"] for s in out] == [singular_title]

    plural_title = _add_story(
        session,
        now,
        title="Explosions rock the capital",
        source="bbc",
        source_event_id="p",
        outlet_count=2,
    )
    out2 = qa.build_qa_stories(session, now=now, question="explosion capital")
    assert plural_title in [s["story_id"] for s in out2]
