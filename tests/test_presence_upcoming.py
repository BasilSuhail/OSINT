"""What is scheduled, grouped so a country's election day is one line (#934).

Everything else this console shows is past tense. This is the one thing that
looks forward, and it is still presence: fetched, shown, discarded, never
citable.

The grouping is the feature. Forty US Senate races are forty Wikidata items and
one election day; unfolded onto a panel they bury every other country in the
world. The jurisdiction filter that would collapse them upstream —
`P1001` to a sovereign state — was measured at a 65 s timeout against the live
endpoint, so the collapse happens here, on (country, date), for nothing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.presence import upcoming as up


def _binding(name: str, day: str, iso: str | None, kind: str = "public election") -> dict:
    row = {
        "itemLabel": {"value": name},
        "begin": {"value": f"{day}T00:00:00Z"},
        "typeLabel": {"value": kind},
    }
    if iso:
        row["iso"] = {"value": iso}
        row["countryLabel"] = {"value": {"US": "United States", "SE": "Sweden"}.get(iso, iso)}
    return row


def _body(*rows: dict) -> dict:
    return {"results": {"bindings": list(rows)}}


@pytest.fixture(autouse=True)
def _clear():
    up.clear_cache()
    yield
    up.clear_cache()


def test_one_scheduled_thing_is_named_as_itself() -> None:
    entries = up.group(
        up.parse(_body(_binding("2026 Swedish general election", "2026-09-13", "SE")))
    )
    assert len(entries) == 1
    assert entries[0]["headline"] == "2026 Swedish general election"
    assert entries[0]["count"] == 1
    assert entries[0]["iso"] == "SE"
    assert entries[0]["starts_on"] == "2026-09-13"


def test_a_country_voting_on_one_day_is_one_line() -> None:
    entries = up.group(
        up.parse(
            _body(
                _binding("2026 Iowa elections", "2026-11-03", "US"),
                _binding("2026 United States Senate election in Maine", "2026-11-03", "US"),
                _binding("2026 California gubernatorial election", "2026-11-03", "US"),
            )
        )
    )
    assert len(entries) == 1
    assert entries[0]["count"] == 3


def test_a_collapsed_group_is_never_named_after_one_of_its_members() -> None:
    """Picking the shortest label put "2026 Iowa elections" at the head of
    fifty-seven American contests, which reads as a fact about Iowa."""
    entries = up.group(
        up.parse(
            _body(
                _binding("2026 Iowa elections", "2026-11-03", "US"),
                _binding("2026 Maine Senate election", "2026-11-03", "US"),
            )
        )
    )
    assert entries[0]["headline"] == "2 public elections"
    assert "Iowa" not in entries[0]["headline"]


def test_a_mixed_day_names_what_it_holds_rather_than_one_of_them() -> None:
    """Measured live, one US day carries 56 public elections, a presidential
    election and a referendum. Calling it "58 public elections" is wrong;
    calling it "58 events scheduled" is true and useless."""
    entries = up.group(
        up.parse(
            _body(
                _binding("A referendum", "2026-11-03", "US", kind="referendum"),
                _binding("An election", "2026-11-03", "US", kind="public election"),
            )
        )
    )
    assert entries[0]["headline"] == "2 elections and referendums"


def test_a_day_with_no_kind_at_all_still_says_how_many() -> None:
    entries = up.group(
        up.parse(
            _body(
                {
                    "itemLabel": {"value": "One"},
                    "begin": {"value": "2026-11-03T00:00:00Z"},
                    "iso": {"value": "US"},
                    "countryLabel": {"value": "United States"},
                },
                {
                    "itemLabel": {"value": "Two"},
                    "begin": {"value": "2026-11-03T00:00:00Z"},
                    "iso": {"value": "US"},
                    "countryLabel": {"value": "United States"},
                },
            )
        )
    )
    assert entries[0]["headline"] == "2 events scheduled"


def test_several_flavours_of_election_are_still_elections() -> None:
    """Measured live: a US election day carries presidential, general and public
    elections at once. Calling that "58 events scheduled" is true and says less
    than the source knows."""
    entries = up.group(
        up.parse(
            _body(
                _binding("One", "2026-11-03", "US", kind="presidential election"),
                _binding("Two", "2026-11-03", "US", kind="general election"),
                _binding("Three", "2026-11-03", "US", kind="public election"),
            )
        )
    )
    assert entries[0]["headline"] == "3 elections"


def test_two_countries_on_one_day_stay_apart() -> None:
    entries = up.group(
        up.parse(
            _body(
                _binding("A US election", "2026-11-03", "US"),
                _binding("A Swedish election", "2026-11-03", "SE"),
            )
        )
    )
    assert len(entries) == 2
    assert {entry["iso"] for entry in entries} == {"US", "SE"}


def test_a_thing_with_no_country_is_still_shown() -> None:
    """A territory with no ISO code is not nothing. It cannot be grouped by
    country, so it stands alone rather than being dropped."""
    entries = up.group(up.parse(_body(_binding("An island election", "2026-11-03", None))))
    assert len(entries) == 1
    assert entries[0]["iso"] is None
    assert entries[0]["country"] is None


def test_things_with_no_country_are_not_grouped_with_each_other() -> None:
    entries = up.group(
        up.parse(
            _body(
                _binding("One island election", "2026-11-03", None),
                _binding("Another island election", "2026-11-03", None),
            )
        )
    )
    assert len(entries) == 2


def test_the_soonest_comes_first() -> None:
    entries = up.group(
        up.parse(
            _body(
                _binding("Later", "2026-11-03", "US"),
                _binding("Sooner", "2026-09-13", "SE"),
            )
        )
    )
    assert [entry["headline"] for entry in entries] == ["Sooner", "Later"]


def test_a_row_with_an_unreadable_date_is_dropped_rather_than_shown_wrong() -> None:
    body = _body(_binding("Fine", "2026-09-13", "SE"))
    body["results"]["bindings"].append(
        {
            "itemLabel": {"value": "Broken"},
            "begin": {"value": "not a date"},
            "typeLabel": {"value": "public election"},
        }
    )
    entries = up.group(up.parse(body))
    assert [entry["headline"] for entry in entries] == ["Fine"]


def test_the_window_is_asked_for_in_the_query() -> None:
    today = date(2026, 8, 12)
    query = up.build_query(today, days=90)
    assert "2026-08-12T00:00:00Z" in query
    assert "2026-11-10T00:00:00Z" in query
    # The class list is the whole performance story: convention, meeting and
    # voting cost eight seconds and returned wiki-conferences (#934).
    assert "wd:Q625994" not in query
    assert "wd:Q2761147" not in query
    assert "wd:Q40231" in query


def test_a_country_filter_leaves_the_rest_of_the_world_alone() -> None:
    """One upstream query serves every country. Filtering happens over the
    cached answer, so asking about France does not re-ask Wikidata."""
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json=_body(
                _binding("A US election", "2026-11-03", "US"),
                _binding("A Swedish election", "2026-09-13", "SE"),
            ),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    everything = up.scheduled(client=client)
    swedish = up.scheduled(client=client, iso="SE")

    assert calls["n"] == 1
    assert everything["count"] == 2
    assert swedish["count"] == 1
    assert swedish["entries"][0]["iso"] == "SE"


def test_an_upstream_failure_is_an_empty_calendar_that_says_so() -> None:
    """Presence never shows a stale picture. An empty list marked degraded is
    the honest answer; yesterday's calendar presented as today's is not."""

    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    answer = up.scheduled(client=client)
    assert answer["entries"] == []
    assert answer["degraded"] is True


def test_a_failure_is_not_cached_as_though_it_were_an_answer() -> None:
    """A minute of downstream silence must not become six hours of empty
    calendar."""
    state = {"fail": True}

    def handler(_: httpx.Request) -> httpx.Response:
        if state["fail"]:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json=_body(_binding("An election", "2026-09-13", "SE")))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert up.scheduled(client=client)["degraded"] is True
    state["fail"] = False
    assert up.scheduled(client=client)["degraded"] is False


def test_the_answer_says_when_it_was_fetched() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_body(_binding("An election", "2026-09-13", "SE")))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetched = up.scheduled(client=client)["fetched_at"]
    assert datetime.fromisoformat(fetched) <= datetime.now(UTC) + timedelta(seconds=1)


def test_presence_never_reaches_the_database() -> None:
    """The tier is defined by what it refuses to keep, not by tense (#873).

    A calendar is future-tense where the rest of presence is present-tense, and
    it belongs here anyway: nothing is written, nothing is retained, nothing can
    be cited from it later.
    """
    source = (up.__file__).replace(".pyc", ".py")
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    for forbidden in ("app.models", "sqlmodel", "Session", "session"):
        assert forbidden not in text, f"presence must not reach the database: {forbidden}"
