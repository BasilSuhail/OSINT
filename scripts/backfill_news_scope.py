"""One-off: tag existing RSS rows with payload.news_scope (#166).

Walks every rss-* row, re-runs the city lookup against the stored
title + summary, derives the local / world / unknown scope, and
writes it back into payload.

Usage:
    python -m scripts.backfill_news_scope
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.db_models import EventRow
from app.enrichment.city import city_for
from app.sources.rss_registry import load_feed_configs

NEWS_SOURCE_PREFIXES = ("rss-",)


def _default_country_per_source() -> dict[str, str | None]:
    return {cfg.source: cfg.default_country for cfg in load_feed_configs()}


def _read_batch(session: Session, after_id: int, batch_size: int = 500):
    stmt = (
        select(EventRow.id, EventRow.source, EventRow.payload)
        .where(EventRow.source.like("rss-%"))
        .where(EventRow.id > after_id)
        .order_by(EventRow.id)
        .limit(batch_size)
    )
    return session.execute(stmt).all()


def _classify(payload: dict, default_country: str | None) -> str:
    text = " ".join([str(payload.get("title") or ""), str(payload.get("summary") or "")]).strip()
    if not text:
        return "unknown"
    hit = city_for(text, country_hint=default_country)
    if hit is None:
        return "unknown"
    if default_country is None:
        return "local"
    return "local" if hit.iso == default_country else "world"


def run() -> dict[str, int]:
    defaults = _default_country_per_source()
    counts: dict[str, int] = defaultdict(int)
    with session_scope() as session:
        last_id = 0
        while True:
            rows = _read_batch(session, after_id=last_id)
            if not rows:
                break
            for row in rows:
                payload = row.payload or {}
                if "news_scope" in payload:
                    counts[f"{row.source}:skip"] += 1
                    last_id = row.id
                    continue
                scope = _classify(payload, defaults.get(row.source))
                new_payload = dict(payload)
                new_payload["news_scope"] = scope
                session.execute(
                    update(EventRow).where(EventRow.id == row.id).values(payload=new_payload)
                )
                counts[f"{row.source}:{scope}"] += 1
            session.commit()
            last_id = rows[-1].id

    return dict(counts)


def main() -> None:
    out = run()
    print("backfill summary:")
    for k, v in sorted(out.items()):
        print(f"  {k:40s} {v}")


if __name__ == "__main__":
    main()
