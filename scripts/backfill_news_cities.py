"""One-off: backfill lat/lon/payload.city on existing RSS news rows.

Run once after the city-enrichment lookup lands so the rows that were
ingested before this change get pinpoint coords too.

Usage:
    python -m scripts.backfill_news_cities
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.db_models import EventRow
from app.enrichment.city import city_for

RSS_SOURCES = (
    "rss-bbc-world",
    "rss-bbc-uk",
    "rss-reuters-world",
    "rss-dawn",
    "rss-guardian-world",
    "rss-geo-english",
)

# Map source slug → country bias to feed city_for as a hint.
SOURCE_COUNTRY_HINT = {
    "rss-bbc-uk": "GB",
    "rss-dawn": "PK",
    "rss-geo-english": "PK",
}


def _read_batch(session: Session, after_id: int, batch_size: int = 500):
    stmt = (
        select(EventRow.id, EventRow.source, EventRow.payload, EventRow.country)
        .where(EventRow.source.in_(RSS_SOURCES))
        .where(EventRow.lat.is_(None))
        .where(EventRow.id > after_id)
        .order_by(EventRow.id)
        .limit(batch_size)
    )
    return session.execute(stmt).all()


def run() -> dict[str, int]:
    counts = defaultdict(int)
    with session_scope() as session:
        last_id = 0
        while True:
            rows = _read_batch(session, after_id=last_id)
            if not rows:
                break
            for row in rows:
                payload = row.payload or {}
                text = " ".join(
                    [
                        str(payload.get("title") or ""),
                        str(payload.get("summary") or ""),
                    ]
                )
                hint = SOURCE_COUNTRY_HINT.get(row.source) or row.country
                hit = city_for(text, country_hint=hint)
                if not hit:
                    counts[f"{row.source}:miss"] += 1
                    last_id = row.id
                    continue
                new_payload = dict(payload)
                new_payload["city"] = hit.name
                session.execute(
                    update(EventRow)
                    .where(EventRow.id == row.id)
                    .values(lat=hit.lat, lon=hit.lon, country=hit.iso, payload=new_payload)
                )
                counts[f"{row.source}:hit"] += 1
            session.commit()
            last_id = rows[-1].id

    return dict(counts)


def main() -> None:
    out = run()
    print("backfill summary:")
    for k, v in sorted(out.items()):
        print(f"  {k:32s} {v}")


if __name__ == "__main__":
    main()
