"""Keep the checkout current before `make up` starts anything (#661).

Three fixes were merged and none of them ran: the running code was not the
merged code, and no part of the system knew the difference. `make up` already
solves getting code from disk into the containers (#634) — the dev overlay
bind-mounts `app/`, so host files *are* the running code. What was missing is
getting the merged code onto disk in the first place.

`git pull` does not cover it, because GitHub squash-merges. A local commit and
its squashed twin have identical trees and different SHAs, so git sees forked
histories, refuses to fast-forward, and says very little. That is structural:
every squash-merged PR forks the local branch the same way.

The rule here is that **uncommitted or unpushed work is never destroyed**, and
anything else is not worth an hour of debugging a system that was already
fixed. When the sync cannot be proven safe this refuses, says exactly what it
found, and lets the stack start anyway — a stale checkout is a nuisance, a
failure to start is not.

    python -m app.devx.repo_sync            # sync if safe, always explain
    OSINT_NO_AUTO_SYNC=1 make up            # skip entirely
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

#: The only branch synced automatically. Resetting a feature branch mid-work is
#: exactly the thing this must never do.
MAIN_BRANCH: str = "main"

#: Set to skip the whole thing. A script that reaches for the network on every
#: start needs an off switch.
SKIP_ENV: str = "OSINT_NO_AUTO_SYNC"

Action = Literal["none", "fast_forward", "reset", "refuse"]


@dataclass(frozen=True)
class Decision:
    """What to do, and the sentence explaining it. The sentence is not optional:
    the failure this fixes was not knowing which code was running."""

    action: Action
    reason: str


def decide(*, branch: str, dirty: bool, behind: int, local_only: list[str]) -> Decision:
    """Pure decision. `local_only` is `git cherry` output, one line per commit.

    `git cherry origin/main HEAD` marks each local-only commit:

        -  <sha>   already upstream — a squash-merge artifact, safe to drop
        +  <sha>   genuinely unpushed work — never drop

    A `-` on every line is exactly the squash case, and resetting loses nothing.
    A single `+` means real work exists only here, and nothing is touched.
    """
    if branch != MAIN_BRANCH:
        return Decision(
            "none", f"on branch {branch!r} — only {MAIN_BRANCH} is synced automatically"
        )

    if dirty:
        return Decision(
            "refuse",
            "uncommitted changes in the working tree — not touching them. "
            "Commit or stash, then re-run.",
        )

    unpushed = [line for line in local_only if line.strip().startswith("+")]
    if unpushed:
        return Decision(
            "refuse",
            f"{len(unpushed)} local commit(s) are not upstream — not discarding them. "
            "Push them, or reset by hand once they are merged.",
        )

    if local_only:
        return Decision(
            "reset",
            f"{len(local_only)} local commit(s) already upstream (squash-merged) — "
            f"resetting to origin/{MAIN_BRANCH}",
        )

    if behind:
        return Decision("fast_forward", f"{behind} commit(s) behind origin/{MAIN_BRANCH}")

    return Decision("none", "already up to date")


def _git(*args: str, root: str | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def inspect(root: str | None = None) -> Decision:
    """Read the repo's state and decide. Never writes."""
    branch = _git("rev-parse", "--abbrev-ref", "HEAD", root=root)
    dirty = bool(_git("status", "--porcelain", root=root))
    behind = int(_git("rev-list", "--count", f"HEAD..origin/{MAIN_BRANCH}", root=root) or 0)
    local_only = [
        line
        for line in _git("cherry", f"origin/{MAIN_BRANCH}", "HEAD", root=root).splitlines()
        if line.strip()
    ]
    return decide(branch=branch, dirty=dirty, behind=behind, local_only=local_only)


def apply(decision: Decision, root: str | None = None) -> None:
    """Carry out a decision. `none` and `refuse` write nothing."""
    if decision.action == "fast_forward":
        _git("merge", "--ff-only", f"origin/{MAIN_BRANCH}", root=root)
    elif decision.action == "reset":
        _git("reset", "--hard", f"origin/{MAIN_BRANCH}", root=root)


def main() -> int:
    if os.environ.get(SKIP_ENV):
        print(f"  repo sync skipped ({SKIP_ENV} set)")
        return 0

    try:
        _git("rev-parse", "--git-dir")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("  repo sync skipped (not a git checkout)")
        return 0

    try:
        _git("fetch", "--quiet", "origin")
    except subprocess.CalledProcessError:
        # Offline is not a reason to refuse to start. Say so and carry on.
        print("  repo sync skipped (could not reach origin — working offline?)")
        return 0

    try:
        decision = inspect()
    except subprocess.CalledProcessError as exc:
        print(f"  repo sync skipped (git said: {exc.stderr.strip() or exc})")
        return 0

    if decision.action == "refuse":
        print(f"  ⚠ repo NOT synced: {decision.reason}")
        print("    the stack will start on the code currently on disk")
        return 0

    apply(decision)
    label = {"none": "repo", "fast_forward": "repo updated", "reset": "repo reset"}
    print(f"  {label[decision.action]}: {decision.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
