"""Rate-limit pacing that survives the process (#559).

GDELT publishes one request every five seconds, but the penalty for exceeding
it is a rolling refusal that outlasts the burst by minutes. The previous pacer
kept its state in a module global on a `time.monotonic()` clock, which meant two
things: a fresh process opened with an immediate call however recently the last
run had finished, and a 429 never widened the spacing that provoked it. A
resumable backtest therefore re-tripped the limiter on every resume.

State lives on disk next to the response cache, on the wall clock, so a new
process continues where the last one stopped:

- `last_call_at` — when the most recent request went out.
- `cooldown_until` — when refusals allow calling again.
- `refusals` — consecutive refusals, so each one waits longer than the last.

Time and sleep are injected so the escalation can be tested without spending
the wait.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

#: GDELT's published floor.
DEFAULT_MIN_INTERVAL_S = 5.0

#: What one refusal buys. The observed penalty outlasts the burst by minutes,
#: so this is far longer than the published interval on purpose.
DEFAULT_COOLDOWN_S = 60.0

#: Ceiling on escalation — beyond this the caller should stop, not sleep.
MAX_COOLDOWN_S = 1800.0


class Pacer:
    """Paces outbound calls to one rate-limited host, persistently."""

    def __init__(
        self,
        *,
        state_path: Path,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        time_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.state_path = Path(state_path)
        self.min_interval_s = min_interval_s
        self.cooldown_s = cooldown_s
        self._time = time_fn
        self._sleep = sleep_fn

    def _read(self) -> dict[str, float]:
        """Persisted state, or empty when there is none worth trusting.

        A corrupt file is not worth failing a run over — the cost of treating it
        as absent is one unpaced call, which is what the old code did always.
        """
        try:
            loaded = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _write(self, state: dict[str, float]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state))

    def cooldown_remaining(self) -> float:
        """Seconds until refusals allow calling again."""
        remaining = float(self._read().get("cooldown_until", 0.0)) - self._time()
        return max(0.0, remaining)

    def wait_turn(self) -> None:
        """Block until this caller may make its next request."""
        state = self._read()
        now = self._time()

        since_last = now - float(state.get("last_call_at", 0.0))
        # A state file from the future — a clock change, a restored backup —
        # would otherwise strand the caller. Waiting one interval is enough.
        interval_wait = (
            self.min_interval_s if since_last < 0 else max(0.0, self.min_interval_s - since_last)
        )
        cooldown_wait = max(0.0, float(state.get("cooldown_until", 0.0)) - now)

        wait = max(interval_wait, cooldown_wait)
        if wait > 0:
            self._sleep(wait)

    def record_call(self) -> None:
        """Note that a request just went out."""
        state = self._read()
        state["last_call_at"] = self._time()
        self._write(state)

    def record_success(self) -> None:
        """Clear the refusal escalation — the host is answering again."""
        state = self._read()
        state["refusals"] = 0
        state["cooldown_until"] = 0.0
        self._write(state)

    def record_refusal(self, *, retry_after_s: float | None = None) -> None:
        """Note a rate-limit refusal and widen the wait before the next call.

        `retry_after_s` raises the cooldown but never lowers it: the host's own
        number is a floor, and the penalty observed here outlasts what GDELT
        advertises.
        """
        state = self._read()
        refusals = int(state.get("refusals", 0)) + 1
        cooldown = min(self.cooldown_s * (2 ** (refusals - 1)), MAX_COOLDOWN_S)
        if retry_after_s is not None:
            cooldown = max(cooldown, retry_after_s)
        state["refusals"] = refusals
        state["cooldown_until"] = self._time() + cooldown
        self._write(state)
