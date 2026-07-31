"""Re-resolve country / coords / scope on stored RSS news rows (#717).

The resolver runs at fetch time, so without this only rows ingested after
deploy get the fix. Retention is 30 days — the map would stay wrong for a
month otherwise.

Rewrites, per row: ``events.country``, ``events.lat``, ``events.lon``, and
``payload.city`` / ``payload.geo_basis`` / ``payload.news_scope`` /
``payload.enrichment_meta.geo_model``.

This **clears** as well as sets. A row tagged GB because it name-dropped
London, on a story about China, comes back either CN or null. That is the
point — the precision half of the issue is stale wrong values, and leaving
them in place would fix only half of what was measured.

Usage:
    .venv/bin/python -m scripts.backfill_news_geo [--batch-size 500] [--dry-run]
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.db_models import EventRow
from app.enrichment.geo import GEO_METHOD_VERSION, GeoVerdict, resolve_geo, resolved_news_scope
from app.sources.rss_registry import desk_country_map, load_feed_configs


def resolve_row(
    payload: dict,
    *,
    default_country: str | None,
    desk_country: str | None,
) -> GeoVerdict:
    """Run the resolver over one stored payload."""
    title = str(payload.get("title") or "")
    summary = str(payload.get("summary") or "")
    return resolve_geo(
        title,
        summary,
        desk_country=desk_country,
        city_hint=default_country,
    )


def _read_batch(session: Session, after_id: int, batch_size: int):
    stmt = (
        select(EventRow.id, EventRow.source, EventRow.payload, EventRow.country)
        .where(EventRow.source.like("rss-%"))
        .where(EventRow.id > after_id)
        .order_by(EventRow.id)
        .limit(batch_size)
    )
    return session.execute(stmt).all()


def run(batch_size: int = 500, *, dry_run: bool = False) -> dict[str, int]:
    defaults = {cfg.source: cfg.default_country for cfg in load_feed_configs()}
    desks = desk_country_map()
    counts: dict[str, int] = defaultdict(int)

    with session_scope() as session:
        last_id = 0
        while True:
            rows = _read_batch(session, last_id, batch_size)
            if not rows:
                break
            for row_id, source, payload, old_country in rows:
                last_id = row_id
                payload = dict(payload or {})
                verdict = resolve_row(
                    payload,
                    default_country=defaults.get(source),
                    desk_country=desks.get(source),
                )
                counts["seen"] += 1
                counts[f"basis:{verdict.basis}"] += 1
                if verdict.iso and not old_country:
                    counts["gained"] += 1
                elif old_country and not verdict.iso:
                    counts["cleared"] += 1
                elif old_country and verdict.iso and old_country != verdict.iso:
                    counts["changed"] += 1

                if dry_run:
                    continue

                payload["city"] = verdict.city
                payload["geo_basis"] = verdict.basis
                payload["news_scope"] = resolved_news_scope(
                    verdict.iso, verdict.lat, verdict.lon, defaults.get(source)
                )
                meta = dict(payload.get("enrichment_meta") or {})
                meta["geo_model"] = GEO_METHOD_VERSION
                payload["enrichment_meta"] = meta

                session.execute(
                    update(EventRow)
                    .where(EventRow.id == row_id)
                    .values(
                        country=verdict.iso,
                        lat=verdict.lat,
                        lon=verdict.lon,
                        payload=payload,
                    )
                )
            if not dry_run:
                session.commit()
            print(f"... {counts['seen']:,} rows", flush=True)

    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    args = parser.parse_args()

    counts = run(args.batch_size, dry_run=args.dry_run)
    for key in sorted(counts):
        print(f"{key:24} {counts[key]:,}")


if __name__ == "__main__":
    main()
