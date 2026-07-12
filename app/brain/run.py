"""Run the brain narrate once — `make brain` / `python -m app.brain.run`."""

from __future__ import annotations

from app.brain.task import _narrate_body


def main() -> None:
    result = _narrate_body()
    print(result)


if __name__ == "__main__":
    main()
