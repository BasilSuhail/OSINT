"""The RAM floor only describes the machine holding the model (#413).

#409 wrote the floor for a Pi, where the caller and the model share one
machine. Containerising the backend (#634) left the check reading the Docker
VM's `/proc/meminfo` — 2,983 MB total, ~1,026 MB available — while Ollama runs
on the host with ~11 GB free. Narration and enrichment reported success while
doing nothing, and every ask returned BRAIN_BUSY_ANSWER.

The Pi behaviour is the thing that must not move, so it is tested first.

These tests describe a container **inside Docker Desktop's VM**, which is the
arrangement that produced those numbers. That used to be implicit: any host but
loopback counted as another machine. It is stated now, because
`host.docker.internal` means the opposite on native Linux Docker — no VM, shared
kernel, an exact reading — and treating it as remote there switched the floor off
on a Raspberry Pi and let it load a model into memory it did not have (#997).
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.brain import gate


@pytest.fixture
def in_docker_desktop(monkeypatch):
    """Say out loud what these tests assume: a container inside the VM.

    Left implicit, this assumption reached native Linux Docker as well, where it
    is false and switched the memory floor off entirely.
    """
    monkeypatch.setattr(gate.settings, "brain_same_machine_as_ollama", False)


class TestWhereOllamaRuns:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:11434",
            "http://127.0.0.1:11434",
            "http://[::1]:11434",
            "http://0.0.0.0:11434",
        ],
    )
    def test_loopback_means_the_model_shares_this_memory(self, url):
        assert gate.ollama_is_local(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "http://ollama-box.lan:11434",
            "http://ollama:11434",
            "https://ollama.example.com",
        ],
    )
    def test_a_named_host_means_another_machine(self, url):
        assert gate.ollama_is_local(url) is False

    #: The container-to-host name is the one that depends on where you are: a VM
    #: boundary on Docker Desktop, nothing at all on native Linux Docker.
    def test_the_docker_host_name_is_remote_only_inside_the_vm(self, in_docker_desktop):
        assert gate.ollama_is_local("http://host.docker.internal:11434") is False


class TestTheFloorStillProtectsThePi:
    def test_low_ram_still_blocks_when_the_model_is_local(self, db_session: Session, monkeypatch):
        #: Nothing resident, so the floor is the question — stated rather
        #: than left to whether this machine is running Ollama.
        monkeypatch.setattr(gate.client, "model_resident", lambda *a, **k: False)
        # The #409 case, unchanged: one machine, genuinely short of memory.
        monkeypatch.setattr(gate.settings, "ollama_url", "http://localhost:11434")
        monkeypatch.setattr(gate, "ram_free_mb", lambda: 500)
        monkeypatch.setattr(gate.settings, "brain_min_free_mb", 1200)

        allowed, reason = gate.should_run(db_session)

        assert allowed is False
        assert "low RAM" in reason

    def test_ample_ram_still_allows_when_the_model_is_local(self, db_session: Session, monkeypatch):
        #: Nothing resident, so the floor is the question — stated rather
        #: than left to whether this machine is running Ollama.
        monkeypatch.setattr(gate.client, "model_resident", lambda *a, **k: False)
        monkeypatch.setattr(gate.settings, "ollama_url", "http://localhost:11434")
        monkeypatch.setattr(gate, "ram_free_mb", lambda: 4000)
        monkeypatch.setattr(gate.settings, "brain_min_free_mb", 1200)

        allowed, reason = gate.should_run(db_session)

        assert allowed is True
        assert "4000MB free" in reason


class TestTheContainerCase:
    def test_a_remote_model_is_not_blocked_by_local_memory(
        self, db_session: Session, monkeypatch, in_docker_desktop
    ):
        # The measured defect: 1,026 MB in the Docker VM, 1,200 MB floor, and
        # ~11 GB free on the host that actually loads the model.
        monkeypatch.setattr(gate.settings, "ollama_url", "http://host.docker.internal:11434")
        monkeypatch.setattr(gate, "ram_free_mb", lambda: 1026)
        monkeypatch.setattr(gate.settings, "brain_min_free_mb", 1200)

        allowed, _ = gate.should_run(db_session)

        assert allowed is True

    def test_the_reason_admits_the_floor_was_not_applied(
        self, db_session: Session, monkeypatch, in_docker_desktop
    ):
        # It must not read like a RAM check that passed. Backoff was visible by
        # design in #409; so should its absence be.
        monkeypatch.setattr(gate.settings, "ollama_url", "http://host.docker.internal:11434")
        monkeypatch.setattr(gate, "ram_free_mb", lambda: 1026)

        _, reason = gate.should_run(db_session)

        assert "RAM floor not applied" in reason
        assert "MB free" not in reason

    def test_the_other_gates_still_apply_to_a_remote_model(
        self, db_session: Session, monkeypatch, in_docker_desktop
    ):
        # What is dropped is a reading of the wrong machine, not the backoff.
        monkeypatch.setattr(gate.settings, "ollama_url", "http://host.docker.internal:11434")
        monkeypatch.setattr(gate, "ram_free_mb", lambda: 1026)
        monkeypatch.setattr(gate.runtime_load, "busy_reason", lambda now=None: "you are working")

        allowed, reason = gate.should_run(db_session)

        assert allowed is False
        assert reason == "you are working"


class TestAskTheBrain:
    def test_ask_was_refused_on_every_request_in_a_container(self, monkeypatch, in_docker_desktop):
        # 995 MB measured in the API container against a 3,800 MB floor — and
        # the floor is bigger than the VM's entire 2,983 MB, so no load could
        # ever satisfy it. Every ask returned BRAIN_BUSY_ANSWER.
        monkeypatch.setattr(gate.settings, "ollama_url", "http://host.docker.internal:11434")
        monkeypatch.setattr(gate, "ram_free_mb", lambda: 995)
        monkeypatch.setattr(gate.settings, "qa_min_free_mb", 3800)

        assert gate.qa_ram_blocked() is False

    def test_ask_is_still_refused_locally_when_the_model_will_not_fit(self, monkeypatch):
        monkeypatch.setattr(gate.settings, "ollama_url", "http://localhost:11434")
        monkeypatch.setattr(gate, "ram_free_mb", lambda: 995)
        monkeypatch.setattr(gate.settings, "qa_min_free_mb", 3800)

        assert gate.qa_ram_blocked() is True
