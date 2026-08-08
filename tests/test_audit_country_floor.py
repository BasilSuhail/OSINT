"""An alarm that fires 46 times a night is not an alarm (#827).

The nightly audit produced 57 findings. Forty-six were `country_coverage`,
forty-five of those on news feeds, and they were the check being wrong rather
than the data.

`MIN_COVERAGE` is 0.99. Measured over seven days across the 41 news feeds
carrying at least thirty rows:

```
min     0.375   one Kenyan feed
p10     0.601
median  0.764
max     1.000
```

No feed can reach 0.99, and none should. #717 measured that roughly 41% of
news genuinely names no country and established that such a row must stay
null rather than be assigned one it cannot support — assigning it is the #166
centroid blob. So the check demanded the exact behaviour the resolver was
built to refuse, and buried the handful of findings that meant something.

A floor is not a mute button. Below it the check still fails, and the tests
here hold that line: a feed that stops resolving countries must still be
caught.
"""

from __future__ import annotations

from app.audit.checks import MIN_COVERAGE, check_country_coverage
from app.audit.expectations import Expectation, for_source
from app.audit.stats import SourceStats


def _stats(source: str, *, rows: int, with_country: int) -> SourceStats:
    return SourceStats(
        source=source,
        rows=rows,
        severity_present=rows,
        severity_distinct=2,
        severity_top_share=0.5,
        severity_std=0.1,
        country_present=with_country,
        earliest=None,
        latest=None,
        composite_eligible=0,
    )


def _expect(source: str) -> Expectation:
    expectation = for_source(source)
    assert expectation is not None, source
    return expectation


class TestTheFloorIsHonoured:
    def test_a_news_feed_at_the_measured_median_is_not_a_finding(self) -> None:
        """0.764 is the median across 41 feeds. Calling the median a defect
        makes the word meaningless."""
        stats = _stats("rss-bbc-uk", rows=1000, with_country=764)
        assert check_country_coverage(stats, _expect("rss-bbc-uk")) is None

    def test_the_worst_measured_feed_is_still_a_finding(self) -> None:
        """One feed sat at 0.375 while its peers sat at 0.76, and that gap is
        the thing worth reporting."""
        stats = _stats("rss-capital-fm-kenya", rows=1000, with_country=375)
        finding = check_country_coverage(stats, _expect("rss-capital-fm-kenya"))
        assert finding is not None
        assert finding.check == "country_coverage"

    def test_a_feed_that_stops_resolving_entirely_is_caught(self) -> None:
        """The regression this must never trade away: a resolver failure looks
        exactly like this and has to be loud."""
        finding = check_country_coverage(
            _stats("rss-bbc-uk", rows=1000, with_country=0), _expect("rss-bbc-uk")
        )
        assert finding is not None
        assert "0" in finding.detail


class TestWhatIsUnchanged:
    def test_a_source_with_no_country_of_its_own_is_never_asked(self) -> None:
        """A malware URL and a prediction market have no country. Asking them
        for one produces a finding nobody can act on."""
        for source in ("abuse-ch-urlhaus", "polymarket"):
            assert _expect(source).country in {"none", "optional"}, source

    def test_the_strict_default_still_applies_to_sources_without_a_floor(self) -> None:
        """The floor is per source and declared. A source that never asked for
        one keeps the strict bar."""
        strict = Expectation(severity="none", country="required", feeds_composite=False)
        assert strict.country_coverage_floor is None
        assert MIN_COVERAGE == 0.99
        assert check_country_coverage(_stats("x", rows=100, with_country=98), strict) is not None


class TestTheDeclarationIsMeasured:
    def test_the_news_floor_sits_below_every_healthy_feed_and_above_the_worst(self) -> None:
        """Set from the measured spread rather than chosen: p10 is 0.601 and
        the worst feed is 0.375, so the bar has to sit between them or it is
        either useless or a rubber stamp."""
        floor = _expect("rss-bbc-uk").country_coverage_floor
        assert floor is not None
        assert 0.375 < floor < 0.601

    def test_the_declaration_says_why(self) -> None:
        note = _expect("rss-bbc-uk").note
        assert "717" in note or "countryless" in note.lower()

    def test_gdelt_keeps_a_bar_it_can_actually_clear(self) -> None:
        """Measured at 0.894 over seven days. A bar above that reports the
        machine coder as broken every night for doing what it does."""
        expectation = _expect("gdelt")
        if expectation.country == "required":
            floor = expectation.country_coverage_floor
            assert floor is not None and floor <= 0.85
