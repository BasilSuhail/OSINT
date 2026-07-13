from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db_models import Base, BrainNarrativeRow
from app.housekeeping import prune_brain_narrative


def test_prune_deletes_rows_older_than_30_days():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 12, tzinfo=UTC)
    with Session(engine) as session:
        session.add(
            BrainNarrativeRow(
                created_at=now - timedelta(days=31),
                model="m",
                payload={},
                input_digest="sha256:old",
            )
        )
        session.add(
            BrainNarrativeRow(
                created_at=now - timedelta(days=1),
                model="m",
                payload={},
                input_digest="sha256:new",
            )
        )
        session.commit()
        deleted = prune_brain_narrative(session, now=now)
        session.commit()
        assert deleted == 1
        remaining = session.execute(select(BrainNarrativeRow.input_digest)).scalars().all()
        assert remaining == ["sha256:new"]
