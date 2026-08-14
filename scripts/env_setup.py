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

#: `KEY: /some/literal` inside a compose file. The container is *given* this
#: value, so whatever `.env` says for that key never reaches the process and
#: cannot be wrong. Lines whose value interpolates something are not literals
#: and are matched by the pattern above instead.
_COMPOSE_LITERAL = re.compile(r"^\s{2,}([A-Z_][A-Z0-9_]*):\s*(?!\$\{)(\S[^\n]*)$", re.M)

#: Keys this project's own scripts write into `.env` at runtime. They are not
#: in the example because nobody sets them by hand, and reporting them as
#: unknown would train an operator to ignore the one report that catches typos.
_RUNTIME_KEYS = frozenset({"COMPOSE_PROJECT_NAME"})

#: Keys whose value is a path. Checked for the one mistake that is invisible
#: from here: a path from this machine given to something that reads it from
#: inside a container (#959).
_PATH_SUFFIXES = ("_PATH", "_DIR")

#: Where a containerised process can actually read. `/data` is the repository's
#: data directory as mounted inside the containers; `/app` is the code.
_CONTAINER_ROOTS = ("/data", "/app")

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


def overridden_keys(compose_texts: list[str]) -> set[str]:
    """Keys the compose files hand the containers directly.

    `.env` may say anything about these; the process never sees it. Checking
    such a value would be reporting a mistake that cannot have an effect, and a
    report that cries wolf is one an operator learns to skip.
    """
    found: set[str] = set()
    for text in compose_texts:
        found.update(match.group(1) for match in _COMPOSE_LITERAL.finditer(text))
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


def set_value(env_text: str, key: str, value: str) -> tuple[str, bool]:
    """`.env` with one key set, and whether that changed anything.

    The one exception to "never touch a value". `sync` is a general tool and
    has no business overwriting an answer somebody gave; this is called by the
    command that owns a particular setting, to point it at the file that
    command has just written. It replaces every line for that key, because a
    key written twice is read as the last one and leaving an earlier line
    behind would be leaving a lie behind.
    """
    line = f"{key}={value}"
    kept: list[str] = []
    replaced = False
    changed = False
    for raw in env_text.splitlines():
        match = _ASSIGNMENT.match(raw.strip())
        if match is not None and match.group(1) == key:
            if replaced:
                changed = True
                continue
            replaced = True
            if raw.strip() != line:
                changed = True
            kept.append(line)
            continue
        kept.append(raw)
    if not replaced:
        kept.append(line)
        changed = True
    return "\n".join(kept) + "\n", changed


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
    #: Paths written as this machine sees them, for settings something reads
    #: from inside a container. The file is right there in the terminal and
    #: simply does not exist where it is needed (#959).
    host_paths: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.missing
            or self.required_empty
            or self.placeholders
            or self.unknown
            or self.duplicated
            or self.host_paths
        )


def looks_like_a_host_path(key: str, value: str, host_side: set[str]) -> bool:
    """Whether this setting names a path the container will not find.

    ``host_side`` is every key the compose files either interpolate or set
    outright. The first sort is read out here, where an absolute path from this
    machine is exactly right; the second never reaches the process at all, so
    whatever is written in `.env` cannot be wrong. What is left is read by the
    application, which normally runs in a container — and in there
    `/Users/somebody/file.json` is not a file, it is nothing at all.
    """
    if not key.endswith(_PATH_SUFFIXES) or key in host_side:
        return False
    path = value.strip().strip("\"'")
    if not path.startswith("/"):
        return False
    return not path.startswith(_CONTAINER_ROOTS)


def check(
    example_text: str,
    env_text: str | None,
    required: set[str],
    overridden: set[str] | None = None,
) -> CheckReport:
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
        elif looks_like_a_host_path(key, value, required | (overridden or set())):
            report.host_paths.append(key)
    return report


def _read(path: pathlib.Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def _print_check(report: CheckReport) -> None:
    """The findings, in the order somebody would act on them.

    Every one of these is a note rather than a fault. The app starts with any
    of them outstanding, and the exit code is for a script that wants to know,
    not a verdict on the console — the `make` target says so in as many words,
    because a non-zero exit reads as a crash to somebody who did not write it.
    """
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
    if report.host_paths:
        print(f"  {len(report.host_paths)} key(s) name a path this machine can see but the")
        print("  containers cannot — they read it from inside, where that path does not exist:")
        for key in report.host_paths:
            print(f"    {key}")
        print("  put the file under data/ and name it /data/<file>, or leave the key empty")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("sync", "check", "set"))
    parser.add_argument("key", nargs="?", help="for `set`: the setting to point somewhere")
    parser.add_argument("value", nargs="?", help="for `set`: what to point it at")
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

    if args.action == "set":
        if not args.key or args.value is None:
            print("  set needs a key and a value", file=sys.stderr)
            return 1
        rendered, changed = set_value(env_text or "", args.key, args.value)
        if changed:
            env_path.write_text(rendered)
            print(f"  {env_path}: {args.key} now points at {args.value}")
        else:
            print(f"  {args.key} already points at {args.value}")
        return 0

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
    report = check(
        example_text,
        env_text,
        required_keys(compose_texts),
        overridden_keys(compose_texts),
    )
    _print_check(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
