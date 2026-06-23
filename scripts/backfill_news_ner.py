"""One-off: tag existing RSS rows with payload.entities + enrichment_meta.ner_model.

Walks every rss-* row, runs NER on title + summary, writes results back.
No-op rows when spaCy isn't installed (the wrapper returns []).

Usage:
    python -m scripts.backfill_news_ner
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.db_models import EventRow
from app.enrichment.ner import (
    NER_METHOD_VERSION,
    entities_to_payload,
    extract_entities,
    is_available,
)


def _read_batch(session: Session, after_id: int, batch_size: int = 500):
    stmt = (
        select(EventRow.id, EventRow.source, EventRow.payload)
        .where(EventRow.source.like("rss-%"))
        .where(EventRow.id > after_id)
        .order_by(EventRow.id)
        .limit(batch_size)
    )
    return session.execute(stmt).all()


def run() -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    if not is_available():
        print("spaCy unavailable — nothing to do. Install with `.[nlp]` extra.")
        return {}
    with session_scope() as session:
        last_id = 0
        while True:
            rows = _read_batch(session, after_id=last_id)
            if not rows:
                break
            for row in rows:
                payload = row.payload or {}
                if "entities" in payload:
                    counts[f"{row.source}:skip"] += 1
                    last_id = row.id
                    continue
                text = " ".join(
                    [str(payload.get("title") or ""), str(payload.get("summary") or "")]
                ).strip()
                ents = extract_entities(text)
                new_payload = dict(payload)
                new_payload["entities"] = entities_to_payload(ents)
                meta = dict(new_payload.get("enrichment_meta") or {})
                meta["ner_model"] = NER_METHOD_VERSION
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
        print(f"  {k:40s} {v}")


if __name__ == "__main__":
    main()
