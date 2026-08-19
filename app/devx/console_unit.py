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
        if value.endswith("\\"):
            # systemd's EnvironmentFile parser reads a trailing backslash as a
            # line continuation and merges the next line into this value,
            # corrupting both — the same class of failure the newline check
            # above exists to catch.
            raise ValueError(f"{key} ends with a backslash, which systemd reads as a continuation")
        if value.startswith(('"', "'")):
            # A leading quote is quote-processed by systemd too, not just a
            # trailing one — the docstring above already refuses to add
            # quotes; a value that arrives already carrying one is refused
            # for the same reason.
            raise ValueError(f"{key} starts with a quote character, which systemd strips out")
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
# `After=` only orders two units that are already starting; it does not pull
# tailscaled into the boot transaction. `Wants=` is what starts it. Together
# they are what actually keeps this unit from binding an address that does
# not exist yet.
After=network-online.target tailscaled.service
Wants=network-online.target tailscaled.service

[Service]
Type=simple
WorkingDirectory={working_dir}
# systemd units run with a minimal built-in PATH and never source a login
# shell, so an inherited PATH cannot be relied on to contain `pnpm` — this
# repository has already hit exactly that failure once, in
# scripts/dev-up.sh, which runs `pnpm dev` through a login shell for the
# same reason. Named explicitly here instead, covering where the documented
# install (`apt install nodejs && corepack enable`) puts its shims.
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
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
