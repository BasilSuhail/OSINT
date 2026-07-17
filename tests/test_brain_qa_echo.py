from app.brain import qa, qa_rubric

_PREV = (
    "Yes, multiple independent outlets report that the US is launching strikes on Iran "
    "again. Tehran warns of an 'existential war' with America, with corroboration from "
    "four outlets including Al Jazeera English, CBC World, and the Straits Times World [2]."
)


def test_echo_detects_verbatim_copy():
    assert qa.answer_echoes(_PREV, _PREV) is True


def test_echo_detects_recycled_sentences():
    current = (
        "According to the available reports, the US has completed strikes on Iran [4]. "
        "Tehran warns of an 'existential war' with America, with corroboration from "
        "four outlets including Al Jazeera English, CBC World, and the Straits Times World [2]."
    )
    assert qa.answer_echoes(_PREV, current) is True


def test_echo_allows_fresh_answer_on_same_topic():
    current = (
        "Three strikes so far — the third hit this week according to CENTCOM [4]. "
        "No outlet gives a total beyond that, so treat any larger count as unconfirmed."
    )
    assert qa.answer_echoes(_PREV, current) is False


def test_echo_exempts_canned_answers():
    assert qa.answer_echoes(qa.REFUSAL_ANSWER, qa.REFUSAL_ANSWER) is False
    assert qa.answer_echoes(qa.NO_EVIDENCE_ANSWER, qa.NO_EVIDENCE_ANSWER) is False


def test_echo_handles_short_answers():
    assert qa.answer_echoes("Yes.", "Yes.") is False  # too short to call an echo
    assert qa.answer_echoes("", "anything") is False


def test_conversation_block_truncates_answers_hard():
    history = [{"question": "q1", "answer": "x" * 1000}]
    block = qa._conversation_block(history)
    line = next(entry for entry in block.split("\n") if entry.startswith("A:"))
    assert len(line) <= 130


def test_conversation_block_forbids_repeating():
    block = qa._conversation_block([{"question": "q", "answer": "a"}])
    assert "never repeat" in block.lower() or "do not repeat" in block.lower()


def test_prompt_has_tone_and_no_echo_rules():
    prompt = qa.build_qa_prompt({"stories": []}, "how many attacks?")
    low = prompt.lower()
    assert "lead with it" in low  # numbers/dates/names answered directly
    assert "do not take sides" in low
    assert "what each side" in low
    assert "fresh" in low or "never repeat" in low or "do not repeat" in low


def test_rubric_echo_dimension_fails_on_copy():
    spec = qa_rubric.EVAL_QUESTIONS[0]
    stories = [
        {
            "n": 1,
            "story_id": 1,
            "title": "US strikes Iran in new wave of attacks on military sites",
            "gist": "US strikes Iran; war escalation continues across the region.",
            "contested": False,
            "owner_count": 3,
            "corroboration": 0.9,
            "sensor": {},
        }
    ]
    answer = (
        "Yes, the war is back on: the US launched a new wave of strikes on Iran's "
        "military sites, and the conflict is escalating across the region [1]. "
        "This is reported, not established fact."
    )
    fresh = qa_rubric.score_answer(
        spec, answer=answer, stories=stories, invalid_citations=[], previous_answer=None
    )
    assert fresh["echo"] is True

    copied = qa_rubric.score_answer(
        spec, answer=answer, stories=stories, invalid_citations=[], previous_answer=answer
    )
    assert copied["echo"] is False
    assert copied["passed"] is False
    assert any("echo" in r or "repeat" in r for r in copied["reasons"])


def test_rubric_dimensions_include_echo():
    assert "echo" in qa_rubric.DIMENSIONS


def test_echo_retry_prompt_names_the_problem():
    prompt = qa.build_echo_retry_prompt(
        {"stories": []}, "how many attacks?", "draft answer", "previous answer"
    )
    low = prompt.lower()
    assert "repeat" in low
    assert "new question" in low
    assert "DRAFT_ANSWER" in prompt and "PREVIOUS_ANSWER" in prompt
