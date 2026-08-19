"""The console's systemd unit, rendered rather than shipped.

A checked-in unit file cannot know where the repository was cloned, which
address the tailnet handed out, or which port the console was told to use, and
a file with three placeholders to edit by hand is three chances to install a
unit that names a directory that does not exist.

So it is text this module produces and `scripts/serve-up.sh` writes, which is
also what makes it testable: the failures worth catching are all failures of
the text. Starting before the tailnet is up binds an address that does not
exist yet. Not restarting turns one crash into a dark console until somebody
notices. Writing the token into the unit publishes it to every account on the
machine, because unit files are world-readable and the environment file beside
them is not.
"""

from __future__ import annotations

UNIT_NAME = "osint-console.service"


def env_file_text(env: dict[str, str]) -> str:
    """`KEY=value` lines for systemd's `EnvironmentFile`.

    Unquoted, deliberately: this is read by systemd and not by a shell, so a
    quoted value arrives with the quotes still attached — an origin list that
    starts with a quote character matches no origin at all.
    """
    lines = []
    for key, value in env.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"{key} contains a newline, which would truncate it")
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def unit_text(
    *,
    working_dir: str,
    env_file: str,
    bind: str,
    port: int,
    commit_file: str,
) -> str:
    """The service that keeps the console up."""
    return f"""[Unit]
Description=OSINT console
Documentation=https://github.com/BasilSuhail/OSINT
# The bind address does not exist until the tailnet is up, and a unit that
# starts before it fails at boot while working perfectly when tried by hand.
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={working_dir}
# Beside the unit rather than in it: unit files are world-readable.
EnvironmentFile={env_file}
# Which build is being served, in the journal, so a fix that was pulled and
# not rebuilt is a line to read rather than a mystery.
ExecStartPre=/bin/sh -c 'echo "console build: $(cat {commit_file} 2>/dev/null || echo unknown)"'
ExecStart=/usr/bin/env pnpm exec next start -H {bind} -p {port}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
