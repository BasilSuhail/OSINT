"""Pacing that survives the process, so a resumed run does not re-trip GDELT (#559)."""

import json

import pytest

from app.backtest import pacing


class FakeClock:
    """Wall clock under test control; sleeping moves it forward."""

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / "pacing.json"


def _pacer(state_path, clock, **kw):
    return pacing.Pacer(state_path=state_path, time_fn=clock.time, sleep_fn=clock.sleep, **kw)


class TestSpacing:
    def test_the_first_call_of_a_fresh_state_does_not_wait(self, state_path, clock):
        _pacer(state_path, clock).wait_turn()
        assert clock.slept == []

    def test_a_second_call_waits_out_the_interval(self, state_path, clock):
        pacer = _pacer(state_path, clock, min_interval_s=5.0)
        pacer.wait_turn()
        pacer.record_call()
        pacer.wait_turn()
        assert clock.slept == [5.0]

    def test_a_call_after_the_interval_has_passed_does_not_wait(self, state_path, clock):
        pacer = _pacer(state_path, clock, min_interval_s=5.0)
        pacer.record_call()
        clock.now += 9.0
        pacer.wait_turn()
        assert clock.slept == []

    def test_a_new_pacer_resumes_the_previous_one_s_spacing(self, state_path, clock):
        # The bug this exists to fix: pacing state was a module global on a
        # monotonic clock, so every fresh process fired immediately however
        # recently the last run had called.
        _pacer(state_path, clock, min_interval_s=5.0).record_call()
        clock.now += 1.0

        _pacer(state_path, clock, min_interval_s=5.0).wait_turn()
        assert clock.slept == [4.0]

    def test_state_is_written_where_it_was_asked_for(self, state_path, clock):
        _pacer(state_path, clock).record_call()
        assert json.loads(state_path.read_text())["last_call_at"] == clock.now


class TestCooldown:
    def test_a_refusal_pushes_every_later_call_past_the_cooldown(self, state_path, clock):
        pacer = _pacer(state_path, clock, cooldown_s=60.0)
        pacer.record_refusal()
        pacer.wait_turn()
        assert clock.slept == [60.0]

    def test_the_cooldown_outlives_the_process(self, state_path, clock):
        _pacer(state_path, clock, cooldown_s=60.0).record_refusal()
        clock.now += 10.0
        _pacer(state_path, clock, cooldown_s=60.0).wait_turn()
        assert clock.slept == [50.0]

    def test_repeated_refusals_escalate(self, state_path, clock):
        # A limiter that is still refusing after one cooldown is telling the
        # caller the cooldown was too short.
        pacer = _pacer(state_path, clock, cooldown_s=60.0)
        pacer.record_refusal()
        first = pacer.cooldown_remaining()
        clock.now += first
        pacer.record_refusal()
        assert pacer.cooldown_remaining() > first

    def test_a_retry_after_header_is_honoured_over_the_default(self, state_path, clock):
        pacer = _pacer(state_path, clock, cooldown_s=60.0)
        pacer.record_refusal(retry_after_s=900.0)
        assert pacer.cooldown_remaining() == 900.0

    def test_a_retry_after_shorter_than_the_default_does_not_shorten_it(self, state_path, clock):
        # GDELT's own number is a floor, not a promise; the observed penalty
        # outlasts what it advertises.
        pacer = _pacer(state_path, clock, cooldown_s=60.0)
        pacer.record_refusal(retry_after_s=1.0)
        assert pacer.cooldown_remaining() == 60.0

    def test_a_success_clears_the_escalation(self, state_path, clock):
        pacer = _pacer(state_path, clock, cooldown_s=60.0)
        pacer.record_refusal()
        pacer.record_refusal()
        clock.now += pacer.cooldown_remaining()
        pacer.record_success()
        pacer.record_refusal()
        assert pacer.cooldown_remaining() == 60.0


class TestRobustness:
    def test_an_unreadable_state_file_is_treated_as_no_state(self, state_path, clock):
        state_path.write_text("{ this is not json")
        _pacer(state_path, clock).wait_turn()
        assert clock.slept == []

    def test_a_missing_parent_directory_is_created(self, tmp_path, clock):
        path = tmp_path / "nested" / "deeper" / "pacing.json"
        _pacer(path, clock).record_call()
        assert path.exists()

    def test_a_state_file_from_the_future_does_not_wait_forever(self, state_path, clock):
        # A clock change should not strand the caller for hours.
        state_path.write_text(json.dumps({"last_call_at": clock.now + 10_000.0}))
        pacer = _pacer(state_path, clock, min_interval_s=5.0)
        pacer.wait_turn()
        assert clock.slept == [5.0]
