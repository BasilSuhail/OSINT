"""A GDELT row's headline comes from its article, or it does not come (#788).

The rejection cases carry the weight. A CAMEO code word in the headline slot
is obviously wrong; a consent wall's "Just a moment…" sitting there looks
right and is worse.
"""

from __future__ import annotations

import httpx
import pytest

from app.enrichment.article_title import (
    MAX_BYTES,
    clean_title,
    fetch_title,
    parse_title,
)


class TestParseTitle:
    def test_og_title_wins_over_document_title(self) -> None:
        """og:title is the headline the outlet chose for sharing; <title>
        usually carries the site's branding as well."""
        body = (
            '<html><head><meta property="og:title" '
            'content="Two villages evacuated as wildfire jumps the ridge">'
            "<title>Evacuation latest | Castanet</title></head>"
        )
        assert parse_title(body) == "Two villages evacuated as wildfire jumps the ridge"

    def test_document_title_is_used_when_there_is_no_og(self) -> None:
        body = "<head><title>Pakistan suicide bombing kills eleven</title></head>"
        assert parse_title(body) == "Pakistan suicide bombing kills eleven"

    def test_twitter_title_is_accepted(self) -> None:
        body = '<head><meta name="twitter:title" content="Missing boy sparks huge rescue"></head>'
        assert parse_title(body) == "Missing boy sparks huge rescue"

    def test_entities_are_decoded(self) -> None:
        body = "<head><title>Palace gives nod to Prince Edward&#39;s key role</title></head>"
        assert parse_title(body) == "Palace gives nod to Prince Edward's key role"

    def test_broken_markup_still_yields_what_was_read(self) -> None:
        body = "<head><title>Evacuation alert expanded for Bradley Creek</title><<<>"
        assert parse_title(body) == "Evacuation alert expanded for Bradley Creek"

    def test_a_page_with_no_title_is_a_miss(self) -> None:
        assert parse_title("<html><body><p>no head here</p></body></html>") is None


class TestCleanTitle:
    def test_site_branding_is_stripped(self) -> None:
        assert (
            clean_title("Kohberger wants his guilty plea reversed - Fox 11")
            == "Kohberger wants his guilty plea reversed"
        )

    @pytest.mark.parametrize(
        "raw",
        ["Just a moment...", "Are you a robot?", "Access Denied", "404 Not Found", "News"],
    )
    def test_a_wall_is_not_a_headline(self, raw: str) -> None:
        """These return 200 with a title. Printed on the map they would read
        as real headlines, which is worse than the code word they replace."""
        assert clean_title(raw) is None

    def test_branding_is_kept_when_stripping_would_gut_the_headline(self) -> None:
        """ "Fire - BBC" must not become "Fire": what is left has to still be
        a sentence, or the strip has destroyed the thing it was tidying."""
        assert clean_title("Fire - BBC News") == "Fire - BBC News"

    def test_a_whole_paragraph_is_not_a_headline(self) -> None:
        assert clean_title("word " * 100) is None

    def test_whitespace_is_collapsed(self) -> None:
        assert (
            clean_title("  Oil prices\n   fall on Hormuz hopes ")
            == "Oil prices fall on Hormuz hopes"
        )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestFetchTitle:
    def test_a_good_page_gives_its_headline(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text="<head><title>Evacuation alert expanded for Bradley Creek</title></head>",
            )

        with _client(handler) as client:
            result = fetch_title("https://example.com/a", client=client)
        assert result.title == "Evacuation alert expanded for Bradley Creek"
        assert result.reason == "ok"

    def test_a_gone_article_is_not_worth_asking_again(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        with _client(handler) as client:
            result = fetch_title("https://example.com/gone", client=client)
        assert result.title is None
        assert result.retryable is False

    def test_a_server_having_a_moment_is_worth_asking_again(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        with _client(handler) as client:
            result = fetch_title("https://example.com/later", client=client)
        assert result.retryable is True

    def test_rate_limiting_is_worth_asking_again(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        with _client(handler) as client:
            assert fetch_title("https://example.com/slow", client=client).retryable is True

    def test_a_timeout_is_worth_asking_again(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("too slow", request=request)

        with _client(handler) as client:
            result = fetch_title("https://example.com/slow", client=client)
        assert result.reason == "timeout"
        assert result.retryable is True

    def test_a_pdf_is_not_read(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "application/pdf"}, text="%PDF")

        with _client(handler) as client:
            result = fetch_title("https://example.com/a.pdf", client=client)
        assert result.reason == "not-html"
        assert result.retryable is False

    def test_a_timestamp_where_a_url_belongs_is_never_fetched(self) -> None:
        """Every row stored before #733 has a 14-digit DATEADDED in
        `source_url`. Those must not become outbound requests."""

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("must not be fetched")

        with _client(handler) as client:
            result = fetch_title("20260803094500", client=client)
        assert result.reason == "not-a-url"
        assert result.retryable is False

    def test_a_firehose_is_cut_off(self) -> None:
        """A server that streams without end must not fill the box's memory."""
        seen: dict[str, int] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            body = "<head><title>Real headline about the ridge fire</title>" + "x" * (MAX_BYTES * 4)
            seen["len"] = len(body)
            return httpx.Response(200, headers={"content-type": "text/html"}, text=body)

        with _client(handler) as client:
            result = fetch_title("https://example.com/huge", client=client)
        assert result.title == "Real headline about the ridge fire"
        assert seen["len"] > MAX_BYTES
