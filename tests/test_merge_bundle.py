"""Tests for the merge bundle scripts.

Only the parts that are decisions rather than SQL. The merge itself is
Postgres-shaped — `COPY`, a staging schema, `pg_get_serial_sequence` — and
mocking that would test the mock. It was instead rehearsed against a scratch
database seeded to reproduce the overlap: 8,000 rows sharing the source's id
range, and the invariants checked afterwards (no duplicated natural key, no
dangling reference, sequences past the shifted maximum, the destination's own
rows still present).

What is worth pinning here is the reference map. It is the thing that silently
breaks: a column added to the schema that points at an id, and not added here,
produces links that resolve to the wrong row with no error anywhere.
"""

from __future__ import annotations

from scripts.export_merge_bundle import BUNDLE_TABLES, copy_statement
from scripts.merge_bundle import EVENT_REFS, STORY_REFS


class TestCopyStatement:
    def test_events_can_have_a_source_left_out(self) -> None:
        sql = copy_statement("events", exclude_sources=["nasa-firms"])
        assert "WHERE source NOT IN ('nasa-firms')" in sql
        assert "TO STDOUT WITH CSV HEADER" in sql

    def test_several_sources_can_be_left_out(self) -> None:
        sql = copy_statement("events", exclude_sources=["nasa-firms", "opensky-adsb"])
        assert "'nasa-firms', 'opensky-adsb'" in sql

    def test_no_exclusion_asks_for_the_whole_table(self) -> None:
        assert "WHERE" not in copy_statement("events", exclude_sources=[])

    def test_only_events_is_filtered(self) -> None:
        # Nothing else carries a `source` column, and a story member whose event
        # was left out is the loader's to drop — it is the only side that knows
        # what the destination already holds.
        sql = copy_statement("story_members", exclude_sources=["nasa-firms"])
        assert "WHERE" not in sql


class TestReferenceMap:
    def test_every_table_naming_a_story_is_in_the_bundle(self) -> None:
        for table in STORY_REFS:
            assert table in BUNDLE_TABLES, table

    def test_every_table_naming_an_event_is_in_the_bundle(self) -> None:
        for table in EVENT_REFS:
            assert table in BUNDLE_TABLES, table

    def test_the_story_graph_travels_with_its_stories(self) -> None:
        # Exporting a story_* table without `stories` would shift its story_id
        # by an offset taken from a table that never arrived.
        assert "stories" in BUNDLE_TABLES
        assert "events" in BUNDLE_TABLES

    def test_a_nullable_event_reference_is_declared_as_such(self) -> None:
        # The bool decides whether an unresolvable row is emptied or deleted.
        # `story_members` exists to name an event, so a row that cannot name one
        # is meaningless; a sensor check keeps its verdict without a match.
        assert EVENT_REFS["story_members"] == (("event_id", False),)
        assert EVENT_REFS["story_sensor_checks"] == (("matched_event_id", True),)

    def test_the_reference_map_covers_the_schema(self) -> None:
        # The check this file exists for: a new column pointing at an id, not
        # listed here, produces links that resolve to the wrong row silently.
        from app import db_models

        declared = {(t, c) for t, cols in STORY_REFS.items() for c in cols}
        declared |= {(t, c) for t, cols in EVENT_REFS.items() for c, _ in cols}

        found: set[tuple[str, str]] = set()
        for mapper in db_models.Base.registry.mappers:
            table = mapper.class_.__tablename__
            if table not in BUNDLE_TABLES:
                continue
            for column in mapper.columns:
                name = column.name
                if name == "source_event_id" or name == "id":
                    continue
                if name.endswith("event_id") or name.endswith("story_id"):
                    found.add((table, name))

        assert found == declared, f"unmapped id references: {found - declared}"
