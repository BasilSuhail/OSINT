"""One-off: backfill payload.sentiment on existing RSS / UK Police rows.

Run once after the sentiment-enrichment lookup lands so the rows that were
ingested before this change get their compound score too.

Usage:
    python -m scripts.backfill_news_sentiment
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.db_models import EventRow
from app.enrichment.sentiment import SENTIMENT_METHOD_VERSION, score_text

NEWS_SOURCES = (
    "rss-bbc-world",
    "rss-bbc-uk",
    "rss-reuters-world",
    "rss-dawn",
    "rss-guardian-world",
    "rss-geo-english",
    "uk-police",
)


def _read_batch(session: Session, after_id: int, batch_size: int = 500):
    stmt = (
        select(EventRow.id, EventRow.source, EventRow.payload)
        .where(EventRow.source.in_(NEWS_SOURCES))
        .where(EventRow.id > after_id)
        .order_by(EventRow.id)
        .limit(batch_size)
    )
    return session.execute(stmt).all()


def _needs_backfill(payload: dict | None) -> bool:
    if not payload:
        return False
    return not ("sentiment" in payload and payload["sentiment"] is not None)


def run() -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    with session_scope() as session:
        last_id = 0
        while True:
            rows = _read_batch(session, after_id=last_id)
            if not rows:
                break
            for row in rows:
                payload = row.payload or {}
                if not _needs_backfill(payload):
                    counts[f"{row.source}:skip"] += 1
                    last_id = row.id
                    continue
                text = " ".join(
                    [
                        str(payload.get("title") or ""),
                        str(payload.get("summary") or ""),
                    ]
                ).strip()
                hit = score_text(text)
                if hit is None:
                    counts[f"{row.source}:miss"] += 1
                    last_id = row.id
                    continue
                new_payload = dict(payload)
                new_payload["sentiment"] = hit.compound
                new_payload["sentiment_label"] = hit.label
                meta = dict(new_payload.get("enrichment_meta") or {})
                meta["sentiment_model"] = SENTIMENT_METHOD_VERSION
                new_payload["enrichment_meta"] = meta
                session.execute(
                    update(EventRow).where(EventRow.id == row.id).values(payload=new_payload)
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
