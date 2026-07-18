"""Plain-voice + no-markdown guard (#480, slice of #476).

Live 2026-07-18 hard-QA answer opened "The text you provided is a dataset
snippet…" and shipped **bold** and * bullets. Prompt rules tighten, and a
deterministic sanitizer guarantees what the prompt cannot.
"""

import app.api as api
from app.brain import qa


def test_strip_markdown_removes_markers_but_keeps_pointer_lines():
    # #484: markers go, layout stays — flattening bullets into run-on prose
    # was the wall-of-text screenshot.
    raw = (
        "**The Event:** A cycle of retaliation.\n"
        "* **Iran:** strikes on infrastructure [2]\n"
        "* The Gulf: attacks on facilities\n"
        "### Conclusion\n"
        "1. Escalation continues."
    )
    out = qa.strip_markdown(raw)
    assert "*" not in out and "#" not in out
    assert out.splitlines() == [
        "The Event: A cycle of retaliation.",
        "Iran: strikes on infrastructure [2]",
        "The Gulf: attacks on facilities",
        "Conclusion",
        "Escalation continues.",
    ]


def test_strip_markdown_keeps_paragraphs_and_citations():
    raw = "First paragraph [1].\n\n\nSecond _paragraph_ [2]."
    assert qa.strip_markdown(raw) == "First paragraph [1].\n\nSecond paragraph [2]."


def test_strip_markdown_leaves_plain_text_untouched():
    plain = "Strikes resumed near the border; collapse is contested [1][2]."
    assert qa.strip_markdown(plain) == plain
    #: A lone asterisk is not emphasis.
    assert qa.strip_markdown("2 * 3 is 6.") == "2 * 3 is 6."


def test_prompt_bans_markdown_and_input_talk():
    prompt = qa.build_qa_prompt({"stories": []}, "q")
    assert "NEVER describe or mention your input in ANY words" in prompt
    assert "Never use markdown" in prompt
    assert "local reporting shows" in prompt
    #: Layout rule (#484): short paragraphs, compound questions part by part.
    assert "SHORT paragraphs separated by blank lines" in prompt
    assert "each part answered in its own paragraph" in prompt
    #: The stream/text prompt inherits the same shared rules.
    text = qa.build_qa_text_prompt({"stories": []}, "q")
    assert "Never use markdown" in text
    assert "SHORT paragraphs separated by blank lines" in text


def test_checked_answer_strips_markdown(monkeypatch):
    def must_not_call(prompt, **kw):
        raise AssertionError("no repair needed for a cited answer")

    monkeypatch.setattr(api.client, "generate_json", must_not_call)
    out = api._checked_ask_answer(
        answer="**Yes.** Strikes resumed at the border [1].",
        qa_context={"stories": []},
        question="q",
        stories=[{"n": 1, "story_id": 5, "title": "Strikes resume", "gist": None}],
        n_sources=1,
    )
    assert out == "Yes. Strikes resumed at the border [1]."
