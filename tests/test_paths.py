"""Where the data folder is (#697).

`make coverage` wrote a 60 kB report and the dashboard showed nothing, because
the API resolved its path from `OSINT_DATA_DIR` — a variable set nowhere — and
fell back to `./data`, which is `/app/data` inside the container and does not
exist. The failure mode is silence, so these pin the resolution rather than
trusting it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import paths
from app.settings import settings


def test_the_configured_data_dir_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    # `/data` is what compose mounts inside the container. Only the resolution
    # is asserted here; creating it would need root on the host.
    monkeypatch.setattr(settings, "data_dir", "/data")

    assert paths.data_dir() == Path("/data")


def test_an_unset_ghost_variable_cannot_redirect_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The whole defect: OSINT_DATA_DIR was the variable being read and nothing
    # ever set it. Setting it now must change nothing.
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setenv("OSINT_DATA_DIR", "/somewhere/else")

    assert paths.exports_dir() == tmp_path / "exports"


def test_exports_dir_is_created_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A containerised job writing its first report must not fail on a missing
    # parent — the previous code assumed the folder already existed.
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "fresh"))

    exports = paths.exports_dir()

    assert exports.is_dir()
    assert exports == tmp_path / "fresh" / "exports"


def test_calling_twice_is_harmless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

    assert paths.exports_dir() == paths.exports_dir()


def test_no_module_resolves_the_exports_path_by_hand() -> None:
    """The regression guard. Twenty-one sites each rolled their own.

    Reading `OSINT_DATA_DIR` anywhere means a path that works from the repo
    root and breaks in a container, silently, which is how this survived.
    """
    app_dir = Path(__file__).resolve().parent.parent / "app"
    offenders = [
        py.relative_to(app_dir).as_posix()
        for py in app_dir.rglob("*.py")
        if 'os.environ.get("OSINT_DATA_DIR"' in py.read_text(encoding="utf-8")
    ]

    assert offenders == [], f"resolve via app.paths instead: {offenders}"
