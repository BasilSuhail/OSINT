from app.brain import qa_rubric


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
