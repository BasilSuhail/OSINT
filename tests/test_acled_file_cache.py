"""ACLED must not re-parse files that have not changed (#538).

Measured on the live app: the hourly ACLED task spent 107 seconds at 100% CPU
and wrote 0 rows, because it re-read 104 MB of .xlsx through pandas every hour
even though the files had not changed since June. openpyxl expands those sheets
into DataFrames, which was a large part of a 2.68 GB worker peak.
"""

from __future__ import annotations

from pathlib import Path

from app.sources.acled_fetcher import file_signature, unchanged_since_last_parse


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


def test_signature_changes_when_contents_change(tmp_path):
    p = _write(tmp_path, "a.csv", "one")
    first = file_signature(p)
    p.write_text("one much longer body")
    assert file_signature(p) != first


def test_signature_is_stable_for_an_untouched_file(tmp_path):
    p = _write(tmp_path, "a.csv", "one")
    assert file_signature(p) == file_signature(p)


def test_unchanged_file_is_skipped_on_the_second_run(tmp_path):
    state = tmp_path / "state.json"
    p = _write(tmp_path, "a.csv", "one")

    assert unchanged_since_last_parse(p, state_path=state) is False
    # First call records the signature; the second recognises the same file.
    assert unchanged_since_last_parse(p, state_path=state) is True


def test_edited_file_is_parsed_again(tmp_path):
    state = tmp_path / "state.json"
    p = _write(tmp_path, "a.csv", "one")
    unchanged_since_last_parse(p, state_path=state)
    p.write_text("two — a genuinely different file")
    assert unchanged_since_last_parse(p, state_path=state) is False


def test_each_file_is_tracked_separately(tmp_path):
    state = tmp_path / "state.json"
    a = _write(tmp_path, "a.csv", "one")
    b = _write(tmp_path, "b.csv", "two")
    unchanged_since_last_parse(a, state_path=state)
    assert unchanged_since_last_parse(b, state_path=state) is False
    assert unchanged_since_last_parse(a, state_path=state) is True


def test_missing_file_is_never_reported_unchanged(tmp_path):
    state = tmp_path / "state.json"
    assert unchanged_since_last_parse(tmp_path / "gone.csv", state_path=state) is False


def test_corrupt_state_file_does_not_break_the_fetcher(tmp_path):
    """A bad cache must cause a re-parse, never a crash or a false skip."""
    state = tmp_path / "state.json"
    state.write_text("{not json")
    p = _write(tmp_path, "a.csv", "one")
    assert unchanged_since_last_parse(p, state_path=state) is False


def test_fetch_skips_files_it_has_already_parsed(tmp_path, monkeypatch):
    """The whole point: no second parse of an unchanged export.

    Without this the hourly task re-read 104 MB of spreadsheets to produce
    nothing, every hour, forever.
    """
    from app.sources import acled_fetcher as mod

    csv_path = tmp_path / "acled.csv"
    csv_path.write_text(
        "event_id_cnty,event_date,country,latitude,longitude,fatalities,event_type,notes\n"
        "ABC1,2026-07-01,Peru,-12.0,-77.0,3,Battles,test row\n"
    )
    state = tmp_path / "state.json"
    monkeypatch.setattr(mod, "_PARSE_STATE_PATH", state)
    monkeypatch.setattr(mod, "_local_paths", lambda: [csv_path])

    parses: list[Path] = []
    real_parse = mod.parse_acled_file

    def counting_parse(path, **kwargs):
        parses.append(path)
        return real_parse(path, **kwargs)

    monkeypatch.setattr(mod, "parse_acled_file", counting_parse)

    fetcher = mod.AcledFetcher()
    fetcher.fetch()
    assert len(parses) == 1, "first run must parse"

    fetcher.fetch()
    assert len(parses) == 1, "unchanged file must not be parsed again"

    # Touching the file brings it back.
    csv_path.write_text(
        "event_id_cnty,event_date,country,latitude,longitude,fatalities,event_type,notes\n"
        "ABC1,2026-07-01,Peru,-12.0,-77.0,3,Battles,test row\n"
        "ABC2,2026-07-02,Chile,-33.0,-70.0,1,Riots,another row\n"
    )
    fetcher.fetch()
    assert len(parses) == 2, "a changed file must be parsed again"
