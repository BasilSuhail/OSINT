"""The RAM floor was switched off on the machine it was written to protect.

`qa_ram_blocked()` returns False — no gate at all — whenever Ollama looks remote,
because a memory reading taken here would describe the wrong machine. Correct
reasoning, wrong verdict for `host.docker.internal`: on Docker Desktop that name
crosses into a VM, and on native Linux Docker it does not cross anything at all.

Treating it as remote everywhere meant a Raspberry Pi reached
`qa_ram_blocked() -> False` for every ask, loaded a 3.4 GB model into 8 GB already
holding the stack and the console, and locked up hard. Twice. With the guard
sitting there returning False.
"""

from __future__ import annotations

import pytest

from app.brain import gate


@pytest.fixture
def undeclared(monkeypatch):
    """No explicit override, so the kernel heuristic decides."""
    monkeypatch.setattr(gate.settings, "brain_same_machine_as_ollama", None)


class TestWhatCountsAsLocal:
    @pytest.mark.parametrize("url", ["http://localhost:11434", "http://127.0.0.1:11434"])
    def test_loopback_is_always_local(self, url: str, undeclared) -> None:
        assert gate.ollama_is_local(url) is True

    #: A box on the LAN genuinely holds the model in its own memory, and a
    #: reading taken here says nothing about it.
    def test_another_machine_is_never_local(self, undeclared) -> None:
        assert gate.ollama_is_local("http://ollama-box.lan:11434") is False


class TestTheContainerToHostName:
    #: Native Linux Docker: no VM, container shares the host kernel, the reading
    #: is exact. This is the case that was wrong, and it is the Pi.
    def test_local_on_native_linux_docker(self, monkeypatch) -> None:
        monkeypatch.setattr(gate.settings, "brain_same_machine_as_ollama", None)
        monkeypatch.setattr(gate.platform, "release", lambda: "6.18.39+rpt-rpi-2712")
        assert gate.ollama_is_local("http://host.docker.internal:11434") is True

    #: Docker Desktop: the name crosses into a VM whose /proc/meminfo describes a
    #: few gigabytes that have nothing to do with the host holding the model.
    @pytest.mark.parametrize("release", ["6.10.14-linuxkit", "5.15.0-docker-desktop"])
    def test_remote_inside_docker_desktop(self, release: str, monkeypatch) -> None:
        monkeypatch.setattr(gate.settings, "brain_same_machine_as_ollama", None)
        monkeypatch.setattr(gate.platform, "release", lambda: release)
        assert gate.ollama_is_local("http://host.docker.internal:11434") is False

    #: The kernel check is a guess, and a load-bearing one, so it can be overruled
    #: on an arrangement nobody here has seen.
    def test_the_operator_can_overrule_the_guess(self, monkeypatch) -> None:
        monkeypatch.setattr(gate.platform, "release", lambda: "6.10.14-linuxkit")
        monkeypatch.setattr(gate.settings, "brain_same_machine_as_ollama", True)
        assert gate.ollama_is_local("http://host.docker.internal:11434") is True

        monkeypatch.setattr(gate.platform, "release", lambda: "6.18.39+rpt-rpi-2712")
        monkeypatch.setattr(gate.settings, "brain_same_machine_as_ollama", False)
        assert gate.ollama_is_local("http://host.docker.internal:11434") is False


class TestTheGateNowFires:
    #: The whole point: on a Pi reaching Ollama over host.docker.internal, an ask
    #: with no headroom is refused instead of taking the board down.
    def test_a_pi_with_no_headroom_is_blocked(self, monkeypatch) -> None:
        monkeypatch.setattr(gate.settings, "brain_same_machine_as_ollama", None)
        monkeypatch.setattr(gate.platform, "release", lambda: "6.18.39+rpt-rpi-2712")
        monkeypatch.setattr(gate.settings, "ollama_url", "http://host.docker.internal:11434")
        monkeypatch.setattr(gate, "ram_free_mb", lambda: 900)
        assert gate.qa_ram_blocked() is True

    def test_the_same_pi_with_room_is_allowed(self, monkeypatch) -> None:
        monkeypatch.setattr(gate.settings, "brain_same_machine_as_ollama", None)
        monkeypatch.setattr(gate.platform, "release", lambda: "6.18.39+rpt-rpi-2712")
        monkeypatch.setattr(gate.settings, "ollama_url", "http://host.docker.internal:11434")
        monkeypatch.setattr(gate, "ram_free_mb", lambda: 6500)
        assert gate.qa_ram_blocked() is False

    #: And the case the remote check was added for stays fixed: a tight VM must
    #: not refuse a load on a host with room to spare.
    def test_docker_desktop_still_never_blocks_on_the_vms_memory(self, monkeypatch) -> None:
        monkeypatch.setattr(gate.settings, "brain_same_machine_as_ollama", None)
        monkeypatch.setattr(gate.platform, "release", lambda: "6.10.14-linuxkit")
        monkeypatch.setattr(gate.settings, "ollama_url", "http://host.docker.internal:11434")
        monkeypatch.setattr(gate, "ram_free_mb", lambda: 900)
        assert gate.qa_ram_blocked() is False
