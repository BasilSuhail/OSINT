"""Canonical Pydantic models shared across the pipeline.

Mirrors the `events` table in `docs/architecture/04-schema.md`. Fetchers return
lists of `Event`; the ingest task is the only place that touches the database.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Category(StrEnum):
    """Cross-source category vocabulary.

    Composite worker only consumes events where category is one of
    `MARKET`, `GEOPOLITICAL`, `HAZARD`. Everything else is Layer 3 dashboard.
    See `docs/architecture/04-schema.md` for the full vocabulary.
    """

    MARKET = "market"
    GEOPOLITICAL = "geopolitical"
    HAZARD = "hazard"
    WEATHER = "weather"
    TRACKING = "tracking"
    SPACE = "space"
    NEWS = "news"
    CYBER = "cyber"
    MESH = "mesh"


class Event(BaseModel):
    """A single canonical event row produced by any fetcher."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(..., min_length=1, description="Source slug, e.g. 'yfinance', 'gdelt'.")
    source_event_id: str = Field(..., min_length=1, description="Stable per-source identifier.")
    occurred_at: datetime = Field(..., description="Event time (not fetch time).")
    fetched_at: datetime = Field(..., description="When the fetcher pulled it.")
    category: Category
    severity: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    keywords: list[str] = Field(default_factory=list)
    country: str | None = Field(default=None, description="ISO 3166-1 alpha-2, uppercase.")
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    payload: dict[str, Any] = Field(..., description="Full source-specific record for replay.")

    @field_validator("country")
    @classmethod
    def _country_uppercase(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) != 2:
            raise ValueError("country must be ISO 3166-1 alpha-2 (2 chars)")
        return value.upper()
