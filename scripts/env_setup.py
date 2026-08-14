"""Create and repair the local ``.env`` from ``env.example`` (#957).

``env.example`` is the list of every setting this project reads, with the
comments that explain them. ``.env`` is one operator's answers. Keeping the
second in step with the first was a manual job nobody was told about, and it
failed in three ways that were all seen rather than imagined: a key added to
the example months after a copy never reached the copy, a typed key name loaded
as nothing and started the process anyway, and a first run had no starting
point at all.

Two commands, both safe to run again and again:

``sync``   creates ``.env`` when it is missing, and otherwise appends only the
           keys it does not have, carrying the comments that explain them. A
           value already in the file is never touched, reordered or reformatted
           — it is somebody's answer, possibly a credential, and this script
           has no opinion about it.

``check``  says what is missing, what is required and still empty, and what is
           in ``.env`` but not in the example, which is how a typo becomes
           visible. Exits non-zero when it finds something.

**No value is ever printed.** The file holds credentials and this output goes
to a terminal that may be shared, logged or recorded, so the report names keys
and counts and nothing else.

Standard library only, and run with the system ``python3``: this is the script
somebody runs before the virtual environment exists.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from dataclasses import dataclass, field

#: A KEY=value line. Keys are upper snake case by convention here; anything
#: else in the example is a comment or a blank.
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

#: `${VAR}` and `${VAR:-default}` in the compose files. A key referenced there
#: is one the stores actually need, which is a stronger claim than "documented"
#: and the only definition of "required" this script is willing to make.
_COMPOSE_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")

#: Keys this project's own scripts write into `.env` at runtime. They are not
#: in the example because nobody sets them by hand, and reporting them as
#: unknown would train an operator to ignore the one report that catches typos.
_RUNTIME_KEYS = frozenset({"COMPOSE_PROJECT_NAME"})

#: Values that are obviously somebody's intention to come back later.
_PLACEHOLDERS = frozenset({"changeme", "change-me", "your-key-here", "xxx", "todo", "tbd"})


@dataclass(frozen=True)
class Block:
    """One setting in the example, with the comment lines that introduce it."""

    key: str
    value: str
    comments: tuple[str, ...] = ()

    def rendered(self) -> str:
        return "".join(f"{line}\n" for line in self.comments) + f"{self.key}={self.value}\n"


def unique_blocks(blocks: list[Block]) -> list[Block]:
    """The example's settings, one per key, first occurrence winning.

    A key written twice in the example is a mistake in the example — this
    script found one on its first run — but it must not become two appended
    lines in somebody's `.env`, where the second would silently override
    whatever they had answered.
    """
    seen: set[str] = set()
    out: list[Block] = []
    for block in blocks:
        if block.key in seen:
            continue
        seen.add(block.key)
        out.append(block)
    return out


def duplicate_keys(blocks: list[Block]) -> list[str]:
    """Keys the example defines more than once."""
    seen: set[str] = set()
    twice: list[str] = []
    for block in blocks:
        if block.key in seen and block.key not in twice:
            twice.append(block.key)
        seen.add(block.key)
    return twice


def parse_example(text: str) -> list[Block]:
    """The example, as ordered settings each carrying its own explanation.

    Comments are attached to the key that follows them, so a key appended to a
    ``.env`` later arrives with the sentence that says what it is for. A
    comment block separated from the next key by a blank line is a section
    heading rather than a note about one setting, and is left behind.
    """
    blocks: list[Block] = []
    pending: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            pending.clear()
            continue
        if line.lstrip().startswith("#"):
            pending.append(line)
            continue
        match = _ASSIGNMENT.match(line)
        if match is None:
            pending.clear()
            continue
        blocks.append(Block(key=match.group(1), value=match.group(2), comments=tuple(pending)))
        pending.clear()
    return blocks


def parse_env(text: str) -> dict[str, str]:
    """The keys an existing ``.env`` sets, and what it sets them to.

    Later wins, which is what a shell would do reading the same file, so a key
    appended twice reads as the value that is actually in force.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.match(line)
        if match is not None:
            out[match.group(1)] = match.group(2).strip()
    return out


def required_keys(compose_texts: list[str]) -> set[str]:
    """Keys the container stack interpolates, and therefore actually needs."""
    found: set[str] = set()
    for text in compose_texts:
        found.update(_COMPOSE_REF.findall(text))
    return found


def is_placeholder(value: str) -> bool:
    stripped = value.strip().strip("\"'")
    return stripped.lower() in _PLACEHOLDERS


@dataclass
class SyncReport:
    created: bool = False
    added: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.created or bool(self.added)


