"""Source diversity: outlet classes + voices in Q&A (#477).

Basil's accuracy clause: trust needs comparison across mainstream,
state, regional, and independent voices — coverage volume is not proof.
"""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.sources.rss_registry as rss_registry
from app.brain import qa
from app.db_models import Base
from tests.test_brain_qa_details import _add_member
from tests.test_brain_qa_stories import _add_story

VALID_CLASSES = {"mainstream", "state", "regional", "independent"}


def test_every_feed_has_a_valid_class():
    class_of = rss_registry.outlet_class_map()
    assert len(class_of) >= 44
    assert set(class_of.values()) == VALID_CLASSES
    assert class_of["rss-tass-en"] == "state"
    assert class_of["rss-bbc-world"] == "mainstream"
    assert class_of["rss-dawn"] == "regional"
    assert class_of["rss-bellingcat"] == "independent"


def test_new_independent_feeds_are_registered_and_scheduled():
    configs = {cfg.source: cfg for cfg in rss_registry.load_feed_configs()}
    for slug in (
        "rss-intercept",
        "rss-middle-east-eye",
        "rss-antiwar",
        "rss-responsible-statecraft",
        "rss-bellingcat",
        "rss-global-voices",
        "rss-consortium-news",
    ):
        assert slug in configs
        assert configs[slug].url.startswith("https://")
    #: Slugs stay unique — a duplicate would orphan events rows.
    raw_slugs = [cfg.source for cfg in rss_registry.load_feed_configs()]
    assert len(raw_slugs) == len(set(raw_slugs))
    #: Owners feed the independence machinery (#464).
    owners = rss_registry.content_owner_map()
    assert owners["rss-bellingcat"] == "bellingcat"


def test_story_voices_group_outlets_by_class(monkeypatch):
    now = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    sid = _add_story(
        session,
        now,
        title="War strikes resume at the border",
        source="rss-bbc-world",
        source_event_id="e1",
        outlet_count=3,
        category="conflict",
        gist="Cross-border strikes.",
    )
    _add_member(session, sid, source="rss-tass-en", event_id="e2", title="Strikes: TASS angle")
    _add_member(session, sid, source="rss-antiwar", event_id="e3", title="Strikes: antiwar angle")

    out = qa.build_qa_stories(session, now=now, question="is the war back on?")

    voices = out[0]["voices"]
    assert voices["mainstream"] == ["BBC World"]
    assert voices["state"] == ["TASS English"]
    assert voices["independent"] == ["Antiwar.com"]


def test_prompt_carries_voices_and_claim_status_rules():
    prompt = qa.build_qa_prompt({"stories": []}, "q")
    assert '"voices" — the story\'s outlets grouped by class' in prompt
    assert "Compare voices" in prompt
    assert "A claim only state media carries is never confirmed" in prompt
    assert "confirmed, reported, contested, denied, inferred, or unknown" in prompt
    text = qa.build_qa_text_prompt({"stories": []}, "q")
    assert "Compare voices" in text
