from app.brain import qa

_STORIES = [
    {
        "n": 1,
        "story_id": 10,
        "title": "Trade ban on Israeli settlements is the latest test of EU unity",
        "gist": "EU weighs a trade ban covering Israeli settlement goods.",
    },
    {
        "n": 2,
        "story_id": 11,
        "title": "Explosion heard on Iran's Qeshm island",
        "gist": "Multiple explosions reported near the Strait of Hormuz.",
    },
]


def test_salvage_appends_citation_of_matching_story():
    draft = (
        "Yes, there is a trade ban on Israeli settlements, described as the latest "
        "test of EU unity, though its scope is not detailed."
    )
    out = qa.attach_supported_citation(draft, _STORIES)
    assert out == f"{draft} [1]"
    assert qa.citation_compliant(out, len(_STORIES))


def test_salvage_picks_best_matching_story():
    draft = "Multiple explosions were reported on Qeshm island near the Strait of Hormuz."
    out = qa.attach_supported_citation(draft, _STORIES)
    assert out is not None
    assert out.endswith("[2]")


def test_salvage_refuses_ungrounded_draft():
    assert qa.attach_supported_citation("Aliens landed in Paris overnight.", _STORIES) is None


def test_salvage_refuses_thin_overlap():
    # A single shared word is not grounding.
    assert qa.attach_supported_citation("The islanders vote today.", _STORIES) is None


def test_salvage_handles_no_stories():
    assert qa.attach_supported_citation("Anything at all.", []) is None
