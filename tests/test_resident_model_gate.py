"""Memory a model already occupies is not memory it still needs (#1016).

`make news` on a Raspberry Pi:

    gist     the summary line on each story card
    narrate  the written situation summary
             skipped — low RAM: 3057MB free < 3500MB floor

Nothing was short of memory. The gist stage had loaded the 3b and was holding it
warm, so the 3.4 GB it occupied counted against the floor for the next stage,
which then refused to use the model sitting loaded in front of it.

The floors ask whether there is room to *load* a model. Once one is loaded that
is the wrong question — and on a small board it is the usual case, because one
model does every job and the first stage to run makes the rest look unaffordable.
"""

from __future__ import annotations

from app.brain import gate


def _local(monkeypatch, *, free_mb: int, resident: bool) -> None:
    monkeypatch.setattr(gate.settings, "ollama_url", "http://localhost:11434")
    monkeypatch.setattr(gate, "ram_free_mb", lambda: free_mb)
    monkeypatch.setattr(gate.client, "model_resident", lambda *a, **k: resident)


class TestTheScheduledJobs:
    #: The observed failure, as numbers: the model loaded, the memory it uses
    #: counted against it, the job skipped.
    def test_a_resident_model_is_not_refused_for_lack_of_room(
        self, db_session, monkeypatch
    ) -> None:
        _local(monkeypatch, free_mb=3057, resident=True)
        monkeypatch.setattr(gate.settings, "brain_min_free_mb", 3500)
        allowed, reason = gate.should_run(db_session)
        assert allowed is True
        assert "already loaded" in reason

    #: And the guard that must survive, or the board goes down: nothing loaded
    #: and no room to load it is still a refusal.
    def test_no_room_and_nothing_loaded_still_refuses(self, db_session, monkeypatch) -> None:
        _local(monkeypatch, free_mb=3057, resident=False)
        monkeypatch.setattr(gate.settings, "brain_min_free_mb", 3500)
        allowed, reason = gate.should_run(db_session)
        assert allowed is False
        assert "low RAM" in reason


class TestTheAskPanel:
    def test_a_resident_model_answers_rather_than_reporting_busy(self, monkeypatch) -> None:
        _local(monkeypatch, free_mb=100, resident=True)
        monkeypatch.setattr(gate.settings, "qa_min_free_mb", 3800)
        assert gate.qa_ram_blocked() is False

    def test_nothing_loaded_and_no_room_is_still_busy(self, monkeypatch) -> None:
        _local(monkeypatch, free_mb=100, resident=False)
        monkeypatch.setattr(gate.settings, "qa_min_free_mb", 3800)
        assert gate.qa_ram_blocked() is True


class TestTheResidencyCheckItself:
    #: It must never be the reason a job fails. Unreachable reads as "not
    #: loaded", which sends the caller back to the floor — the conservative
    #: answer, and the one that was correct before this existed.
    def test_an_unreachable_ollama_reads_as_not_loaded(self, monkeypatch) -> None:
        from app.brain import client

        monkeypatch.setattr(client.settings, "ollama_url", "http://127.0.0.1:9")
        assert client.model_resident("llama3.2:3b") is False

    def test_a_listed_model_reads_as_loaded(self, monkeypatch) -> None:
        from app.brain import client

        class _Resp:
            def raise_for_status(self) -> None: ...

            def json(self) -> dict:
                return {"models": [{"name": "llama3.2:3b", "size": 3_400_000_000}]}

        monkeypatch.setattr(client.httpx, "get", lambda url, timeout: _Resp())
        assert client.model_resident("llama3.2:3b") is True
        assert client.model_resident("qwen3.5:4b-q4_K_M") is False