def sync(example_text: str, env_text: str | None) -> tuple[str, SyncReport]:
    """The `.env` this project should have, given the one it has.

    Returns the whole file rather than writing it, so the decision to touch
    somebody's configuration belongs to the caller and a test never needs a
    filesystem.
    """
    blocks = unique_blocks(parse_example(example_text))
    if env_text is None:
        rendered = example_text if example_text.endswith("\n") else example_text + "\n"
        return rendered, SyncReport(created=True, added=[b.key for b in blocks])

    have = parse_env(env_text)
    missing = [b for b in blocks if b.key not in have]
    if not missing:
        return env_text, SyncReport()

    #: Appended, never merged in place. Rewriting the file to the example's
    #: order would reformat somebody's answers and lose any note they wrote
    #: beside them, for the sake of tidiness nobody asked for.
    body = env_text if env_text.endswith("\n") else env_text + "\n"
    parts = [
        body,
        "\n# Added by `make env` — these are in env.example but were not here.\n",
    ]
    parts.extend(block.rendered() for block in missing)
    return "".join(parts), SyncReport(added=[b.key for b in missing])


@dataclass
class CheckReport:
    """What is wrong with a `.env`, named by key and never by value."""

    missing: list[str] = field(default_factory=list)
    required_empty: list[str] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    #: Keys `env.example` itself defines twice. Not the operator's problem to
    #: fix, but theirs to suffer: the second line wins and the first is a lie.
    duplicated: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.missing
            or self.required_empty
            or self.placeholders
            or self.unknown
            or self.duplicated
        )


def check(example_text: str, env_text: str | None, required: set[str]) -> CheckReport:
    """Everything worth saying about a `.env`, in one pass.

    ``unknown`` is the one that catches a typo: a key in `.env` that the
    example has never heard of is either a setting that was renamed or a
    misspelling that is loading as nothing, and both are silent otherwise.
    """
    parsed = parse_example(example_text)
    duplicated = duplicate_keys(parsed)
    if env_text is None:
        return CheckReport(missing=[b.key for b in unique_blocks(parsed)], duplicated=duplicated)

    documented = {b.key: b for b in parsed}
    have = parse_env(env_text)
    report = CheckReport(duplicated=duplicated)
    for key in documented:
        if key not in have:
            report.missing.append(key)
    for key, value in have.items():
        if key not in documented:
            if key not in _RUNTIME_KEYS:
                report.unknown.append(key)
            continue
        if not value.strip() and key in required:
            report.required_empty.append(key)
        elif is_placeholder(value):
            report.placeholders.append(key)
    return report


def _read(path: pathlib.Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _print_check(report: CheckReport) -> None:
    if report.ok:
        print("  .env looks complete")
        return
    if report.missing:
        print(f"  {len(report.missing)} key(s) in env.example are missing from .env:")
        for key in report.missing:
            print(f"    {key}")
        print("  run `make env` to add them")
    if report.required_empty:
        print(f"  {len(report.required_empty)} key(s) the container stack needs are empty:")
        for key in report.required_empty:
            print(f"    {key}")
    if report.placeholders:
        print(f"  {len(report.placeholders)} key(s) still hold a placeholder:")
        for key in report.placeholders:
            print(f"    {key}")
    if report.unknown:
        print(f"  {len(report.unknown)} key(s) in .env are not in env.example — renamed, or typed:")
        for key in report.unknown:
            print(f"    {key}")
    if report.duplicated:
        print(f"  {len(report.duplicated)} key(s) are defined twice in env.example:")
        for key in report.duplicated:
            print(f"    {key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("sync", "check"))
    parser.add_argument("--root", default=".", help="project root holding env.example")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.root)
    example_path = root / "env.example"
    env_path = root / ".env"

    example_text = _read(example_path)
    if example_text is None:
        print(f"  no {example_path} to work from", file=sys.stderr)
        return 1
    env_text = _read(env_path)

    if args.action == "sync":
        rendered, report = sync(example_text, env_text)
        if report.changed:
            env_path.write_text(rendered)
        if report.created:
            print(f"  wrote {env_path} from env.example ({len(report.added)} keys)")
            print("  fill in the ones that need values, then `make up`")
        elif report.added:
            print(f"  added {len(report.added)} missing key(s) to {env_path}:")
            for key in report.added:
                print(f"    {key}")
        else:
            print(f"  {env_path} already has every key in env.example")
        return 0

    compose_texts = [
        text
        for text in (
            _read(root / "docker-compose.yml"),
            _read(root / "docker-compose.dev.yml"),
        )
        if text is not None
    ]
    report = check(example_text, env_text, required_keys(compose_texts))
    _print_check(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
