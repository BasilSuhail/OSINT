"""«what else?» must return something else (#813).

Asked about Edinburgh and then asked "what else?", the console returned the
same suitcase-murder story reworded, with the source chips shuffled. Two
mechanisms compounded: `build_retrieval_text` folds the previous *answer*
into the text retrieval matches on — right for "what do u think that was?"
(#444), fatal for a question whose whole content is "not that" — and nothing
recorded which stories had already been cited.

The existing guard misses it by design: `answer_echoes` (#451) compares
answer prose and forces a regeneration, so the second answer is genuinely
new sentences about identical evidence. The guard polices the wording; the
repetition is in the retrieval.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

import app.api as api
from app.api import app, get_session
from app.brain import qa


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


class TestIntent:
    def test_the_plain_forms_are_continuations(self) -> None:
        for question in (
            "what else?",
            "What else",
            "anything else?",
            "what other stories are there",
            "more",
            "go on",
            "anything more on that?",
        ):
            assert qa.is_continuation_request(question), question

    def test_a_new_question_is_not_a_continuation(self) -> None:
        for question in (
            "tell me about edinburgh's latest murders",
            "what happened in Lahore today",
            "why is that story contested?",
            "who else was charged",  # a question about the story, not for another one
        ):
            assert not qa.is_continuation_request(question), question

    def test_an_elaborate_request_is_not_a_continuation(self) -> None:
        """ "Elaborate" asks for more about *this*; "what else" asks for a
        different one. Confusing them would break #600."""
        assert qa.is_elaborate_request("elaborate")
        assert not qa.is_continuation_request("elaborate")
        assert not qa.is_continuation_request("explain that in simple terms")

    def test_tell_me_more_stays_with_elaboration(self) -> None:
        """Genuinely ambiguous, and #600 got there first. "Tell me more"
        reads as more about *that* at least as naturally as another story,
        so it keeps the longer answer rather than a different subject."""
        assert qa.is_elaborate_request("tell me more")
        assert not qa.is_continuation_request("tell me more")

    def test_padding_does_not_make_the_match_expensive(self) -> None:
        """The intent pattern reads a question typed by whoever is asking, so
        every quantifier in it has to be unambiguous. Two `\\s*` either side of
        an optionally-empty class let a run of spaces be split n ways, and a
        suffix that cannot match then costs O(n squared) to rule out.

        Measured on the pattern this replaced: 70ms at 5000 spaces, 1.07s at
        20000, 9.5s at 60000 — quadratic. The unambiguous pattern reads 20000
        in 0.7ms. The bound below sits two orders of magnitude above the linear
        cost and below the quadratic one, so it fails loudly if an ambiguous
        pair comes back without being flaky on a slow machine.
        """
        padded = "more" + " " * 20_000 + "x"
        started = time.perf_counter()
        assert not qa.is_continuation_request(padded)
        assert time.perf_counter() - started < 0.25


class TestRetrievalAnchor:
    HISTORY: ClassVar[list[dict[str, Any]]] = [
        {
            "question": "tell me about edinburgh murders",
            "answer": "A man accused of killing an Edinburgh aid worker hid a body in a suitcase.",
            "story_ids": [11, 12],
        }
    ]

    def test_a_vague_follow_up_still_inherits_its_topic(self) -> None:
        """#444 must not regress: this question has no topic of its own."""
        text = qa.build_retrieval_text("what do u think that was?", self.HISTORY)
        assert "edinburgh" in text.lower()
        assert "suitcase" in text.lower()

    def test_a_continuation_keeps_the_topic_and_drops_the_told_story(self) -> None:
        text = qa.build_retrieval_text("what else?", self.HISTORY, continuation=True)
        assert "edinburgh" in text.lower(), "the topic was lost"
        assert "suitcase" not in text.lower(), "the answer still steers retrieval"


