"""The ask stream keeps speaking while the model reads the prompt (#997).

A streamed answer sends nothing until the model has read its context. On a
machine with a GPU that is about a second; on a small board it was measured at
around a hundred, and the console's own guard hangs up after forty-five seconds
of silence. The stream it cancelled was then reported to the reader as the brain
being offline — the same sentence the API uses for a model that is not
installed — so every check the message invites is server-side, and all of them
passed. Four rounds of diagnosis went into a server that was working.

These are about the silence, not the answer.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from app.api import _HEARTBEAT, _kept_alive


def _slow(gap: float, *chunks: str) -> Iterator[str]:
    """Chunks that arrive `gap` seconds apart, like a model that is thinking."""
    for chunk in chunks:
        time.sleep(gap)
        yield chunk


class TestTheSilenceIsFilled:
    #: The failure this exists for: nothing sent for longer than the client will
    #: wait, on a generation that is working perfectly.
    def test_a_long_quiet_start_still_sends_something(self) -> None:
        out = list(_kept_alive(_slow(0.05, "answer"), every=0.01))
        assert _HEARTBEAT in out

    def test_the_answer_still_arrives_in_order(self) -> None:
        out = list(_kept_alive(_slow(0.02, "one", "two", "three"), every=0.005))
        assert [c for c in out if c is not _HEARTBEAT] == ["one", "two", "three"]

    #: Once tokens are flowing they arrive faster than the interval, so a
    #: healthy answer never carries one. A heartbeat between every token would
    #: be noise in the transcript and bytes on the wire for nothing.
    def test_a_fast_stream_needs_no_heartbeat(self) -> None:
        out = list(_kept_alive(iter(["a", "b", "c"]), every=5))
        assert out == ["a", "b", "c"]

    def test_an_empty_stream_ends_rather_than_beating_forever(self) -> None:
        assert list(_kept_alive(iter([]), every=5)) == []


class TestFailureStillReachesTheCaller:
    #: The handler above turns an exception into a typed answer. If it stops
    #: arriving, that answer is never chosen and the reader gets a stream that
    #: simply stops.
    def test_an_error_is_raised_not_swallowed(self) -> None:
        def breaks() -> Iterator[str]:
            yield "partial"
            raise RuntimeError("ollama went away")

        with pytest.raises(RuntimeError, match="ollama went away"):
            list(_kept_alive(breaks(), every=5))

    def test_what_arrived_before_the_error_is_yielded_first(self) -> None:
        def breaks() -> Iterator[str]:
            yield "partial"
            raise RuntimeError("boom")

        seen: list[str] = []
        with pytest.raises(RuntimeError):
            for chunk in _kept_alive(breaks(), every=5):
                seen.append(chunk)
        assert seen == ["partial"]


class TestTheHeartbeatItself:
    #: An SSE comment: ignored as a message by every client, counted as traffic
    #: by every client. Anything else would be an event readers must learn to
    #: skip, and one that forgot to would print it into the answer.
    def test_it_is_a_comment_and_not_an_event(self) -> None:
        assert _HEARTBEAT.startswith(":")
        assert "event:" not in _HEARTBEAT

    def test_it_ends_the_frame_so_a_client_flushes_it(self) -> None:
        assert _HEARTBEAT.endswith("\n\n")
