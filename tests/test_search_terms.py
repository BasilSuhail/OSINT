"""The topic vocabulary, and the index expression it shares with the migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.search import SEARCH_VECTOR_SQL
from app.search_terms import topic_for, topic_words


def test_disaster_words_ask_for_the_hazard_category() -> None:
    for word in ("disaster", "disasters", "hazard", "hazards"):
        topic = topic_for(word)
        assert topic is not None, word
        assert topic.category == "hazard"


def test_quake_words_reach_the_tokens_the_rows_carry() -> None:
    """Nobody types "eq", and every GDACS quake is tagged with it."""
    topic = topic_for("earthquakes")
    assert topic is not None
    assert {"earthquake", "eq", "usgs"} <= topic.keywords


def test_fire_words_reach_the_detections() -> None:
    """The 1.9M rows that make up most of the map are tagged `fire`/`firms`."""
    topic = topic_for("wildfires")
    assert topic is not None
    assert {"fire", "firms"} <= topic.keywords


def test_case_and_spacing_do_not_matter() -> None:
    assert topic_for("  DISASTERS  ") == topic_for("disasters")


def test_a_sentence_is_not_a_topic() -> None:
    """ "fire" asks for fire detections; "fire at the docks" is a question, and
    answering it with a million satellite readings would bury what was asked."""
    assert topic_for("fire at the docks") is None
    assert topic_for("edinburgh") is None
    assert topic_for("") is None


def test_every_topic_word_is_lowercase_and_stripped() -> None:
    """Lookup normalises the query, so a key that is not already normal can
    never be reached."""
    for word in topic_words():
        assert word == word.lower().strip()
        assert " ".join(word.split()) == word


def test_vector_sql_matches_the_migration() -> None:
    """An expression index is only used when the query's expression is
    character-identical to the indexed one. A drifted string does not fail
    anywhere — it silently falls back to a sequential scan over 2.2M rows.

    Loaded by path: the module name begins with a digit, so it cannot be
    imported."""
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "0029_event_search_topics.py"
    )
    spec = importlib.util.spec_from_file_location("_migration_0029", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.VECTOR_SQL == SEARCH_VECTOR_SQL
