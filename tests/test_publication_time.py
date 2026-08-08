"""A story is not published in the future (#766).

Measured on the live feed while writing this. The Jerusalem Post front page
labels its timestamps `GMT` and stamps them in Israel local time, so eight of
twelve items were ahead of the clock:

```
now utc: 2026-08-08T14:06Z
'Sat, 08 Aug 2026 16:25:19 GMT'   ahead 139 min
'Sat, 08 Aug 2026 16:17:40 GMT'   ahead 131 min
'Sat, 08 Aug 2026 15:43:05 GMT'   ahead  97 min
'Sat, 08 Aug 2026 13:57:53 GMT'   behind   8 min
```

Nothing exceeded 180 minutes ahead, which is the signature of a fixed
three-hour offset rather than a drifting clock: subtract three hours and every
item lands in the past, newest at 41 minutes ago, with the spacing between
items unchanged.

Three of those rows are in the live table now, dated up to 115 minutes ahead.
They sort above genuine news and they distort every freshness measure that
compares a row against the clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

from app.ingest import publication_time as pt
from app.models import Event

NOW = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)


def _event(minutes_ahead: float, *, source: str = "rss-jpost-world", n: int = 0) -> Event:
    return Event(
        source=source,
        source_event_id=f"e{n}-{minutes_ahead}",
        occurred_at=NOW + timedelta(minutes=minutes_ahead),
        fetched_at=NOW,
        category="geopolitical",
        payload={"title": f"story {n}"},
    )


def _minutes_ahead(event: Event) -> float:
    return (event.occurred_at - NOW).total_seconds() / 60


class TestSystematicOffset:
    """A feed publishing local time labelled UTC is provable from one batch."""

    def _batch(self) -> list[Event]:
        # The live sample: eight ahead, four behind, nothing beyond three hours.
        ahead = [139, 138, 131, 127, 103, 97, 57, 20]
        behind = [-8, -251, -1361, -16920]
        return [_event(m, n=i) for i, m in enumerate(ahead + behind)]

    def test_the_whole_batch_shifts_by_whole_hours(self) -> None:
        fixed, report = pt.normalize(self._batch(), now=NOW)
        assert report.offset_hours == 3
        assert all(_minutes_ahead(e) <= 0 for e in fixed), "a row is still in the future"

    def test_the_shift_preserves_the_order_and_the_gaps(self) -> None:
        """An offset correction is a translation. Clamping would collapse the
        newest items onto one timestamp and lose which came first."""
        before = self._batch()
        after, _ = pt.normalize(before, now=NOW)
        gaps_before = [(a.occurred_at - b.occurred_at).total_seconds() for a, b in pairwise(before)]
        gaps_after = [(a.occurred_at - b.occurred_at).total_seconds() for a, b in pairwise(after)]
        assert gaps_before == gaps_after

    def test_the_correction_is_recorded_on_every_row_it_touched(self) -> None:
        fixed, _ = pt.normalize(self._batch(), now=NOW)
        adjusted = [e for e in fixed if e.payload.get("time_adjustment")]
        assert len(adjusted) == 12, "the offset applies to the batch, not only the future rows"
        note = adjusted[0].payload["time_adjustment"]
        assert note["reason"] == "feed-offset"
        assert note["offset_hours"] == 3
        assert note["raw"].startswith("2026-08-08")


class TestOneOffFutureRow:
    """A single future row is a defect in that row, not in the feed's clock."""

    def _batch(self) -> list[Event]:
        return [_event(45, n=0)] + [_event(-m, n=i) for i, m in enumerate([10, 60, 200, 900], 1)]

    def test_only_the_offending_row_moves(self) -> None:
        fixed, report = pt.normalize(self._batch(), now=NOW)
        assert report.offset_hours is None
        assert _minutes_ahead(fixed[0]) == 0
        assert [_minutes_ahead(e) for e in fixed[1:]] == [-10, -60, -200, -900]

    def test_the_clamp_says_what_it_did(self) -> None:
        fixed, _ = pt.normalize(self._batch(), now=NOW)
        note = fixed[0].payload["time_adjustment"]
        assert note["reason"] == "future-clamped"
        assert note["raw"] == (NOW + timedelta(minutes=45)).isoformat()
        assert not fixed[1].payload.get("time_adjustment")


class TestWhatIsLeftAlone:
    def test_a_batch_already_in_the_past_is_untouched(self) -> None:
        batch = [_event(-m, n=i) for i, m in enumerate([1, 30, 400])]
        fixed, report = pt.normalize(batch, now=NOW)
        assert report.offset_hours is None
        assert report.clamped == 0
        assert all(not e.payload.get("time_adjustment") for e in fixed)

    def test_seconds_of_skew_are_not_worth_a_note(self) -> None:
        """Feeds disagree with our clock by a few seconds constantly. Marking
        that as an adjustment would bury the real defects in noise."""
        fixed, report = pt.normalize([_event(0.5, n=0)], now=NOW)
        assert report.clamped == 0
        assert not fixed[0].payload.get("time_adjustment")

    def test_an_event_without_a_date_is_passed_through(self) -> None:
        batch = [_event(-5, n=0)]
        fixed, _ = pt.normalize(batch, now=NOW)
        assert fixed[0].occurred_at == batch[0].occurred_at


class TestReport:
    def test_it_summarizes_what_happened(self) -> None:
        _, report = pt.normalize(
            [_event(139, n=0), _event(131, n=1), _event(97, n=2), _event(-8, n=3)], now=NOW
        )
        line = report.summary()
        assert line is not None
        assert "3h" in line
        assert "rss-jpost-world" in line

    def test_a_clean_batch_says_nothing(self) -> None:
        _, report = pt.normalize([_event(-5, n=0)], now=NOW)
        assert report.summary() is None
