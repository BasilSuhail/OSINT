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

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEV_UP = ROOT / "scripts" / "dev-up.sh"
README = ROOT / "README.md"
SCRIPT = DEV_UP.read_text()


#: One platform's install list, from its `<details>` summary to the close of
#: the block. The README carries several of these, and only two of them are
#: Linux lists that add the account to the `docker` group.
def _install_list(summary: str) -> str:
    text = README.read_text()
    start = text.index(summary)
    return text[start : text.index("</details>", start)]


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
    #:
    #: Asked of each list separately, and of a fenced block rather than of the
    #: prose around it. This was once a count of `sudo reboot` across the whole
    #: file, which stood in for the question the name asks and answered a
    #: different one: any new block anywhere in the README that legitimately
    #: names a reboot — the server section's does, to prove the service comes
    #: back — broke a test about the install lists.
    @pytest.mark.parametrize("summary", ["Raspberry Pi 5", "Linux desktop or server"])
    def test_both_linux_lists_name_the_reboot_as_a_command(self, summary: str) -> None:
        assert "```bash\nsudo reboot\n```" in _install_list(summary)

    def test_it_says_why_rather_than_only_what(self) -> None:
        text = README.read_text()
        assert "group only takes effect on a new login" in text
