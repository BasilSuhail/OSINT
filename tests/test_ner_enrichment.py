"""Tests for ``app.enrichment.ner``.

These tests cover the wrapper's behaviour both when spaCy is installed
(via mocking) and when it isn't. The CI environment doesn't install
spacy + en_core_web_sm, so the graceful-fallback path is the one that
runs there.
"""

from __future__ import annotations

from unittest.mock import patch

from app.enrichment.ner import (
    NER_METHOD_VERSION,
    Entity,
    entities_to_payload,
    extract_entities,
    is_available,
)


def test_method_version_constant() -> None:
    assert NER_METHOD_VERSION == "spacy.en_core_web_sm.v1.0"


def test_extract_empty_input_returns_empty() -> None:
    assert extract_entities("") == ()
    assert extract_entities("   ") == ()


def test_extract_returns_empty_when_model_unavailable() -> None:
    """The CI env runs without spaCy installed — wrapper falls back cleanly."""
    with patch("app.enrichment.ner._model", return_value=None):
        extract_entities.cache_clear()
        assert extract_entities("Apple announces new product in Cupertino") == ()
    extract_entities.cache_clear()


def test_is_available_reflects_model_state() -> None:
    with patch("app.enrichment.ner._model", return_value=None):
        assert is_available() is False


def test_entities_to_payload_serialises() -> None:
    payload = entities_to_payload(
        (Entity(text="Apple", label="ORG"), Entity(text="Cupertino", label="GPE"))
    )
    assert payload == [
        {"text": "Apple", "label": "ORG"},
        {"text": "Cupertino", "label": "GPE"},
    ]


def test_entities_to_payload_empty() -> None:
    assert entities_to_payload(()) == []


def test_extract_with_mock_doc_keeps_only_whitelisted_labels() -> None:
    """When the model returns extra labels (DATE / MONEY), filter them out."""

    class _MockEnt:
        def __init__(self, text: str, label: str) -> None:
            self.text = text
            self.label_ = label

    class _MockDoc:
        ents = (
            _MockEnt("Apple", "ORG"),
            _MockEnt("2026", "DATE"),
            _MockEnt("$1B", "MONEY"),
            _MockEnt("Cupertino", "GPE"),
        )

    class _MockNlp:
        def __call__(self, _text: str) -> _MockDoc:
            return _MockDoc()

    with patch("app.enrichment.ner._model", return_value=_MockNlp()):
        extract_entities.cache_clear()
        result = extract_entities("Apple announced $1B Cupertino expansion in 2026")
        labels = {e.label for e in result}
        assert labels == {"ORG", "GPE"}
        texts = [e.text for e in result]
        assert "Apple" in texts
        assert "Cupertino" in texts
    extract_entities.cache_clear()


def test_extract_dedupes_by_lowercase_text_and_label() -> None:
    class _MockEnt:
        def __init__(self, text: str, label: str) -> None:
            self.text = text
            self.label_ = label

    class _MockDoc:
        ents = (
            _MockEnt("Apple", "ORG"),
            _MockEnt("apple", "ORG"),
            _MockEnt("APPLE", "ORG"),
        )

    class _MockNlp:
        def __call__(self, _text: str) -> _MockDoc:
            return _MockDoc()

    with patch("app.enrichment.ner._model", return_value=_MockNlp()):
        extract_entities.cache_clear()
        result = extract_entities("Apple Apple APPLE")
        assert len(result) == 1
    extract_entities.cache_clear()
