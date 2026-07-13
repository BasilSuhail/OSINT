from app.brain import enrich


def test_parse_gist_coerces_non_string_tags_without_crashing():
    # A small model can emit a list/dict/int where a bare enum string was asked
    # for; `x in frozenset` would raise TypeError on unhashable input. The parser
    # must coerce to the safe fallback, never crash.
    out = enrich.parse_gist({"gist": 123, "category": ["conflict"], "escalating": {"v": "yes"}})
    assert out == {"gist": "", "category": "other", "escalating": "unclear"}


def test_parse_gist_keeps_valid_values():
    out = enrich.parse_gist(
        {"gist": "Border clashes reported.", "category": "conflict", "escalating": "yes"}
    )
    assert out == {
        "gist": "Border clashes reported.",
        "category": "conflict",
        "escalating": "yes",
    }


def test_parse_gist_coerces_off_enum_to_fallbacks():
    out = enrich.parse_gist({"gist": "x", "category": "sports", "escalating": "maybe"})
    assert out["category"] == "other"
    assert out["escalating"] == "unclear"


def test_parse_gist_handles_missing_keys():
    out = enrich.parse_gist({})
    assert out["gist"] == ""
    assert out["category"] == "other"
    assert out["escalating"] == "unclear"


def test_parse_gist_truncates_long_gist():
    out = enrich.parse_gist({"gist": "z" * 999, "category": "other", "escalating": "no"})
    assert len(out["gist"]) <= enrich.GIST_MAX_CHARS


def test_build_gist_prompt_has_enums_and_titles():
    prompt = enrich.build_gist_prompt(["Border clashes reported", "Troops mass at frontier"])
    assert "conflict" in prompt and "escalating" in prompt
    assert "only" in prompt.lower()  # no-fabrication
    assert "Border clashes reported" in prompt
