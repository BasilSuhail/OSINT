from app.brain import qa_rubric
from app.brain.qa import REFUSAL_ANSWER


def _story(n: int, title: str, **kw):
    return {
        "n": n,
        "story_id": n * 100,
        "title": title,
        "gist": kw.pop("gist", None),
        "corroboration": kw.pop("corroboration", 0.8),
        "outlet_count": kw.pop("outlet_count", 3),
        "owner_count": kw.pop("owner_count", 2),
        "divergence": kw.pop("divergence", None),
        "contested": kw.pop("contested", False),
        "sensor": kw.pop("sensor", {}),
        "sources": kw.pop("sources", ["Reuters"]),
    }


WAR = next(q for q in qa_rubric.EVAL_QUESTIONS if q.question == "is the war back on?")
SENSOR = next(q for q in qa_rubric.EVAL_QUESTIONS if q.mode == "sensor")
CONTESTED = next(q for q in qa_rubric.EVAL_QUESTIONS if q.mode == "contested")
COVERAGE = next(q for q in qa_rubric.EVAL_QUESTIONS if q.mode == "coverage")


def test_eval_questions_cover_issue_set():
    questions = {q.question for q in qa_rubric.EVAL_QUESTIONS}
    assert questions == {
        "is the war back on?",
        "did the ceasefire collapse?",
        "what happened in Iran?",
        "what is sensor confirmed?",
        "where is coverage thin?",
        "what is contested right now?",
    }
    assert all(q.risky for q in qa_rubric.EVAL_QUESTIONS if q.mode == "topic")


def test_relevant_sources_topic_mode_matches_title_and_gist():
    stories = [
        _story(1, "Typhoon slams Philippines"),
        _story(2, "Iran ceasefire collapses after strikes"),
        _story(3, "Markets rally", gist="Ceasefire hopes lift stocks."),
    ]
    assert qa_rubric.relevant_sources(WAR, stories) == [2, 3]


def test_relevant_sources_sensor_mode_needs_sensor_dict():
    stories = [
        _story(1, "Wildfire in Spain", sensor={"fire": "confirmed"}),
        _story(2, "Political speech"),
    ]
    assert qa_rubric.relevant_sources(SENSOR, stories) == [1]


def test_relevant_sources_contested_mode_needs_contested_flag():
    stories = [_story(1, "A", contested=True), _story(2, "B")]
    assert qa_rubric.relevant_sources(CONTESTED, stories) == [1]


def test_relevant_sources_coverage_mode_accepts_all():
    stories = [_story(1, "A"), _story(2, "B")]
    assert qa_rubric.relevant_sources(COVERAGE, stories) == [1, 2]


def _score(spec, answer, stories, invalid=None, error=None):
    return qa_rubric.score_answer(
        spec, answer=answer, stories=stories, invalid_citations=invalid or [], error=error
    )


def test_wrong_topic_citation_fails_relevance_typhoon_repro():
    stories = [
        _story(1, "Typhoon slams Philippines"),
        _story(2, "Iran ceasefire collapses after strikes"),
    ]
    out = _score(WAR, "The retrieved story is: Typhoon slams Philippines [1].", stories)
    assert out["relevance"] is False
    assert out["passed"] is False
    assert any("relevant" in r for r in out["reasons"])
    # refusal dim passes: relevant evidence exists and the model did answer
    assert out["refusal"] is True


def test_relevant_cited_risky_answer_with_uncertainty_passes():
    stories = [
        _story(1, "Typhoon slams Philippines"),
        _story(2, "Iran ceasefire collapses after strikes", gist="Strikes resumed near Tehran."),
    ]
    answer = (
        "Reported strikes suggest the Iran ceasefire collapsed [2]; "
        "this remains unconfirmed by sensors."
    )
    out = _score(WAR, answer, stories)
    assert out == {
        "relevance": True,
        "citation": True,
        "uncertainty": True,
        "contested": True,
        "refusal": True,
        "usefulness": True,
        "passed": True,
        "reasons": [],
    }


def test_refusal_with_relevant_evidence_fails_refusal_dim():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    out = _score(WAR, REFUSAL_ANSWER, stories)
    assert out["refusal"] is False
    assert out["passed"] is False


def test_refusal_without_relevant_evidence_passes_all():
    stories = [_story(1, "Typhoon slams Philippines")]
    out = _score(WAR, REFUSAL_ANSWER, stories)
    assert out["passed"] is True
    assert out["reasons"] == []


def test_answer_without_relevant_evidence_fails_refusal_dim():
    stories = [_story(1, "Typhoon slams Philippines")]
    out = _score(WAR, "The war restarted yesterday [1].", stories)
    assert out["refusal"] is False


def test_risky_answer_without_uncertainty_marker_fails():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    answer = "Yes. The Iran ceasefire collapses story shows strikes resumed [1]."
    out = _score(WAR, answer, stories)
    assert out["uncertainty"] is False


def test_contested_cited_story_requires_contested_language():
    stories = [_story(1, "Iran ceasefire collapses after strikes", contested=True)]
    answer = "Reported strikes ended the Iran ceasefire [1]; details remain unclear."
    out = _score(WAR, answer, stories)
    assert out["contested"] is False
    answer_flagged = answer + " Coverage of this ceasefire story is disputed."
    assert _score(WAR, answer_flagged, stories)["contested"] is True


def test_invalid_citations_fail_citation_dim():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    answer = "Reported strikes ended the Iran ceasefire [1], sources say unconfirmed."
    out = _score(WAR, answer, stories, invalid=[9])
    assert out["citation"] is False


def test_short_generic_answer_fails_usefulness():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    out = _score(WAR, "Maybe, reported [1].", stories)
    assert out["usefulness"] is False


def test_long_answer_without_story_overlap_fails_usefulness():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    answer = "Something reportedly happened somewhere recently, details pending [1]."
    out = _score(WAR, answer, stories)
    assert out["usefulness"] is False


def test_coverage_mode_needs_coverage_language():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    good = "Coverage is thin: only one outlet reported this ceasefire story [1]."
    bad = "The Iran ceasefire collapses story is the main reported event [1]."
    assert _score(COVERAGE, good, stories)["relevance"] is True
    assert _score(COVERAGE, bad, stories)["relevance"] is False


def test_coverage_mode_refusal_is_acceptable():
    stories = [_story(1, "Iran ceasefire collapses after strikes")]
    out = _score(COVERAGE, REFUSAL_ANSWER, stories)
    assert out["refusal"] is True
    assert out["passed"] is True


def test_sensor_mode_relevance():
    stories = [
        _story(1, "Wildfire in Spain kills twelve", sensor={"fire": "confirmed"}),
        _story(2, "Political speech"),
    ]
    answer = "Sensors confirmed the Spain wildfire that reportedly killed twelve [1]."
    out = _score(SENSOR, answer, stories)
    assert out["relevance"] is True
    speech = _score(SENSOR, "The main story is a political speech [2].", stories)
    assert speech["relevance"] is False


def test_error_row_fails_every_dimension():
    out = _score(WAR, None, [_story(1, "Iran ceasefire collapses")], error="boom")
    assert out["passed"] is False
    assert all(out[d] is False for d in qa_rubric.DIMENSIONS)
    assert out["reasons"] == ["model error: boom"]


def test_no_evidence_answer_scores_as_refusal():
    from app.brain.qa import NO_EVIDENCE_ANSWER

    stories = [_story(1, "Typhoon slams Philippines")]
    out = _score(WAR, NO_EVIDENCE_ANSWER, stories)
    assert out["refusal"] is True
    assert out["passed"] is True
