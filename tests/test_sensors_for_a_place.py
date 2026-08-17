"""A question naming a place gets the hazards at that place (#1014).

The console drew forty earthquake readings inside Indonesia, with ShakeMap
contours over the islands, while the Ask panel beside it answered "I don't have
enough local evidence" to "what is happening in Indonesia?".

Both were behaving as written. Sensor retrieval required the question to name a
hazard — "earthquake", "flood", "cyclone" — and a question naming only a country
names none, so it returned nothing before it ever looked at the place. A console
that contradicts itself on screen is worse than either half alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.brain import qa, sensors
from app.brain.sensors import question_kinds
from app.db_models import EventRow


class TestWhyItReturnedNothing:
    #: The gate. Not a bug in itself — it is what stops an unrelated reading
    #: padding the context — but it decided a place question had no sensor
    #: intent, which is the opposite of true.
    def test_a_place_question_names_no_hazard_kind(self) -> None:
        assert question_kinds("what is happening in Indonesia?") == frozenset()

    def test_a_hazard_question_always_did_work(self) -> None:
        assert "earthquake" in question_kinds("were there big earthquakes?")

    #: Generic hazard words already had their own path. A country name did not.
    def test_a_generic_hazard_word_is_already_handled(self) -> None:
        assert question_kinds("any disasters?") != frozenset()


def _quake(session, *, magnitude: float, place: str, country: str | None, eid: str) -> None:
    session.add(
        EventRow(
            source="usgs-quake",
            source_event_id=eid,
            occurred_at=datetime.now(UTC) - timedelta(hours=1),
            category="hazard",
            severity=min(1.0, magnitude / 10),
            country=country,
            keywords=[],
            payload={"magnitude": magnitude, "place": place, "depth_km": 10},
        )
    )


class TestAPlaceQuestionNowReachesTheReadings:
    def test_a_reading_in_the_named_country_is_returned(self, db_session) -> None:
        _quake(db_session, magnitude=5.4, place="Java, Indonesia", country="ID", eid="a")
        db_session.flush()
        found = sensors.build_qa_sensors(db_session, question="what is happening in Indonesia?")
        assert [r["kind"] for r in found] == ["earthquake"]
        assert found[0]["match"] == "place"

    #: The reason the kind gate was strict, and it still holds: asking about one
    #: country must not hand the model the biggest readings elsewhere on earth,
    #: which is how a New Zealand quake got cited as confirming a Peru event.
    def test_a_bigger_reading_elsewhere_is_not_returned(self, db_session) -> None:
        _quake(db_session, magnitude=5.0, place="Java, Indonesia", country="ID", eid="a")
        _quake(db_session, magnitude=7.9, place="Kermadec Islands", country="NZ", eid="b")
        db_session.flush()
        found = sensors.build_qa_sensors(db_session, question="what is happening in Indonesia?")
        assert len(found) == 1
        assert "Java" in found[0]["headline"]

    #: USGS files some readings with a place string and no country column.
    def test_the_place_text_counts_when_the_column_is_empty(self, db_session) -> None:
        _quake(
            db_session, magnitude=5.1, place="120 km NE of Padang, Indonesia", country=None, eid="a"
        )
        db_session.flush()
        found = sensors.build_qa_sensors(db_session, question="what is happening in Indonesia?")
        assert len(found) == 1

    #: A question naming neither a hazard nor a place still gets nothing, which
    #: is the behaviour that stops unrelated readings padding the context.
    def test_a_question_with_no_place_and_no_hazard_still_gets_nothing(self, db_session) -> None:
        _quake(db_session, magnitude=6.0, place="Java, Indonesia", country="ID", eid="a")
        db_session.flush()
        assert sensors.build_qa_sensors(db_session, question="what did the markets do?") == []

    #: And the consequence that matters: with a reading in hand, the ask no
    #: longer reports having no local evidence.
    def test_the_ask_now_has_evidence_to_answer_from(self, db_session) -> None:
        _quake(db_session, magnitude=5.4, place="Java, Indonesia", country="ID", eid="a")
        db_session.flush()
        found = sensors.build_qa_sensors(db_session, question="what is happening in Indonesia?")
        assert qa.has_relevant_evidence([], found)
