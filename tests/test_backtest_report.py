"""The report is the thesis artifact, so it must be self-describing (#524)."""

from __future__ import annotations

from app.backtest.metrics import EventLead, GateMetrics
from app.backtest.report import render_report

_METRICS = GateMetrics(
    median_lead=-27.0,
    pct_events_leading=0.125,
    n_events=8,
    false_positive_rate=0.64,
    verdict="FAIL",
)
_LEADS = [EventLead(event_id="ve-x", lead_days=-58), EventLead(event_id="id-y", lead_days=4)]


def _render(**kwargs):
    return render_report(
        _METRICS, _LEADS, registry_hash="d78f59d1aaaa", method_version="div.v1", **kwargs
    )


def test_records_how_many_events_were_measurable():
    """A median over 2 of 22 must not read like a median over 22.

    The first real run reported "Events: 8" while only two of those eight
    produced a lead value at all, and the headline median was the midpoint of
    those two numbers.
    """
    out = _render(registry_size=22, unscorable=[("ph-a", "HTTP 429")])
    assert "22" in out
    assert "2" in out


def test_lists_unscorable_events_with_their_reason():
    """Excluded events must be visible, or a fetch failure looks like a result."""
    out = _render(registry_size=22, unscorable=[("ph-a", "HTTP 429"), ("jp-b", "no daily rows")])
    assert "ph-a" in out and "HTTP 429" in out
    assert "jp-b" in out and "no daily rows" in out


def test_states_the_pass_bar_it_was_judged_against():
    out = _render(registry_size=22, unscorable=[])
    assert "median" in out.lower()
    assert "50%" in out or "half" in out.lower()


def test_warns_when_the_measured_sample_is_too_small_to_mean_anything():
    out = _render(registry_size=22, unscorable=[])
    assert "caution" in out.lower() or "too small" in out.lower()


def test_no_warning_when_the_sample_is_adequate():
    metrics = GateMetrics(
        median_lead=3.0,
        pct_events_leading=0.6,
        n_events=20,
        false_positive_rate=0.2,
        verdict="PASS",
    )
    leads = [EventLead(event_id=f"e{i}", lead_days=3) for i in range(20)]
    out = render_report(
        metrics,
        leads,
        registry_hash="abc",
        method_version="div.v1",
        registry_size=22,
        unscorable=[],
    )
    assert "too small" not in out.lower()


def test_reports_the_chance_rate_beside_the_observed_one():
    """A pass rate with no reference point cannot be interpreted (#538)."""
    out = render_report(
        _METRICS,
        _LEADS,
        registry_hash="abc",
        method_version="div.v3",
        registry_size=22,
        unscorable=[],
        null_rate=0.30,
    )
    assert "30%" in out
    assert "Chance rate" in out


def test_shows_the_gap_between_observed_and_chance():
    out = render_report(
        _METRICS,
        _LEADS,
        registry_hash="abc",
        method_version="div.v3",
        registry_size=22,
        unscorable=[],
        null_rate=0.30,
    )
    # observed 12.5% against chance 30% is a NEGATIVE gap and must read as one.
    assert "-18%" in out or "-17%" in out


def test_omits_the_chance_line_when_it_was_not_computed():
    out = render_report(
        _METRICS, _LEADS, registry_hash="abc", method_version="div.v3", registry_size=22
    )
    assert "Chance rate" not in out
