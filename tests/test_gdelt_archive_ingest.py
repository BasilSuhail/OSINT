"""Walking a day of the export grid (#555)."""

import io
import zipfile
from datetime import date

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backtest import gdelt_archive
from app.db_models import Base
from app.sources.gdelt_parser import MIN_FIELD_COUNT


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _csv_body(*, num_mentions: str = "2") -> str:
    fields = [""] * MIN_FIELD_COUNT
    fields[0] = "1000000001"
    fields[1] = "20260618"
    fields[28] = "18"
    fields[30] = "-8.0"
    fields[31] = num_mentions
    fields[52] = "UP"
    return "\t".join(fields)


def _zipped(body: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("20260618000000.export.CSV", body)
    return buffer.getvalue()


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_day_stamps_covers_the_whole_grid():
    stamps = gdelt_archive.day_stamps(date(2026, 6, 18))
    assert len(stamps) == gdelt_archive.FILES_PER_DAY
    assert stamps[0] == "20260618000000"
    assert stamps[1] == "20260618001500"
    assert stamps[-1] == "20260618234500"


def test_ingest_day_counts_every_file_and_records_the_day():
    session = _session()
    with _client(lambda request: httpx.Response(200, content=_zipped(_csv_body()))) as client:
        result = gdelt_archive.ingest_day(session, date(2026, 6, 18), client=client, concurrency=4)

    assert result["files_ok"] == gdelt_archive.FILES_PER_DAY
    assert result["files_missing"] == 0
    # 96 files, one row each, 2 mentions per row.
    assert gdelt_archive.daily_volume(session, "UA", date(2026, 6, 18), date(2026, 6, 18)) == {
        date(2026, 6, 18): 192
    }


def test_a_missing_file_is_counted_not_fatal():
    session = _session()
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        if len(seen) <= 3:
            return httpx.Response(404)
        return httpx.Response(200, content=_zipped(_csv_body()))

    with _client(handler) as client:
        result = gdelt_archive.ingest_day(session, date(2026, 6, 18), client=client, concurrency=1)

    assert result["files_missing"] == 3
    assert result["files_ok"] == gdelt_archive.FILES_PER_DAY - 3


def test_a_day_that_mostly_404s_is_not_readable_afterwards():
    # Recorded, so it can be found and re-walked — but not trusted as volume.
    session = _session()
    with _client(lambda request: httpx.Response(404)) as client:
        gdelt_archive.ingest_day(session, date(2026, 6, 18), client=client, concurrency=4)
    assert gdelt_archive.ingested_days(session, date(2026, 6, 18), date(2026, 6, 18)) == set()


def test_ingesting_a_day_twice_does_not_double_its_volume():
    session = _session()
    with _client(lambda request: httpx.Response(200, content=_zipped(_csv_body()))) as client:
        gdelt_archive.ingest_day(session, date(2026, 6, 18), client=client, concurrency=4)
        gdelt_archive.ingest_day(session, date(2026, 6, 18), client=client, concurrency=4)
    assert gdelt_archive.daily_volume(session, "UA", date(2026, 6, 18), date(2026, 6, 18)) == {
        date(2026, 6, 18): 192
    }


def test_read_export_survives_a_corrupt_zip():
    with _client(lambda request: httpx.Response(200, content=b"not a zip")) as client:
        assert gdelt_archive.read_export(client, "20260618000000") is None
