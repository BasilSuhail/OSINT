"""Structured sensor retrieval for Q&A (#507).

The brain could only ever see news stories: story clustering takes
`category == "news"` and Q&A retrieves from StoryRow. Earthquakes, floods,
wildfires, GDELT and cyber events were invisible to it. These cover the
selector lexicon, ordering, capping and the counts summary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.brain import sensors
from app.db_models import EventRow


def _quake(session, *, magnitude: float, place: str, ago_h: float = 1.0, eid: str = "") -> None:
    now = datetime.now(UTC)
    session.add(
        EventRow(
            source="usgs-quake",
            source_event_id=eid or f"q-{magnitude}-{place}-{ago_h}",
            occurred_at=now - timedelta(hours=ago_h),
            category="hazard",
            severity=min(1.0, magnitude / 10),
            country="NP",
            keywords=[],
            payload={"magnitude": magnitude, "place": place, "depth_km": 10},
        )
    )


def _gdacs(session, *, event_type: str, name: str, ago_h: float = 1.0) -> None:
    now = datetime.now(UTC)
    session.add(
        EventRow(
            source="gdacs",
            source_event_id=f"g-{event_type}-{name}",
            occurred_at=now - timedelta(hours=ago_h),
            category="hazard",
            severity=0.5,
            country="PH",
            keywords=[],
            payload={"event_type": event_type, "eventname": name, "iso3": "PHL"},
        )
    )


def test_no_sensor_intent_returns_nothing(db_session):
    _quake(db_session, magnitude=6.1, place="Nepal")
    db_session.commit()
    out = sensors.build_qa_sensors(db_session, question="what is the mood in europe?")
    assert out == []


def test_earthquake_question_retrieves_quakes(db_session):
    _quake(db_session, magnitude=6.1, place="46 km NE of Tulsipur, Nepal")
    db_session.commit()
    out = sensors.build_qa_sensors(db_session, question="were there any big earthquakes?")
    assert len(out) == 1
    assert out[0]["source"] == "usgs-quake"
    assert "6.1" in out[0]["headline"]
    assert "Tulsipur" in out[0]["headline"]


def test_synonyms_reach_the_same_selector(db_session):
    _quake(db_session, magnitude=5.0, place="Chile")
    db_session.commit()
    for phrasing in ("any seismic activity?", "recent quakes?", "big earthquake lately"):
        assert sensors.build_qa_sensors(db_session, question=phrasing), phrasing


def test_severity_orders_before_recency(db_session):
    _quake(db_session, magnitude=4.0, place="Recent Small", ago_h=0.5)
    _quake(db_session, magnitude=7.2, place="Older Big", ago_h=20)
    db_session.commit()
    out = sensors.build_qa_sensors(db_session, question="any earthquakes?")
    # "Big earthquakes" wants the largest, not the newest.
    assert "7.2" in out[0]["headline"]
    assert "Older Big" in out[0]["headline"]


def test_results_are_capped(db_session):
    for i in range(40):
        _quake(db_session, magnitude=4.0 + i / 100, place=f"P{i}", ago_h=i)
    db_session.commit()
    out = sensors.build_qa_sensors(db_session, question="earthquakes?")
    assert len(out) == sensors.SENSOR_LIMIT


def test_counts_summarise_the_window_beyond_the_cap(db_session):
    for i in range(40):
        _quake(db_session, magnitude=4.0, place=f"P{i}", ago_h=i)
    db_session.commit()
    summary = sensors.build_sensor_summary(db_session, question="earthquakes?")
    assert summary["earthquake"]["count"] == 40
    # The model must be able to say "40 quakes" without being handed 40 rows.
    assert len(sensors.build_qa_sensors(db_session, question="earthquakes?")) < 40


def test_gdacs_types_map_to_their_own_words(db_session):
    _gdacs(db_session, event_type="FL", name="Kyrgyz flood")
    _gdacs(db_session, event_type="VO", name="Mayon")
    db_session.commit()
    floods = sensors.build_qa_sensors(db_session, question="any flooding?")
    assert [e["kind"] for e in floods] == ["flood"]
    volcanoes = sensors.build_qa_sensors(db_session, question="volcano news?")
    assert [e["kind"] for e in volcanoes] == ["volcano"]


def test_window_excludes_stale_events(db_session):
    _quake(db_session, magnitude=6.0, place="Ancient", ago_h=24 * 30)
    db_session.commit()
    assert sensors.build_qa_sensors(db_session, question="earthquakes?") == []


def test_numbering_continues_after_the_stories(db_session):
    _quake(db_session, magnitude=5.5, place="Nepal")
    db_session.commit()
    out = sensors.build_qa_sensors(db_session, question="earthquakes?", start_n=4)
    assert out[0]["n"] == 4


def test_sensors_count_as_evidence(db_session):
    """The refusal gate must accept sensor-only evidence.

    Otherwise "were there big earthquakes?" retrieves no *stories*, trips the
    no-evidence branch and refuses — the exact question this feature adds.
    """
    from app.brain import qa

    _quake(db_session, magnitude=6.4, place="Nepal")
    db_session.commit()
    found = sensors.build_qa_sensors(db_session, question="any big earthquakes?")
    assert qa.has_relevant_evidence([], sensors=found) is True
    assert qa.has_relevant_evidence([], sensors=[]) is False


def test_magnitude_beats_severity_for_ordering(db_session):
    """Regression for real USGS data (#507).

    `severity` is not monotonic in magnitude: production held an M7.3 at 0.5,
    an M5.5 also at 0.5 and an M6.0 at 0.25. Ordering by severity therefore
    ranked a 5.5 above a 7.3 and answered "any big earthquakes?" with the
    wrong quake.
    """
    now = datetime.now(UTC)
    for magnitude, severity, place in ((7.3, 0.5, "Big"), (5.5, 0.5, "Small"), (6.0, 0.25, "Mid")):
        db_session.add(
            EventRow(
                source="usgs-quake",
                source_event_id=f"m-{place}",
                occurred_at=now - timedelta(hours=1),
                category="hazard",
                severity=severity,
                country="MX",
                keywords=[],
                payload={"magnitude": magnitude, "place": place},
            )
        )
    db_session.commit()
    out = sensors.build_qa_sensors(db_session, question="any big earthquakes?")
    assert [e["headline"].split(" — ")[1] for e in out] == ["Big", "Mid", "Small"]


def test_same_quake_from_two_feeds_is_one_reading(db_session):
    """USGS and GDACS both publish major quakes (#507).

    Live data carried one M7.3 off Puerto Madero from both feeds. Two rows read
    as two earthquakes, so the answer would claim a quake that never happened.
    """
    now = datetime.now(UTC)
    db_session.add_all(
        [
            EventRow(
                source="usgs-quake",
                source_event_id="dup-usgs",
                occurred_at=now - timedelta(minutes=30),
                category="hazard",
                severity=0.5,
                country="MX",
                keywords=[],
                payload={"magnitude": 7.3, "place": "58 km WSW of Puerto Madero, Mexico"},
            ),
            EventRow(
                source="gdacs",
                source_event_id="dup-gdacs",
                occurred_at=now - timedelta(minutes=45),
                category="hazard",
                severity=0.5,
                country="MX",
                keywords=[],
                payload={"magnitude": 7.3, "event_type": "EQ", "eventname": ""},
            ),
        ]
    )
    db_session.commit()
    out = sensors.build_qa_sensors(db_session, question="any big earthquakes?")
    assert len(out) == 1
    # The feed that names the place wins.
    assert "Puerto Madero" in out[0]["headline"]


def test_numbering_stays_contiguous_after_dedup(db_session):
    now = datetime.now(UTC)
    db_session.add_all(
        [
            EventRow(
                source="usgs-quake",
                source_event_id="n-a",
                occurred_at=now - timedelta(minutes=10),
                category="hazard",
                severity=0.5,
                country="MX",
                keywords=[],
                payload={"magnitude": 7.3, "place": "Somewhere Long Name"},
            ),
            EventRow(
                source="gdacs",
                source_event_id="n-b",
                occurred_at=now - timedelta(minutes=20),
                category="hazard",
                severity=0.5,
                country="MX",
                keywords=[],
                payload={"magnitude": 7.3, "event_type": "EQ"},
            ),
            EventRow(
                source="usgs-quake",
                source_event_id="n-c",
                occurred_at=now - timedelta(minutes=30),
                category="hazard",
                severity=0.3,
                country="PE",
                keywords=[],
                payload={"magnitude": 5.1, "place": "Peru"},
            ),
        ]
    )
    db_session.commit()
    out = sensors.build_qa_sensors(db_session, question="earthquakes?", start_n=3)
    assert [e["n"] for e in out] == [3, 4]


def test_aftershocks_from_one_feed_are_not_collapsed(db_session):
    """Same magnitude, same feed = distinct quakes (#507).

    USGS alone carried eight separate M5.3 events in one window. Treating
    equal magnitudes as duplicates would erase a whole aftershock sequence.
    """
    now = datetime.now(UTC)
    for i in range(4):
        db_session.add(
            EventRow(
                source="usgs-quake",
                source_event_id=f"after-{i}",
                occurred_at=now - timedelta(minutes=10 * i),
                category="hazard",
                severity=0.33,
                country="CL",
                keywords=[],
                payload={"magnitude": 5.3, "place": f"Aftershock {i}"},
            )
        )
    db_session.commit()
    out = sensors.build_qa_sensors(db_session, question="earthquakes?")
    assert len(out) == 4
