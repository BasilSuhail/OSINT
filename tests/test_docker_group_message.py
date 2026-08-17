"""A daemon that refuses this account is not a daemon that is down (#1011).

`sudo usermod -aG docker "$USER"` takes effect on the next login. Until then
every Docker command is refused, and to a caller that looks exactly like Docker
not running. Reported as the latter, the advice was "Start Docker Desktop" — on a
Raspberry Pi, an instruction naming software that does not exist for it.

Found on a clean board following the README: four steps succeeded because none
of them touch Docker, and the failure surfaced minutes later at `make up`.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV_UP = ROOT / "scripts" / "dev-up.sh"
README = ROOT / "README.md"
SCRIPT = DEV_UP.read_text()


class TestTheScriptTellsThemApart:
    def test_it_checks_for_a_refused_connection(self) -> None:
        assert "docker_denied" in SCRIPT
        assert "permission denied" in SCRIPT

    #: Checked before anything about starting Docker, because Docker is already
    #: running in this case and starting it again fixes nothing.
    def test_the_refusal_is_checked_before_the_start_advice(self) -> None:
        body = SCRIPT[SCRIPT.index("ensure_docker()") :]
        assert body.index("docker_denied") < body.index("DOCKER_AUTOSTART")

    #: The whole point: a reboot is the fix, so the message has to name it.
    def test_it_says_how_to_fix_it(self) -> None:
        block = SCRIPT[SCRIPT.index("docker_denied() {") :]
        block = block[: block.index('printf "→ waiting for Docker"')]
        assert "sudo reboot" in block

    def test_it_does_not_blame_docker_desktop(self) -> None:
        block = SCRIPT[SCRIPT.index("if docker_denied; then") :]
        block = block[: block.index("DOCKER_AUTOSTART")]
        assert "Desktop" not in block


class TestTheAdviceMatchesThePlatform:
    #: "Start Docker Desktop" on Linux names software that does not exist there.
    def test_linux_is_told_to_start_the_service(self) -> None:
        assert "systemctl start docker" in SCRIPT

    def test_the_desktop_advice_is_guarded_by_the_platform(self) -> None:
        assert re.search(r"uname -s.*=.*Linux", SCRIPT) is not None

    def test_the_script_is_valid_shell(self) -> None:
        assert subprocess.run(["bash", "-n", str(DEV_UP)], check=False).returncode == 0


class TestTheReadmeSaysItPlainly:
    #: It said "then log out and back in" as part of a sentence introducing a
    #: command block, which is a thing to notice rather than a step to do.
    def test_both_linux_lists_name_the_reboot_as_a_command(self) -> None:
        assert README.read_text().count("sudo reboot") == 2

    def test_it_says_why_rather_than_only_what(self) -> None:
        text = README.read_text()
        assert "group only takes effect on a new login" in text
