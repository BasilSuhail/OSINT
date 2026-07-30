"""Where the data folder is, answered once (#697).

Twenty-one call sites each resolved this themselves by reading an environment
variable named OSINT_DATA_DIR with a "./data" fallback, and that variable is set
nowhere — not in `.env`, not in compose, not in the Dockerfile. Every one of
them was riding the fallback.

On the host the fallback is right by coincidence: `make` runs from the repo root
so `./data` lands on the real folder. In a container the working directory is
`/app`, `/app/data` does not exist, and the mount is at `/data`. So reads 404'd
against files that were sitting on disk, and containerised writes went into the
image layer instead of the volume, where they vanished on the next restart.

`settings.data_dir` was correct the whole time — no env prefix, so it binds to
`DATA_DIR`, which compose sets to `/data`. This routes everything through it.
"""

from __future__ import annotations

from pathlib import Path

from app.settings import settings


def data_dir() -> Path:
    """The data folder, as configured. `DATA_DIR` in the environment wins."""
    return Path(settings.data_dir)


def exports_dir() -> Path:
    """Where reports are written and read. Created if absent.

    Callers used to assume it existed, which held only because the host had
    already been used once. A containerised job writing the first report of its
    life would otherwise fail on a missing parent.
    """
    path = data_dir() / "exports"
    path.mkdir(parents=True, exist_ok=True)
    return path
