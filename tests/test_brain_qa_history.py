from datetime import UTC, datetime

from app.brain import qa
from tests.test_brain_qa_semantic import _add_vector, _fresh_session
from tests.test_brain_qa_stories import _add_story

_HISTORY = [
    {
        "question": "what is happening with iran?",
        "answer": "The US has launched strikes against Iran after ship attacks in Hormuz. [1]",
    }
]


def test_retrieval_text_folds_in_last_exchange():
    text = qa.build_retrieval_text("what do u think that was?", _HISTORY)
    assert "what do u think that was?" in text
    assert "iran" in text.lower()
    assert "hormuz" in text.lower()


def test_retrieval_text_without_history_is_question():
    assert qa.build_retrieval_text("iran?", None) == "iran?"
    assert qa.build_retrieval_text("iran?", []) == "iran?"


def test_retrieval_text_truncates_long_answers():
    history = [{"question": "q", "answer": "x" * 5000}]
    text = qa.build_retrieval_text("follow-up", history)
    assert len(text) < 1000


def test_semantic_retrieval_embeds_question_and_anchored_text(monkeypatch):
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    sid = _add_story(
        session, now, title="Iran strikes", source="aj", source_event_id="i", outlet_count=3
    )
    _add_vector(session, sid, [1.0, 0.0])
    embedded: list[str] = []

    def fake_embed(texts, **kw):
        embedded.extend(texts)
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(qa.client, "embed", fake_embed)
    out = qa.build_qa_stories(
        session, now=now, question="what do u think that was?", history=_HISTORY
    )
    assert [s["story_id"] for s in out] == [sid]
    #: one batched call carries BOTH the bare question and the anchored text —
    #: history must widen retrieval, never drown the question itself (#451).
    assert len(embedded) == 2
    assert embedded[0] == "what do u think that was?"
    assert "iran" in embedded[1].lower()


def test_semantic_retrieval_scores_by_best_query_match(monkeypatch):
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    question_hit = _add_story(
        session,
        now,
        title="US completes third strike on Iran",
        source="aj",
        source_event_id="qh",
        outlet_count=2,
    )
    anchor_hit = _add_story(
        session,
        now,
        title="Tehran warns of existential war",
        source="bbc",
        source_event_id="ah",
        outlet_count=2,
    )
    off_topic = _add_story(
        session,
        now,
        title="World Cup final preview",
        source="fr24",
        source_event_id="ot",
        outlet_count=20,
    )
    _add_vector(session, question_hit, [1.0, 0.0])
    _add_vector(session, anchor_hit, [0.0, 1.0])
    _add_vector(session, off_topic, [-1.0, 0.0])

    #: question vector ≈ story A, anchored vector ≈ story B.
    monkeypatch.setattr(qa.client, "embed", lambda texts, **kw: [[1.0, 0.0], [0.0, 1.0]])
    out = qa.build_qa_stories(
        session, now=now, question="how many attacks till now?", history=_HISTORY, limit=2
    )
    assert {s["story_id"] for s in out} == {question_hit, anchor_hit}


def test_keyword_fallback_uses_anchored_terms(monkeypatch):
    now = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
    session = _fresh_session()
    _add_story(
        session, now, title="Flooding in towns", source="bbc", source_event_id="f", outlet_count=20
    )
    iran_id = _add_story(
        session,
        now,
        title="Iran strikes intensify",
        source="aj",
        source_event_id="i",
        outlet_count=2,
    )
    # no vectors at all → keyword path; history must supply the "iran" term
    out = qa.build_qa_stories(
        session, now=now, question="what do u think that was?", history=_HISTORY
    )
    assert iran_id in [s["story_id"] for s in out]


def test_prompt_carries_conversation_section():
    ctx = {"stories": []}
    prompt = qa.build_qa_prompt(ctx, "what do u think that was?", history=_HISTORY)
    assert "RECENT CONVERSATION (" in prompt
    assert "what is happening with iran?" in prompt
    assert prompt.index("RECENT CONVERSATION (") < prompt.index("QUESTION:")


def test_prompt_without_history_has_no_conversation_section():
    prompt = qa.build_qa_prompt({"stories": []}, "iran?")
    assert "RECENT CONVERSATION (" not in prompt


def test_text_prompt_keeps_conversation_section():
    prompt = qa.build_qa_text_prompt({"stories": []}, "that was?", history=_HISTORY)
    assert "RECENT CONVERSATION (" in prompt
    assert "Return only the final plain-English answer text" in prompt
