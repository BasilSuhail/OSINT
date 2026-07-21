"""Daily narrative volume for the lead-time gate (#518).

The gate previously drew its narrative side from `GdeltBackfill`, which asked
the DOC API for an article list with `format=tsv`. GDELT rejects that with
"Invalid format." at HTTP 200, so `raise_for_status()` passed, the parser found
nothing, and the backtest scored a confident FAIL against an empty narrative
series. These cover the replacement: one call per window returning daily counts,
errors that are loud, and a cache so the gate can be re-run offline.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.backtest import narrative, pacing


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch, tmp_path):
    """Unit tests must not actually observe GDELT's 5s pacing.

    Without this the suite spent 3.5 minutes asleep, which is the opposite of a
    gate meant to be re-run constantly. Pacing state also goes to a tmp path so
    a test run never inherits — or leaves behind — a real cooldown (#559).
    Tests that assert pacing install their own recording pacer.
    """
    monkeypatch.setattr(
        narrative,
        "_pacer",
        lambda: pacing.Pacer(
            state_path=tmp_path / "pacing.json",
            min_interval_s=0.0,
            cooldown_s=0.0,
            sleep_fn=lambda _s: None,
        ),
    )


_CSV = (
    "Date,Series,Value\n"
    "2026-06-01,Article Count,1317\n"
    "2026-06-01,Total Monitored Articles,159665\n"
    "2026-06-02,Article Count,1519\n"
    "2026-06-02,Total Monitored Articles,182921\n"
    "2026-06-03,Article Count,1578\n"
    "2026-06-03,Total Monitored Articles,171004\n"
)


def test_parses_article_counts_only():
    counts = narrative.parse_timeline(_CSV)
    assert counts == {
        date(2026, 6, 1): 1317,
        date(2026, 6, 2): 1519,
        date(2026, 6, 3): 1578,
    }


def test_ignores_the_monitored_total_series():
    """ "Total Monitored Articles" is the whole corpus, not this country's news.

    Counting it would make every country look identically loud.
    """
    counts = narrative.parse_timeline(_CSV)
    assert 159665 not in counts.values()


def test_error_body_at_http_200_raises(monkeypatch):
    """GDELT reports failure with a 200 and a prose body (#518).

    Returning an empty series here is what turned a broken request into a FAIL
    verdict on the project's central claim.
    """

    def fake_get(url, params, timeout):
        return httpx.Response(200, text="Invalid format.\n")

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    with pytest.raises(narrative.NarrativeUnavailableError):
        narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)


def test_rate_limit_body_raises(monkeypatch):
    def fake_get(url, params, timeout):
        return httpx.Response(200, text="Please limit requests to one every 5 seconds")

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    with pytest.raises(narrative.NarrativeUnavailableError):
        narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)


def test_empty_window_raises_rather_than_scoring_zero(monkeypatch):
    """No rows is indistinguishable from a broken query, so it must not pass."""

    def fake_get(url, params, timeout):
        return httpx.Response(200, text="Date,Series,Value\n")

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    with pytest.raises(narrative.NarrativeUnavailableError):
        narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)


def test_result_is_cached_so_reruns_need_no_network(tmp_path, monkeypatch):
    """The gate is meant to be run over and over; GDELT allows one call per 5s."""
    calls = {"n": 0}

    def fake_get(url, params, timeout):
        calls["n"] += 1
        return httpx.Response(200, text=_CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    first = narrative.fetch_daily_volume(
        "JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=tmp_path
    )
    second = narrative.fetch_daily_volume(
        "JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=tmp_path
    )
    assert first == second
    assert calls["n"] == 1


def test_cache_key_separates_country_and_window(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params, timeout):
        calls["n"] += 1
        return httpx.Response(200, text=_CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=tmp_path)
    narrative.fetch_daily_volume("PE", date(2026, 6, 1), date(2026, 6, 3), cache_dir=tmp_path)
    narrative.fetch_daily_volume("JP", date(2026, 5, 1), date(2026, 5, 3), cache_dir=tmp_path)
    assert calls["n"] == 3


def test_series_fills_missing_days_with_zero():
    """A quiet day is a real zero; a gap must not shorten the series."""
    counts = {date(2026, 6, 1): 5, date(2026, 6, 3): 7}
    days, values = narrative.daily_series(counts, date(2026, 6, 1), date(2026, 6, 4))
    assert days == [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3), date(2026, 6, 4)]
    assert values == [5.0, 0.0, 7.0, 0.0]


def test_retries_a_rate_limit_then_succeeds(monkeypatch):
    """GDELT answers bursts with 429 for a while (#518).

    The gate makes one call per registry event, so it must pace itself and
    recover rather than failing the whole run on the first refusal.
    """
    calls = {"n": 0}

    def fake_get(url, params, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, text="Please limit requests to one every 5 seconds")
        return httpx.Response(200, text=_CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    counts = narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)
    assert counts[date(2026, 6, 1)] == 1317
    assert calls["n"] == 2


def test_gives_up_after_repeated_rate_limits(monkeypatch):
    def fake_get(url, params, timeout):
        return httpx.Response(200, text="Please limit requests to one every 5 seconds")

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    with pytest.raises(narrative.NarrativeUnavailableError):
        narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)


def test_paces_calls_to_respect_the_published_limit(monkeypatch, tmp_path):
    """One request every five seconds is GDELT's stated rule."""
    slept: list[float] = []
    now = [1000.0]

    def fake_get(url, params, timeout):
        return httpx.Response(200, text=_CSV)

    def fake_sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    monkeypatch.setattr(
        narrative,
        "_pacer",
        lambda: pacing.Pacer(
            state_path=tmp_path / "pacing.json",
            min_interval_s=5.0,
            time_fn=lambda: now[0],
            sleep_fn=fake_sleep,
        ),
    )
    narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)
    narrative.fetch_daily_volume("PE", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)
    assert any(s >= 5.0 - 0.01 for s in slept)


def test_a_refusal_makes_the_next_process_wait(monkeypatch, tmp_path):
    """The #559 fix: a 429 must outlive the call that earned it.

    Two separate pacers over one state file stand in for two runs. The second
    must not fire immediately just because it is new.
    """
    state = tmp_path / "pacing.json"
    now = [1000.0]
    slept: list[float] = []

    def make_pacer():
        return pacing.Pacer(
            state_path=state,
            min_interval_s=5.0,
            cooldown_s=60.0,
            time_fn=lambda: now[0],
            sleep_fn=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)),
        )

    monkeypatch.setattr(narrative.httpx, "get", lambda url, params, timeout: httpx.Response(429))
    monkeypatch.setattr(narrative, "_pacer", make_pacer)
    with pytest.raises(narrative.NarrativeUnavailableError):
        narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)

    assert make_pacer().cooldown_remaining() > 0


