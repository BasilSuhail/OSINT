"""Run retention and the disk cap now — `make data-prune`.

Same code path as the scheduled 03:00 UTC pass, so this is the way to see what
housekeeping would do without waiting for it.

Lives under ``app/`` rather than in ``scripts/`` because it runs wherever the
Makefile's ``RUN_PY`` points, and on an install with no host virtualenv that is
the worker container — which copies ``app/`` and not ``scripts/``. The previous
version was unreachable there, so ``make data-prune`` only worked for somebody
who had built a virtualenv the README never asks for.

The vacuum is best effort. The deletes are already committed by the time it runs,
so a vacuum that fails has cost nothing but disk that a later pass will reclaim.
"""

from __future__ import annotations

import json

from app.db import session_scope
from app.housekeeping import run_retention_and_cap, vacuum_events


def main() -> int:
    with session_scope() as session:
        result = run_retention_and_cap(session)
        bind = session.get_bind()
    print(json.dumps(result))
    try:
        vacuum_events(bind)
    except Exception as exc:
        print(f"warning: VACUUM failed (non-fatal): {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
