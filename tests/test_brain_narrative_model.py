from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db_models import Base, BrainNarrativeRow


def test_brain_narrative_roundtrip():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            BrainNarrativeRow(
                created_at=datetime(2026, 7, 12, tzinfo=UTC),
                model="qwen2.5:1.5b-instruct-q4_K_M",
                payload={"headline": "quiet", "watch": []},
                input_digest="sha256:abc",
            )
        )
        session.commit()
        row = session.execute(select(BrainNarrativeRow)).scalar_one()
        assert row.payload["headline"] == "quiet"
        assert row.input_digest == "sha256:abc"
