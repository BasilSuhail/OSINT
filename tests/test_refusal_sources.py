"""An answer resting on nothing does not present sources (#1013).

Asked what was happening in Indonesia with no Indonesia story retrieved, a 4b
said so plainly — in its own prose, not the canned sentence. The split that moves
retrieved stories out of `sources` and into `closest_matches` was triggered only
by an exact string match, so it did not fire, and six unrelated outlets stayed
labelled as that answer's sources: an oil spill in Oman, wildfires in Greece, an
Ebola outbreak in Congo. For an answer stating in as many words that they held
nothing on the subject.

"Sources" is a claim about provenance. Nothing there had earned it.
"""

from __future__ import annotations

from app.api import _ask_payload
from app.brain import qa

#: What a question with no match actually retrieves: the loudest stories going,
#: in loudness order, with no match signal. `has_relevant_evidence` calls this
#: "fill" and refuses to count it, which is the judgement this now uses.
PADDING = [
    {"n": 1, "story_id": 1, "title": "Oil spill off Oman", "retrieval": "fill"},
    {"n": 2, "story_id": 2, "title": "Wildfires in Greece", "retrieval": "fill"},
]

MATCHED = [
    {"n": 1, "story_id": 1, "title": "Java earthquake", "retrieval": "semantic", "relevance": 0.9},
]

#: Close to the observed answer, and the point of it: the model's own words, not
#: the canned string, and it names the padding while saying it is off-topic.
PROSE_REFUSAL = (
    "Local reporting shows no active stories covering Indonesia in the current "
    "window. The available clusters concern an oil spill in Oman and wildfires "
    "in Greece."
)


class TestAnAnswerRestingOnNothing:
    def test_padding_is_not_presented_as_sources(self) -> None:
        body = _ask_payload(PROSE_REFUSAL, "digest", PADDING, relevant=False)
        assert body["sources"] == []

    #: Moved rather than dropped. The reader is still owed what the search did
    #: find — labelled as the nearest thing to an answer, not as evidence for one.
    def test_it_is_offered_as_the_closest_matches(self) -> None:
        body = _ask_payload(PROSE_REFUSAL, "digest", PADDING, relevant=False)
        assert [s["story_id"] for s in body["closest_matches"]] == [1, 2]

    #: The old trigger. Still works, and is now not the only one.
    def test_the_canned_sentence_still_triggers_it(self) -> None:
        body = _ask_payload(qa.NO_LOCAL_EVIDENCE_ANSWER, "digest", PADDING)
        assert body["sources"] == []
        assert len(body["closest_matches"]) == 2

    #: The fault itself: an answer nobody wrote in the canned words.
    def test_prose_that_matches_no_string_is_still_a_no_answer(self) -> None:
        assert PROSE_REFUSAL.strip() != qa.NO_LOCAL_EVIDENCE_ANSWER
        body = _ask_payload(PROSE_REFUSAL, "digest", PADDING, relevant=False)
        assert body["sources"] == []


class TestARealAnswerKeepsItsSources:
    """The risk in fixing the above, and the reason two earlier attempts were
    backed out: an answer that IS grounded must not lose its provenance."""

    def test_a_matched_story_stays_a_source(self) -> None:
        body = _ask_payload("A quake struck Java [1].", "digest", MATCHED, relevant=True)
        assert [s["story_id"] for s in body["sources"]] == [1]
        assert body["closest_matches"] == []

    #: Relevance defaults to true, so every existing caller — the typed failure
    #: answers among them — behaves exactly as before.
    def test_the_default_keeps_sources(self) -> None:
        body = _ask_payload("A quake struck Java [1].", "digest", MATCHED)
        assert [s["story_id"] for s in body["sources"]] == [1]


class TestTheSignalIsTheOneAlreadyInUse:
    #: Not a second opinion about relevance. The refusal-retry path decides with
    #: this same function, and two disagreeing judgements would be a bug waiting.
    def test_padding_does_not_count_as_evidence(self) -> None:
        assert not qa.has_relevant_evidence(PADDING)

    def test_a_matched_story_does(self) -> None:
        assert qa.has_relevant_evidence(MATCHED)

    #: A sensor reading is only ever retrieved when the question names its
    #: hazard, so it counts on its own — and must keep counting, or "were there
    #: big earthquakes?" loses the readings that answer it.
    def test_a_sensor_reading_counts_on_its_own(self) -> None:
        assert qa.has_relevant_evidence([], [{"n": 1, "kind": "quake"}])