def test_query_uses_the_country_name_not_the_iso_code(monkeypatch):
    """GDELT's sourcecountry: operator takes a name (#520).

    The gate sent `sourcecountry:jp` and GDELT returned nothing for Japan, the
    Philippines, Russia, China and Chile — five of the largest news markets in
    the world. Same failure class #518 fixed, reintroduced one layer up: a
    malformed query that yields an empty result.
    """
    seen: dict = {}

    def fake_get(url, params, timeout):
        seen.update(params)
        return httpx.Response(200, text=_CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)
    assert seen["query"] == "sourcecountry:japan"


def test_unmappable_country_raises_rather_than_sending_the_code(monkeypatch):
    """Sending the raw code is what produced silent empty windows."""

    def fake_get(url, params, timeout):  # pragma: no cover - must not be reached
        raise AssertionError("should not call GDELT with an unmappable country")

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    with pytest.raises(narrative.NarrativeUnavailableError):
        narrative.fetch_daily_volume("ZZ", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)


def test_explicit_query_still_wins(monkeypatch):
    seen: dict = {}

    def fake_get(url, params, timeout):
        seen.update(params)
        return httpx.Response(200, text=_CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    narrative.fetch_daily_volume(
        "JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None, query="theme:DISASTER"
    )
    assert seen["query"] == "theme:DISASTER"


def test_cache_key_changes_with_the_query(tmp_path, monkeypatch):
    """A changed query must not reuse data fetched by the old one (#520).

    The cache is keyed by country and window, so the entries fetched with the
    buggy `sourcecountry:jp` token would otherwise be served forever — a fixed
    bug that keeps returning its own wrong answers.
    """
    calls = {"n": 0}

    def fake_get(url, params, timeout):
        calls["n"] += 1
        return httpx.Response(200, text=_CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=tmp_path)
    narrative.fetch_daily_volume(
        "JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=tmp_path, query="theme:DISASTER"
    )
    assert calls["n"] == 2


def test_topic_scopes_the_query_to_the_event(monkeypatch):
    """Total national volume drowns the event (#528).

    Japan publishes ~1,300 articles a day; a M6 earthquake adds perhaps thirty.
    Asking whether a country's whole news output spiked is not the question —
    the question is whether coverage OF THIS EVENT spiked.
    """
    seen: dict = {}

    def fake_get(url, params, timeout):
        seen.update(params)
        return httpx.Response(200, text=_CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    narrative.fetch_daily_volume(
        "JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None, topic="earthquake"
    )
    assert "sourcecountry:japan" in seen["query"]
    assert "earthquake" in seen["query"]


def test_topic_synonyms_are_expanded(monkeypatch):
    """Outlets write "quake" and "tremor" as often as "earthquake"."""
    seen: dict = {}

    def fake_get(url, params, timeout):
        seen.update(params)
        return httpx.Response(200, text=_CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    narrative.fetch_daily_volume(
        "JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None, topic="earthquake"
    )
    assert " OR " in seen["query"]
    assert "quake" in seen["query"]


def test_no_topic_keeps_the_country_wide_query(monkeypatch):
    seen: dict = {}

    def fake_get(url, params, timeout):
        seen.update(params)
        return httpx.Response(200, text=_CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)
    assert seen["query"] == "sourcecountry:japan"


def test_topic_changes_the_cache_key(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params, timeout):
        calls["n"] += 1
        return httpx.Response(200, text=_CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=tmp_path)
    narrative.fetch_daily_volume(
        "JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=tmp_path, topic="earthquake"
    )
    assert calls["n"] == 2


def test_unfamiliar_prose_at_http_200_is_reported_as_what_gdelt_said(monkeypatch):
    """Observed live: a short free-text query earns prose, not a CSV (#557).

    The old marker list did not carry this phrase, so it parsed as a valid but
    empty series and surfaced as "no daily rows parsed" — which points the
    reader at the window when the query was the problem.
    """

    def fake_get(url, params, timeout):
        return httpx.Response(200, text="The specified phrase is too short.")

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    with pytest.raises(narrative.NarrativeUnavailableError) as excinfo:
        narrative.fetch_daily_volume("PE", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)
    assert "too short" in str(excinfo.value)


def test_a_real_csv_header_is_not_mistaken_for_prose(monkeypatch):
    def fake_get(url, params, timeout):
        return httpx.Response(200, text="﻿" + _CSV)

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    counts = narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)
    assert counts[date(2026, 6, 1)] == 1317


def test_an_empty_body_is_reported_as_an_empty_body(monkeypatch):
    def fake_get(url, params, timeout):
        return httpx.Response(200, text="")

    monkeypatch.setattr(narrative.httpx, "get", fake_get)
    with pytest.raises(narrative.NarrativeUnavailableError):
        narrative.fetch_daily_volume("JP", date(2026, 6, 1), date(2026, 6, 3), cache_dir=None)
