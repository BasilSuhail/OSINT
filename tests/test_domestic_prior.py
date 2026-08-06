"""Which feeds may stamp their own country on a story that names nowhere.

`domestic_prior` and `desk_country` both assign a country with no evidence
from the text, and they are deliberately separate keys. A desk is structural
— the feed URL is that country's section, so every story in it is about that
country by construction. A domestic prior is statistical: a national
masthead's general feed, measured to be mostly domestic.

Both are dangerous for the same reason, which is #166: applied to a feed
that republishes world news they stamp that flag on everything. These tests
pin the sets, so adding a feed means measuring it first.
"""

from __future__ import annotations

from app.enrichment.geo import resolve_geo
from app.sources.rss_registry import (
    desk_country_map,
    domestic_prior_map,
    outlet_country_map,
)

#: Measured at 80% or better domestic across a hand-labelled sample of at
#: least twelve of that feed's own uncountried rows. See
#: `domestic_prior_map`'s docstring for the counts.
EARNED = {
    "rss-the-hindu": "IN",
    "rss-tribune-pk": "PK",
    "rss-sabc-news": "ZA",
    "rss-yonhap-en": "KR",
}

#: Measured and refused. Named individually because "it did not qualify" is
#: a finding worth keeping: a later reader looking at Geo English's Pakistani
#: masthead would otherwise add it on sight.
REFUSED = {"rss-geo-english", "rss-times-of-india", "rss-daily-sabah", "rss-antara-en"}


def test_only_measured_feeds_carry_a_domestic_prior() -> None:
    assert domestic_prior_map() == EARNED


def test_the_refused_feeds_stay_refused() -> None:
    """Geo English is Pakistani and its uncountried tail is showbusiness —
    Princess Eugenie, ASAP Rocky. A prior would stamp PK on 252 rows a week
    that are not about Pakistan."""
    assert REFUSED.isdisjoint(domestic_prior_map())


def test_the_two_priors_stay_separate() -> None:
    """A structural guarantee and an 80%-plus measurement are different
    claims. Merging the keys would hide which one a stored row rests on."""
    assert set(domestic_prior_map()).isdisjoint(desk_country_map())


def test_every_domestic_prior_is_a_real_outlet_and_valid_iso2() -> None:
    outlets = outlet_country_map()
    for source, iso in domestic_prior_map().items():
        assert source in outlets, source
        assert len(iso) == 2 and iso.isupper(), f"{source} has a malformed domestic_prior"


def test_the_prior_never_overrides_the_text() -> None:
    """The whole safety of this mechanism is that it runs last. A story that
    says where it is keeps that answer, whatever masthead carried it."""
    assert resolve_geo("Ukraine says Russian strike hit Kharkiv", domestic_prior="IN").iso != "IN"


def test_the_prior_fills_a_story_that_names_nowhere() -> None:
    verdict = resolve_geo(
        "Cab driver held for issuing forged allotment orders", domestic_prior="IN"
    )
    assert verdict.iso == "IN"
    assert verdict.basis == "domestic"


def test_a_desk_outranks_a_prior_if_a_feed_ever_carries_both() -> None:
    verdict = resolve_geo("Minister opens new session", desk_country="GB", domestic_prior="IN")
    assert verdict.iso == "GB"
    assert verdict.basis == "desk"


def test_a_prior_row_gets_no_coordinates() -> None:
    """Knowing the country is not knowing the place. These rows are
    clickable under their country and must not become dots — the 'local'
    scope rule from #719 already requires coordinates for that."""
    verdict = resolve_geo("Minister opens new session", domestic_prior="ZA")
    assert verdict.iso == "ZA"
    assert verdict.lat is None and verdict.lon is None
