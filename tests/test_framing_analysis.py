"""Deterministic framing analysis (#605).

Replaces the raw 'X alone says: a, b, c' keyword dump with a per-bloc read —
article count, tone lean (from VADER sentiment labels), distinctive wording —
plus a synthesis contrasting the two loudest blocs. All keyword + sentiment,
no LLM: the structured logic lives (and is tested) here in Python; the frontend
only interpolates country names into it.
"""

from app.api import _framing_analysis, _tone_lean


def _m(country: str, text: str, sentiment: str) -> dict:
    return {"origin_country": country, "title": text, "summary": "", "sentiment": sentiment}


# ---- tone buckets ------------------------------------------------------------


def test_tone_lean_buckets():
    assert _tone_lean(["negative", "negative", "negative"]) == "mostly negative"
    assert _tone_lean(["negative", "negative", "neutral", "neutral"]) == "leans negative"
    assert _tone_lean(["positive", "positive", "positive"]) == "mostly positive"
    assert _tone_lean(["negative", "negative", "positive", "positive"]) == "mixed"
    assert _tone_lean(["neutral", "neutral"]) == "neutral"
    assert _tone_lean([]) == "tone unclear"


# ---- framing structure -------------------------------------------------------


def test_framing_is_none_below_two_blocs():
    members = [_m("RU", "sanctions anti", "negative"), _m("RU", "brussels fail", "negative")]
    assert _framing_analysis(members) is None


def _mixed_story() -> list[dict]:
    return [
        _m("RU", "sanctions anti", "negative"),
        _m("RU", "brussels fail", "negative"),
        _m("RU", "commission agree", "negative"),
        _m("FR", "deal exemption", "neutral"),
        _m("FR", "reached clients", "neutral"),
    ]


def test_framing_orders_loudest_bloc_first_with_tone_and_terms():
    framing = _framing_analysis(_mixed_story())
    blocs = framing["blocs"]
    assert [b["country"] for b in blocs] == ["RU", "FR"]  # RU has more articles
    ru = blocs[0]
    assert ru["articles"] == 3
    assert ru["tone"] == "mostly negative"
    # Distinctive terms: RU's words that FR never uses.
    assert "anti" in ru["terms"] and "fail" in ru["terms"]
    assert "deal" not in ru["terms"]
    fr = blocs[1]
    assert fr["tone"] == "neutral"
    assert "deal" in fr["terms"]


def test_framing_synthesis_contrasts_the_two_loudest_blocs():
    synthesis = _framing_analysis(_mixed_story())["synthesis"]
    assert synthesis["a"] == "RU" and synthesis["b"] == "FR"
    assert synthesis["a_tone"] == "mostly negative"
    assert synthesis["b_tone"] == "neutral"
    assert set(synthesis["a_terms"]) <= {
        "sanctions",
        "anti",
        "brussels",
        "fail",
        "commission",
        "agree",
    }
    assert set(synthesis["b_terms"]) <= {"deal", "exemption", "reached", "clients"}
    assert synthesis["a_terms"] and synthesis["b_terms"]
