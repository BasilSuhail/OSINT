"""A slow model and an absent one are different events (#997).

Measured on a Raspberry Pi: the 4b Q&A model took over three minutes to answer
"Say hello" against a 120 s timeout, because `keep_alive="0"` evicted it after
every question and each one reloaded 3.4 GB from an SD card before generating a
token. The console reported that as "The brain is offline right now."

Every check that wording invites — is Ollama running, is it listening, can the
container reach it — passes when this is what happened. It sent two separate
investigations down the wrong road before anyone timed a generate call.
"""

from __future__ import annotations

from pathlib import Path

from app.brain import qa
from app.settings import settings

ROOT = Path(__file__).resolve().parents[1]
API = (ROOT / "app" / "api.py").read_text()
CLIENT = (ROOT / "app" / "brain" / "client.py").read_text()


class TestTheAnswersAreDistinct:
    def test_slow_is_its_own_answer(self) -> None:
        assert qa.BRAIN_SLOW_ANSWER != qa.BRAIN_OFFLINE_ANSWER
        assert qa.BRAIN_SLOW_ANSWER in qa.OPERATIONAL_ANSWERS

    #: Operational answers are exempt from claim checks and never treated as
    #: model output, so a new one has to be in that tuple or it would be scored
    #: as content.
    def test_it_is_registered_as_operational(self) -> None:
        assert all(answer in qa.OPERATIONAL_ANSWERS for answer in (qa.BRAIN_SLOW_ANSWER,))

    #: The message has to say what to do, because the reader cannot see which of
    #: the two knobs applies to their machine.
    def test_it_names_both_ways_out(self) -> None:
        assert "BRAIN_TIMEOUT_S" in qa.BRAIN_SLOW_ANSWER
        assert "QA_MODEL" in qa.BRAIN_SLOW_ANSWER


class TestEveryAskPathSeparatesThem:
    #: Three places answer a question: the deep read, the plain ask, and the
    #: streaming ask. A timeout caught in two of three would be worse than none,
    #: because the message would depend on which endpoint the console used.
    def test_all_three_catch_a_timeout_before_the_broad_except(self) -> None:
        assert API.count("except httpx.TimeoutException:") == 3
        assert API.count("BRAIN_SLOW_ANSWER") == 3

    def test_a_timeout_handler_precedes_its_general_one(self) -> None:
        for block in API.split("except httpx.TimeoutException:")[1:]:
            #: The general handler must come after, or it would swallow timeouts.
            assert "except Exception:" in block


class TestTheKnobs:
    def test_the_timeout_is_a_setting_not_a_constant(self) -> None:
        assert "_TIMEOUT_S: float = 120.0" not in CLIENT
        assert "settings.brain_timeout_s" in CLIENT
        assert isinstance(settings.brain_timeout_s, float)

    #: Five call sites — generate_json, generate_text, embed, unload and the
    #: stream. One left on a constant would ignore the setting silently.
    def test_every_call_uses_it(self) -> None:
        assert CLIENT.count("timeout=_timeout()") == 5

    #: "0" keeps the behaviour every existing install already has: evict at once,
    #: never hold two models. Holding is opt-in, because the cost is memory.
    def test_holding_the_model_is_opt_in(self) -> None:
        assert settings.qa_keep_alive == "0"

    def test_no_ask_path_hard_codes_eviction(self) -> None:
        assert 'keep_alive="0"' not in API
        assert API.count("keep_alive=settings.qa_keep_alive") == 8
