"""The evidence one fetch run leaves behind (#848).

Transport success, usable output and new rows are separate claims.  This
module gives the universal fetch wrapper one vocabulary for those claims so
the API, console and watchdog cannot reinterpret an empty list differently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OutputState = Literal["new_data", "unchanged", "empty", "misconfigured", "failed"]


@dataclass(frozen=True)
class IngestOutcome:
    """Counts and classification for one completed fetch attempt."""

    state: OutputState
    fetched: int = 0
    accepted: int = 0
    affected: int = 0
    inserted: int = 0
    rejected: int = 0


def classify(
    *,
    fetched: int,
    accepted: int,
    affected: int,
    inserted: int,
    rejected: int,
    unchanged_hint: bool = False,
) -> IngestOutcome:
    """Classify a non-exceptional run from measured row movement.

    ``unchanged_hint`` is reserved for a fetcher which proved that a static
    input revision was already parsed.  It cannot turn rejected or accepted
    rows into an unchanged check.
    """
    counts = (fetched, accepted, affected, inserted, rejected)
    if any(value < 0 for value in counts):
        raise ValueError("ingest outcome counts cannot be negative")
    if accepted + rejected > fetched:
        raise ValueError("accepted and rejected rows cannot exceed fetched rows")
    if inserted > affected or affected > accepted:
        raise ValueError("inserted <= affected <= accepted must hold")

    if unchanged_hint and fetched == accepted == rejected == 0:
        state: OutputState = "unchanged"
    elif accepted == 0:
        state = "empty"
    elif inserted > 0:
        state = "new_data"
    else:
        state = "unchanged"
    return IngestOutcome(
        state=state,
        fetched=fetched,
        accepted=accepted,
        affected=affected,
        inserted=inserted,
        rejected=rejected,
    )


def terminal(
    state: Literal["misconfigured", "failed"],
    *,
    fetched: int = 0,
    rejected: int = 0,
) -> IngestOutcome:
    """Outcome for a run that did not reach usable-output classification.

    A failure can happen after transport succeeded. Preserve row evidence
    already measured at that point while leaving accepted output at zero.
    """
    if fetched < 0 or rejected < 0:
        raise ValueError("ingest outcome counts cannot be negative")
    if rejected > fetched:
        raise ValueError("rejected rows cannot exceed fetched rows")
    return IngestOutcome(state=state, fetched=fetched, rejected=rejected)
