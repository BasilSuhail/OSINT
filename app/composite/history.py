"""Persisted composite signal history (issue #586).

The composite z-scores each country against its own past, needing three prior
monthly observations before it emits anything but the neutral 0.5. It used to
rebuild that past from the events table on every run — but retention keeps ~30
days, so the events table can only ever show one or two months. 183 of 184
countries sat permanently below the threshold and every live score was exactly
0.5.

The aggregate is the part worth keeping: one value per (country, month,
domain), a few thousand rows a year against a 30 GB cap. Persisting it lets the
analysis history outlive the events it was derived from, so the normaliser
finally has something to normalise against.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db_models import CompositeSignalRow

#: The shape both the aggregation layer and this module speak:
#: {(country, month_start): {domain: value}}.
Signals = dict[tuple[str, datetime], dict[str, float]]


def persist_signals(signals: Signals, session: Session) -> int:
    """Upsert every (country, month, domain) value. Returns rows written."""
    rows = [
        {"country": country, "bucket_start": bucket_start, "domain": domain, "value": value}
        for (country, bucket_start), domains in signals.items()
        for domain, value in domains.items()
    ]
    if not rows:
        return 0

    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        base = pg_insert(CompositeSignalRow).values(rows)
    elif dialect == "sqlite":
        base = sqlite_insert(CompositeSignalRow).values(rows)
    else:
        raise NotImplementedError(f"persist_signals does not support dialect {dialect!r}")

    stmt = base.on_conflict_do_update(
        index_elements=["country", "bucket_start", "domain"],
        set_={"value": base.excluded.value},
    )
    session.execute(stmt)
    return len(rows)


def load_signals(session: Session, since: datetime | None = None) -> Signals:
    """Read stored history back into the aggregation layer's shape."""
    stmt = select(
        CompositeSignalRow.country,
        CompositeSignalRow.bucket_start,
        CompositeSignalRow.domain,
        CompositeSignalRow.value,
    )
    if since is not None:
        stmt = stmt.where(CompositeSignalRow.bucket_start >= since)

    out: Signals = {}
    for country, bucket_start, domain, value in session.execute(stmt).all():
        # Buckets are always UTC month starts by construction (`month_start_utc`);
        # SQLite drops tzinfo on round-trip, so re-attach it.
        if bucket_start.tzinfo is None:
            bucket_start = bucket_start.replace(tzinfo=UTC)
        out.setdefault((country, bucket_start), {})[domain] = value
    return out


def merge_signals(stored: Signals, current: Signals) -> Signals:
    """Overlay this run's freshly aggregated months on the stored history.

    The current run wins per domain: the month in progress is recomputed from
    live events every time, so the stored copy of it is one run stale by
    definition. Domains the current run did not produce keep their stored value
    — a quiet month for one domain must not erase what the others recorded.
    """
    merged: Signals = {key: dict(domains) for key, domains in stored.items()}
    for key, domains in current.items():
        merged.setdefault(key, {}).update(domains)
    return merged
