"""Run one enrichment pass — `make enrich` / `python -m app.brain.enrich_run`."""

from __future__ import annotations

from app.brain.enrich import _enrich_body


def main() -> None:
    print(_enrich_body())


if __name__ == "__main__":
    main()
