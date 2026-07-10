"""Tests for `app.validator.claims` — prompt + mechanical validation (WS-G, #378)."""

from __future__ import annotations

from app.validator.claims import METHOD_VERSION, PROMPT_VERSION, build_prompt, parse_claims


def test_build_prompt_includes_titles_and_schema() -> None:
    prompt = build_prompt(["Earthquake hits Tokyo", "Tokyo quake injures dozens"])
    assert "Earthquake hits Tokyo" in prompt
    assert "countries" in prompt and "event_type" in prompt and "casualties" in prompt


def test_parse_claims_valid_payload_passes_through() -> None:
    got = parse_claims({"countries": ["TR", "SY"], "event_type": "earthquake", "casualties": 12})
    assert got == {"countries": ["TR", "SY"], "event_type": "earthquake", "casualties": 12}


def test_parse_claims_mechanical_validation() -> None:
    got = parse_claims(
        {
            "countries": ["Turkey", "tr", "USA", 7],  # only clean ISO2 survives
            "event_type": "apocalypse",  # unknown enum → none
            "casualties": "many",  # non-int → null
        }
    )
    assert got == {"countries": ["TR"], "event_type": "none", "casualties": None}


def test_parse_claims_negative_casualties_rejected() -> None:
    got = parse_claims({"countries": [], "event_type": "wildfire", "casualties": -3})
    assert got["casualties"] is None
    assert got["event_type"] == "wildfire"


def test_parse_claims_garbage_shapes_degrade_to_empty() -> None:
    assert parse_claims({"unexpected": True}) == {
        "countries": [],
        "event_type": "none",
        "casualties": None,
    }
    assert parse_claims(None) == {"countries": [], "event_type": "none", "casualties": None}


def test_method_version_pins_model_and_prompt() -> None:
    assert PROMPT_VERSION in METHOD_VERSION
    assert "qwen3.5:4b-q4_K_M".replace(":", "-") in METHOD_VERSION