class TestToldStories:
    def test_ids_are_collected_from_every_turn(self) -> None:
        history = [
            {"question": "q1", "answer": "a1", "story_ids": [1, 2]},
            {"question": "q2", "answer": "a2", "story_ids": [2, 3]},
        ]
        assert qa.told_story_ids(history) == frozenset({1, 2, 3})

    def test_a_transcript_without_ids_excludes_nothing(self) -> None:
        """An older client sends question and answer only. It must degrade to
        today's behaviour rather than to an exception."""
        assert qa.told_story_ids([{"question": "q", "answer": "a"}]) == frozenset()
        assert qa.told_story_ids(None) == frozenset()

    def test_rubbish_ids_are_ignored(self) -> None:
        history = [{"question": "q", "answer": "a", "story_ids": ["7", None, 8]}]
        assert qa.told_story_ids(history) == frozenset({7, 8})


class TestThroughTheEndpoint:
    """The rules above are worth nothing if `/brain/ask` does not use them."""

    def _client(self, monkeypatch, db_session, *, stories: list[dict]) -> tuple[TestClient, dict]:
        captured: dict = {}

        def _context(
            session, question=None, history=None, exclude_story_ids=frozenset(), trace=None
        ):
            captured["excluded"] = exclude_story_ids
            remaining = [s for s in stories if s["story_id"] not in exclude_story_ids]
            return {"stories": remaining}

        monkeypatch.setattr(api.gate, "ram_free_mb", lambda: 8000)
        monkeypatch.setattr(api.qa, "build_qa_context", _context)
        monkeypatch.setattr(
            api.client, "generate_json", lambda prompt, **kw: {"answer": "Something else [1]."}
        )
        app.dependency_overrides[get_session] = lambda: db_session
        return TestClient(app), captured

    STORIES: ClassVar[list[dict[str, Any]]] = [
        {
            "n": 1,
            "story_id": 11,
            "title": "Suitcase murder suspect appears in court",
            "retrieval": "semantic",
            "relevance": 0.9,
            "sources": ["Edinburgh Live"],
            "corroboration": None,
            "contested": False,
        },
        {
            "n": 2,
            "story_id": 12,
            "title": "Fire at South Queensferry",
            "retrieval": "semantic",
            "relevance": 0.9,
            "sources": ["STV News"],
            "corroboration": None,
            "contested": False,
        },
    ]

    def test_a_continuation_excludes_what_was_already_cited(self, monkeypatch, db_session):
        client, captured = self._client(monkeypatch, db_session, stories=self.STORIES)
        body = client.post(
            "/brain/ask",
            json={
                "question": "what else?",
                "history": [{"question": "edinburgh murders", "answer": "…", "story_ids": [11]}],
            },
        ).json()
        assert captured["excluded"] == frozenset({11})
        assert [s["story_id"] for s in body["sources"]] == [12]

    def test_a_normal_question_excludes_nothing(self, monkeypatch, db_session):
        client, captured = self._client(monkeypatch, db_session, stories=self.STORIES)
        client.post(
            "/brain/ask",
            json={
                "question": "tell me about the fire",
                "history": [{"question": "edinburgh murders", "answer": "…", "story_ids": [11]}],
            },
        )
        assert captured["excluded"] == frozenset()

    def test_running_out_says_so_instead_of_repeating(self, monkeypatch, db_session):
        """The failure this fixes: the reader asked for more and was handed a
        rewrite of what they had just read."""
        client, _ = self._client(monkeypatch, db_session, stories=self.STORIES)
        body = client.post(
            "/brain/ask",
            json={
                "question": "what else?",
                "history": [
                    {"question": "edinburgh murders", "answer": "…", "story_ids": [11, 12]}
                ],
            },
        ).json()
        assert body["answer"] == qa.NOTHING_MORE_ANSWER
        assert body["sources"] == []

    def test_an_older_client_without_story_ids_still_works(self, monkeypatch, db_session):
        client, captured = self._client(monkeypatch, db_session, stories=self.STORIES)
        body = client.post(
            "/brain/ask",
            json={"question": "what else?", "history": [{"question": "q", "answer": "a"}]},
        ).json()
        assert captured["excluded"] == frozenset()
        assert body["answer"] == "Something else [1]."
