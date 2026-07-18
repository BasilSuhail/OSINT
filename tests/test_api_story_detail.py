from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import app, get_session
from app.brain import enrich
from app.db_models import (
    Base,
    EventRow,
    StoryCorroborationRow,
    StoryDisagreementRow,
    StoryGistRow,
    StoryMemberRow,
    StoryRow,
    StorySensorCheckRow,
)

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _client_and_story():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        story = StoryRow(
            title="Dar holds phone call with Iranian FM amid latest attacks",
            first_seen=NOW - timedelta(days=2),
            last_seen=NOW,
            member_count=3,
            outlet_count=3,
            owner_count=3,
            method_version="stories-v1.0",
        )
        s.add(story)
        s.flush()
        sid = story.id
        for i, (source, title) in enumerate(
            [
                ("dawn", "Dar calls for de-escalation in call with Iranian FM"),
                ("geo_english", "Pakistan urges restraint amid Mideast attacks"),
                ("egypt_independent", "Iranian FM discusses attacks in call with Pakistan"),
            ]
        ):
            ev = EventRow(
                source=source,
                source_event_id=f"e{i}",
                occurred_at=NOW - timedelta(hours=i),
                fetched_at=NOW,
                category="conflict",
                payload={"title": title},
            )
            s.add(ev)
            s.flush()
            s.add(StoryMemberRow(event_id=ev.id, story_id=sid, similarity=0.9 - i * 0.1))
        s.add_all(
            [
                StoryGistRow(
                    story_id=sid,
                    gist="Pakistan and Iran discuss de-escalation after attacks.",
                    category="conflict",
                    escalating="yes",
                    model="m",
                    method_version=enrich.METHOD_VERSION,
                ),
                StoryCorroborationRow(
                    story_id=sid,
                    score=0.938,
                    components={"outlets": 3},
                    method_version="corroboration-v1.0",
                    computed_at=NOW,
                ),
                StoryDisagreementRow(
                    story_id=sid,
                    divergence=1.0,
                    components={"groups": {"EG": 1, "PK": 2}},
                    method_version="disagreement-v1.0",
                    computed_at=NOW,
                ),
                StorySensorCheckRow(
                    story_id=sid,
                    claim_type="conflict",
                    verdict="unconfirmed",
                    method_version="corroboration-v1.0",
                    checked_at=NOW,
                ),
            ]
        )
        s.commit()

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    return TestClient(app), sid


def test_story_detail_aggregates_everything():
    client, sid = _client_and_story()
    body = client.get(f"/stories/{sid}/detail").json()

    assert body["title"].startswith("Dar holds phone call")
    assert body["gist"] == "Pakistan and Iran discuss de-escalation after attacks."
    assert body["category"] == "conflict"
    assert body["escalating"] == "yes"
    assert body["member_count"] == 3
    assert body["outlet_count"] == 3
    assert body["corroboration"] == 0.938
    assert body["corroboration_components"] == {"outlets": 3}
    assert body["divergence"] == 1.0
    assert body["divergence_groups"] == {"EG": 1, "PK": 2}
    assert body["sensor_checks"] == {"conflict": "unconfirmed"}
    assert body["first_seen"] < body["last_seen"]

    members = body["members"]
    assert len(members) == 3
    assert {m["title"] for m in members} == {
        "Dar calls for de-escalation in call with Iranian FM",
        "Pakistan urges restraint amid Mideast attacks",
        "Iranian FM discusses attacks in call with Pakistan",
    }
    assert all("outlet" in m and "origin_country" in m and "occurred_at" in m for m in members)
    app.dependency_overrides.clear()


def test_story_members_carry_outlet_class():
    # Voices UI (#488): every member names its outlet class; slugs the registry
    # does not know (legacy sources) fall back to mainstream.
    client, sid = _client_and_story()
    members = client.get(f"/stories/{sid}/members").json()
    assert len(members) == 3
    assert all(
        m["outlet_class"] in {"mainstream", "state", "regional", "independent"} for m in members
    )
    detail = client.get(f"/stories/{sid}/detail").json()
    assert all("outlet_class" in m for m in detail["members"])
    app.dependency_overrides.clear()


def test_story_drilldown_links_summaries_and_contrast():
    # #492: members expose the article URL + payload summary + sentiment, and
    # the detail names WHAT each origin bloc says that the others don't.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        story = StoryRow(
            title="Iranian attack on Jordan base",
            first_seen=NOW - timedelta(hours=6),
            last_seen=NOW,
            member_count=3,
            outlet_count=3,
            owner_count=3,
            method_version="stories-v1.0",
        )
        s.add(story)
        s.flush()
        sid = story.id
        seeds = [
            (
                "rss-bbc-world",
                "Two US troops killed after Iranian attack",
                "Soldiers killed and one missing after missile barrage.",
            ),
            (
                "rss-guardian-world",
                "US troops killed in Iranian attack",
                "Missile barrage killed soldiers at the base.",
            ),
            (
                "rss-aljazeera",
                "Iran suggests MoU suspended amid strikes",
                "Tehran frames the attack as retaliation; MoU suspended.",
            ),
        ]
        for i, (source, title, summary) in enumerate(seeds):
            ev = EventRow(
                source=source,
                source_event_id=f"d{i}",
                occurred_at=NOW - timedelta(hours=i),
                fetched_at=NOW,
                category="conflict",
                payload={
                    "title": title,
                    "summary": summary,
                    "source_url": f"https://example.org/a{i}",
                    "sentiment_label": "negative",
                },
            )
            s.add(ev)
            s.flush()
            s.add(StoryMemberRow(event_id=ev.id, story_id=sid, similarity=0.9))
        s.add(
            StoryDisagreementRow(
                story_id=sid,
                divergence=0.7,
                components={"groups": {"GB": 2, "QA": 1}},
                method_version="disagreement-v1.0",
                computed_at=NOW,
            )
        )
        s.commit()

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    body = TestClient(app).get(f"/stories/{sid}/detail").json()

    members = body["members"]
    assert all(m["url"].startswith("https://example.org/") for m in members)
    assert all(m["summary"] for m in members)
    assert all(m["sentiment"] == "negative" for m in members)

    contrast = body["divergence_contrast"]
    #: GB bloc (BBC + Guardian) alone talks about killed troops; QA bloc
    #: (Al Jazeera) alone talks about the MoU suspension. "attack" appears in
    #: both blocs' texts, so it is distinctive for neither.
    assert "mou" in contrast["QA"]
    assert "killed" in contrast["GB"]
    assert "attack" not in contrast["GB"] and "attack" not in contrast["QA"]
    app.dependency_overrides.clear()


def test_story_detail_unknown_id_is_404():
    client, _ = _client_and_story()
    assert client.get("/stories/999999/detail").status_code == 404
    app.dependency_overrides.clear()


def test_story_detail_minimal_story_has_null_enrichment():
    # A story with no gist/corroboration/disagreement/sensors must not 500.
    client, _sid = _client_and_story()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as s:
        story = StoryRow(
            title="Bare story",
            first_seen=NOW,
            last_seen=NOW,
            method_version="stories-v1.0",
        )
        s.add(story)
        s.commit()
        bare_id = story.id

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    body = client.get(f"/stories/{bare_id}/detail").json()
    assert body["title"] == "Bare story"
    assert body["gist"] is None
    assert body["corroboration"] is None
    assert body["divergence"] is None
    assert body["members"] == []
    app.dependency_overrides.clear()
