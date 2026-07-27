"""Keeping the checkout current before `make up` (#661).

The decision table is small and the cost of getting it wrong is asymmetric: a
stale checkout wastes an hour, a bad reset destroys work that exists nowhere
else. So the refusals are tested at least as hard as the syncs, and the squash
-merge case is exercised against a real git repository rather than a mocked
`git cherry`, because the whole fix rests on what that command actually says.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.devx.repo_sync import decide, inspect


class TestDecision:
    def test_a_feature_branch_is_never_touched(self):
        # Mid-feature is exactly when a reset is unforgivable.
        decision = decide(branch="656-some-fix", dirty=False, behind=5, local_only=[])

        assert decision.action == "none"
        assert "only main" in decision.reason

    def test_uncommitted_work_stops_everything(self):
        decision = decide(branch="main", dirty=True, behind=3, local_only=[])

        assert decision.action == "refuse"
        assert "uncommitted" in decision.reason

    def test_real_unpushed_commits_are_never_discarded(self):
        decision = decide(
            branch="main", dirty=False, behind=0, local_only=["+ abc123 work in progress"]
        )

        assert decision.action == "refuse"

    def test_unpushed_work_wins_over_squashed_commits_in_the_same_list(self):
        # One genuine `+` among several `-` still means: touch nothing.
        decision = decide(
            branch="main",
            dirty=False,
            behind=0,
            local_only=["- aaa already upstream", "+ bbb mine only"],
        )

        assert decision.action == "refuse"

    def test_squash_merged_commits_are_safe_to_reset(self):
        decision = decide(
            branch="main", dirty=False, behind=3, local_only=["- aaa already upstream"]
        )

        assert decision.action == "reset"
        assert "squash-merged" in decision.reason

    def test_plain_behind_fast_forwards(self):
        decision = decide(branch="main", dirty=False, behind=2, local_only=[])

        assert decision.action == "fast_forward"

    def test_up_to_date_says_so_rather_than_staying_quiet(self):
        # The failure being fixed is not knowing which code is running, so the
        # no-op has to speak too.
        decision = decide(branch="main", dirty=False, behind=0, local_only=[])

        assert decision.action == "none"
        assert decision.reason == "already up to date"


def _git(root: Path, *args: str) -> str:
    # Hooks are disabled so these fixtures do not depend on whatever the
    # developer's global git config enforces (this repo's own pre-commit hook
    # rejects a non-noreply author, which has nothing to do with what is under
    # test here).
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A local clone with an `origin/main` to compare against."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "--quiet", "--initial-branch=main")
    _git(origin, "config", "user.email", "t@example.com")
    _git(origin, "config", "user.name", "t")
    (origin / "a.txt").write_text("one\n")
    _git(origin, "add", "a.txt")
    _git(origin, "commit", "--quiet", "-m", "first")

    work = tmp_path / "work"
    _git(tmp_path, "clone", "--quiet", str(origin), str(work))
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    return work


class TestAgainstRealGit:
    def test_a_clean_clone_is_up_to_date(self, clone: Path):
        assert inspect(str(clone)).action == "none"

    def test_a_squash_merge_is_recognised_as_safe(self, clone: Path, tmp_path: Path):
        # The exact shape that cost an hour: the same change committed locally,
        # and squash-merged upstream under a different SHA.
        (clone / "b.txt").write_text("two\n")
        _git(clone, "add", "b.txt")
        _git(clone, "commit", "--quiet", "-m", "add b")

        origin = tmp_path / "origin"
        (origin / "b.txt").write_text("two\n")
        _git(origin, "add", "b.txt")
        _git(origin, "commit", "--quiet", "-m", "add b (#12)")

        _git(clone, "fetch", "--quiet", "origin")
        decision = inspect(str(clone))

        assert decision.action == "reset"

    def test_genuinely_local_work_is_refused(self, clone: Path):
        (clone / "mine.txt").write_text("only here\n")
        _git(clone, "add", "mine.txt")
        _git(clone, "commit", "--quiet", "-m", "my unpushed work")

        decision = inspect(str(clone))

        assert decision.action == "refuse"

    def test_a_dirty_tree_is_refused_even_when_behind(self, clone: Path, tmp_path: Path):
        origin = tmp_path / "origin"
        (origin / "c.txt").write_text("three\n")
        _git(origin, "add", "c.txt")
        _git(origin, "commit", "--quiet", "-m", "add c")
        _git(clone, "fetch", "--quiet", "origin")
        (clone / "a.txt").write_text("edited, not committed\n")

        decision = inspect(str(clone))

        assert decision.action == "refuse"
        assert "uncommitted" in decision.reason

    def test_behind_origin_fast_forwards(self, clone: Path, tmp_path: Path):
        origin = tmp_path / "origin"
        (origin / "c.txt").write_text("three\n")
        _git(origin, "add", "c.txt")
        _git(origin, "commit", "--quiet", "-m", "add c")
        _git(clone, "fetch", "--quiet", "origin")

        decision = inspect(str(clone))

        assert decision.action == "fast_forward"
